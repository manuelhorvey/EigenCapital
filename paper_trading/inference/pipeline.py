import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from features.contract import validate_no_cross_asset_leakage
from features.regime_features import generate_regime_features
from features.registry import FEATURE_REGISTRY
from paper_trading.entry.decision import SignalType, TradeDecision
from paper_trading.governance.drift import get_shadow_intelligence as _get_drift
from paper_trading.governance.risk import evaluate as _risk_evaluate
from paper_trading.ops import diagnostics as diag
from paper_trading.ops import wrappers as _w
from paper_trading.ops.data_fetcher import fetch_live, fetch_ref
from paper_trading.ops.tracer import (
    shadow_compare_signal,
    shadow_compare_sizing,
    trace_decision,
    trace_diagnostic_report,
)
from paper_trading.shadow.actions import compute_shadow_actions as _compute_shadow
from paper_trading.shadow.feedback import record_shadow_feedback as _record_feedback
from paper_trading.shadow.learning import compile_shadow_learning as _compile_learning
from paper_trading.shadow.memory import store_event as _shadow_store

logger = logging.getLogger("quantforge.inference_pipeline")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ET = pytz.timezone("US/Eastern")


class AssetInferencePipeline:
    def __init__(self, asset):
        self.asset = asset

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        asset = self.asset
        asset._ensure_position_synced()
        if not asset._trained:
            asset.train()

        df = fetch_live(asset.ticker)

        # Sync with latest price (same as dashboard) to ensure responsive SL/TP
        asset.refresh_price()
        if asset.current_price is not None:
            # Update the last row's close with the real-time price
            df.loc[df.index[-1], "close"] = asset.current_price

        asset.price_data = df
        asset._refresh_liquidity(df)
        df["close"] = df["close"].ffill()
        ref = None
        if getattr(asset.contract, "vs_spy_windows", ()):
            ref = fetch_ref("SPY")
        macro = asset._feature_pipeline.macro_derived(
            pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet"))
        )
        features_df = asset._feature_pipeline.build(df, macro, ref, asset.contract)
        validate_no_cross_asset_leakage(features_df, asset.contract, known_slugs=FEATURE_REGISTRY.keys())

        # ── Archetype Inference Features (not passed to XGBoost) ──
        # ADX, RSI, BB z-score, EMA spread for ArchetypeClassifier.
        # These are computed from OHLCV after contract validation to avoid
        # FeatureContract schema rejection. They are inference-only and
        # never enter the XGBoost feature set — no train/serve skew risk.
        import ta
        ema_20 = ta.trend.ema_indicator(df["close"], window=20)
        ema_50 = ta.trend.ema_indicator(df["close"], window=50)
        features_df["ema_spread"] = ((ema_20 - ema_50) / ema_50).reindex(features_df.index)

        features_df["adx"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14).reindex(features_df.index)
        features_df["rsi"] = ta.momentum.rsi(df["close"], window=14).reindex(features_df.index)

        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        bb_mavg = bb.bollinger_mavg()
        bb_std = bb.bollinger_hband() - bb_mavg
        features_df["bb_zscore"] = ((df["close"] - bb_mavg) / (bb_std / 2)).reindex(features_df.index)

        for col in ["adx", "rsi", "bb_zscore", "ema_spread"]:
            if col in features_df.columns and features_df[col].isna().any():
                n_nan = features_df[col].isna().sum()
                logger.warning(
                    "%s: archetype feature '%s' has %d NaN rows "
                    "(need >=%d bars of OHLCV data) — "
                    "classifier will fall back to defaults",
                    asset.name, col, n_nan,
                    14 if col in ("adx", "rsi") else 20,
                )

        X = features_df[asset.features]
        if len(X) == 0:
            raise ValueError(f"No valid feature rows after building features for {asset.name}")

        # PSI drift: rolling 21d distribution vs training baseline
        try:
            latest_df, _ = asset._importance_store.get_latest_two_snapshots(asset.name)
            if latest_df is not None and not latest_df.empty:
                top10 = latest_df[latest_df["rank"] <= 10]
                top_features = [(r["feature"], r["importance_score"]) for r in top10.to_dict("records")]
                X_current = X.tail(21)
                asset._last_psi_drift = asset._psi_monitor.compute_drift(asset.name, X_current, top_features)
        except Exception as e:
            logger.debug("%s: PSI drift skipped: %s", asset.name, e)

        proba = asset._model_iface.predict(asset.model, X)
        if proba.shape[1] < 3:
            raise ValueError(f"Model returned {proba.shape[1]} classes, expected 3")

        # Meta-label inference
        asset._last_meta_proba = None
        if asset._meta_label_model is not None and asset._meta_label_model._trained:
            try:
                asset._last_meta_proba = asset._meta_label_model.predict_proba(X, proba)
            except Exception as e:
                logger.debug("%s: meta-label inference failed: %s", asset.name, e)

        sizing_cfg = asset._sizing_config(df["close"])
        if asset.config.get("regime_sizing"):
            regime_features_df = generate_regime_features(df)
            regime_results = asset.regime_classifier.classify(regime_features_df)
            current_regime = regime_results["regime"].iloc[-1]
            asset._current_regime = current_regime
            pos_size = asset._sizing_strategy.compute(df["close"], sizing_cfg, regime=current_regime)
        else:
            asset._current_regime = "neutral"
            pos_size = asset._sizing_strategy.compute(df["close"], sizing_cfg)

        result = asset._signal_strategy.compute(proba, X.index, threshold, df["close"], pos_size)

        # Phase 3: Archetype Classification (Structural Context)
        archetype = "UNKNOWN"
        if asset._archetype_classifier is not None:
            try:
                # Use current feature row for classification
                # Must use features_df (includes archetype columns adx/rsi/bb_zscore/ema_spread)
                # not X (which is XGBoost-only features)
                archetype_enum = asset._archetype_classifier.classify(features_df.iloc[-1])
                archetype = archetype_enum.value
            except Exception as e:
                logger.debug("%s: archetype classification failed: %s", asset.name, e)

        self._record_inference_proxies(proba, X, result.signal_type)
        asset.signal_data = result.signal_data

        latest = asset.signal_data.iloc[-1]
        asset.last_signal_date = latest.name

        decision = TradeDecision(
            asset=asset.name,
            signal=SignalType(result.signal_type),
            label=result.label,
            confidence=result.confidence_pct,
            prob_long=round(float(latest["prob_long"]), 4),
            prob_short=round(float(latest["prob_short"]), 4),
            prob_neutral=round(float(latest["prob_neutral"]), 4),
            close_price=round(float(latest["close"]), 4),
            timestamp=str(datetime.now(tz=ET).date()),
            position_size=float(pos_size),
            archetype=archetype,
        )

        asset._apply_decision(decision, df)

        trace_decision(
            asset=asset.name,
            features={k: round(float(v), 6) for k, v in X.iloc[-1].items()},
            proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            pos_size=float(pos_size),
            close_price=float(latest["close"]),
            current_side=asset.pos_mgr.current_side(),
            halt_flags=asset.check_halt_conditions(),
        )

        _shadow_signal_df = _w.compute_signals(proba, X.index, threshold)
        _shadow_latest = _shadow_signal_df.iloc[-1]
        _shadow_stype, _shadow_conf, _shadow_conf_pct = _w.signal_type_and_confidence(
            int(_shadow_latest["signal"]),
            float(_shadow_latest["prob_long"]),
            float(_shadow_latest["prob_short"]),
        )
        shadow_compare_signal(
            asset=asset.name,
            proba_produced=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            wrapper_signal=_shadow_stype,
            wrapper_confidence=_shadow_conf_pct,
            original_signal=decision.signal,
            original_confidence=decision.confidence,
        )

        _shadow_size = _w.compute_vol_scalar(df["close"]) if asset.config.get("vol_scalar") else 1.0
        shadow_compare_sizing(
            asset=asset.name,
            wrapper_size=_shadow_size,
            original_size=float(pos_size),
        )

        try:
            _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
            _sig_div = diag.analyze_signal_divergence(
                _proba_list,
                threshold,
                decision.signal,
                decision.confidence,
                _shadow_stype,
                _shadow_conf_pct,
            )
            _mod_div = diag.analyze_model_distribution(asset.name, _proba_list)
            _feat_drivers = diag.analyze_feature_impact(
                asset.model,
                X.iloc[[-1]],
                asset.features,
                proba[-1:],
            )
            _regime = diag.analyze_regime_context(df["close"])
            _report = diag.build_shadow_report(
                asset=asset.name,
                timestamp=str(datetime.now(tz=ET).date()),
                signal_match=_sig_div["match"],
                signal_divergence=_sig_div,
                model_divergence=_mod_div,
                feature_drivers=_feat_drivers,
                regime_context=_regime,
            )
            trace_diagnostic_report(_report)
            _shadow_store(asset.name, _report)
            asset._risk_signal = _risk_evaluate(asset.name)
            asset._shadow_drift_intel = _get_drift(asset.name)
            asset._shadow_action = _compute_shadow(
                asset=asset.name,
                state=None,
                drift_report=asset._shadow_drift_intel,
                risk_signal=asset._risk_signal,
            )
            _record_feedback(
                asset=asset.name,
                signal_data={"signal": decision.signal, "confidence": decision.confidence},
                drift=asset._shadow_drift_intel,
                risk=asset._risk_signal,
                action=asset._shadow_action,
            )
            asset._shadow_learning = _compile_learning(
                asset=asset.name,
                feedback_logs=None,
                drift_history=asset._shadow_drift_intel,
                risk_history=asset._risk_signal,
            )
        except Exception:
            logger.debug("%s: shadow learning feedback skipped", asset.name)

        asset._reg.validate_strategies(
            asset.name,
            {
                "_model": asset._model_iface,
                "_signal": asset._signal_strategy,
                "_sizing": asset._sizing_strategy,
                "_pnl": asset._pnl_strategy,
                "_feature_pipeline": asset._feature_pipeline,
            },
        )

        return asset._decision_to_dict(decision)

    def _record_inference_proxies(self, proba: np.ndarray, X: pd.DataFrame, signal: str) -> None:
        """Store macro vs blend directions for adaptive weight feedback on trade close."""
        asset = self.asset
        asset._last_macro_dir = None
        asset._last_blend_dir = None
        asset._entry_signal_dir = 1 if signal == "BUY" else (-1 if signal == "SELL" else 0)

        macro_head = getattr(asset.model, "macro_head", None) if asset.model else None
        if macro_head is None or X.empty:
            return
        try:
            macro_cols = [c for c in macro_head.features if c in X.columns]
            if len(macro_cols) < 3:
                return
            macro_probs = macro_head.predict_proba(X.iloc[[-1]][macro_cols])[0]
            asset._last_macro_dir = int(np.argmax(macro_probs)) - 1
            asset._last_blend_dir = int(np.argmax(proba[-1])) - 1
        except Exception:
            logger.debug("%s: macro proxy inference failed", asset.name)
