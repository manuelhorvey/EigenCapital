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

        # Normalise index to TZ-naive date to match alpha feature alignment
        # norm_index localises to US/Eastern; for FX crosses (24h in UTC) this
        # shifts the date by a day, breaking close.reindex(alpha_index).
        # Convert to UTC first so the extracted date matches fetch_yf_series.
        if df.index.tz is not None:
            df.index = pd.to_datetime(df.index.tz_convert("UTC").date)
        else:
            df.index = pd.to_datetime(df.index.date)

        # Sync with latest price (same as dashboard) to ensure responsive SL/TP
        asset.refresh_price()
        if asset.current_price is not None:
            df.loc[df.index[-1], "close"] = asset.current_price

        asset.price_data = df
        asset._refresh_liquidity(df)
        df["close"] = df["close"].ffill()

        # ── Build alpha features ──
        from features.alpha_features import build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv

        hist_prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(
            asset.name, asset.ticker,
        )
        alpha_df = build_alpha_features(
            hist_prices, rate_diffs,
            dxy=dxy, vix=vix, spx=spx, commodities=commodities,
        )

        # ── Build archetype features on full-history OHLCV ──
        alpha_idx = alpha_df.index
        ohlcv = fetch_asset_ohlcv(asset.ticker)
        if not ohlcv.empty:
            ohlcv = ohlcv.reindex(alpha_idx).ffill()
        archetype_df = pd.DataFrame(index=alpha_idx)
        import ta
        if not ohlcv.empty:
            ema_20 = ta.trend.ema_indicator(ohlcv["close"], window=20)
            ema_50 = ta.trend.ema_indicator(ohlcv["close"], window=50)
            archetype_df["ema_spread"] = ((ema_20 - ema_50) / ema_50).reindex(alpha_idx)
            archetype_df["adx"] = ta.trend.adx(ohlcv["high"], ohlcv["low"], ohlcv["close"], window=14).reindex(alpha_idx)
            archetype_df["rsi"] = ta.momentum.rsi(ohlcv["close"], window=14).reindex(alpha_idx)
            bb = ta.volatility.BollingerBands(ohlcv["close"], window=20, window_dev=2)
            bb_mavg = bb.bollinger_mavg()
            bb_std = bb.bollinger_hband() - bb_mavg
            archetype_df["bb_zscore"] = ((ohlcv["close"] - bb_mavg) / (bb_std / 2)).reindex(alpha_idx)

        for col in ["adx", "rsi", "bb_zscore", "ema_spread"]:
            if col in archetype_df.columns and archetype_df[col].isna().any():
                n_nan = archetype_df[col].isna().sum()
                if n_nan > 30:
                    logger.warning(
                        "%s: archetype feature '%s' has %d NaN rows "
                        "(classifier will fall back to defaults)",
                        asset.name, col, n_nan,
                    )

        feature_cols = getattr(asset, "_alpha_feature_cols", None)
        if not feature_cols:
            feature_cols = [c for c in alpha_df.columns]
            asset._alpha_feature_cols = feature_cols

        available = [c for c in feature_cols if c in alpha_df.columns]
        if not available:
            raise ValueError(f"No alpha feature columns found for {asset.name}")

        X = alpha_df[available]
        features_df = pd.concat([alpha_df, archetype_df], axis=1)

        # PSI drift: skip first cycle (warm-up), then rolling 21d vs baseline
        if not getattr(asset, "_psi_drift_initialized", False):
            asset._psi_drift_initialized = True
        else:
            try:
                latest_df, _ = asset._importance_store.get_latest_two_snapshots(asset.name)
                if latest_df is not None and not latest_df.empty:
                    top10 = latest_df[latest_df["rank"] <= 10]
                    top_features = [(r["feature"], r["importance_score"]) for r in top10.to_dict("records")]
                    X_current = X.tail(21)
                    asset._last_psi_drift = asset._psi_monitor.compute_drift(asset.name, X_current, top_features)
            except Exception as e:
                logger.debug("%s: PSI drift skipped: %s", asset.name, e)

        raw = asset._model_iface.predict(asset.model, X)
        # Binary model -> expand to 3-column format for pipeline compatibility
        if raw.shape[1] == 2:
            p_long = raw[:, 1].reshape(-1, 1)
            proba = np.column_stack([1.0 - raw[:, 1], np.zeros(raw.shape[0]), raw[:, 1]])
        elif raw.shape[1] >= 3:
            proba = raw[:, :3]
        else:
            raise ValueError(f"Model returned {raw.shape[1]} columns, expected >=2")

        # ── Ensemble: blend base + regime model if available ──
        ensemble = getattr(asset, "_ensemble", None)
        if ensemble is not None and getattr(asset, "_regime_model", None) is not None:
            regime_feats = getattr(asset, "regime_feature_names", None)
            if regime_feats:
                regime_available = [c for c in regime_feats if c in features_df.columns]
                if regime_available:
                    try:
                        regime_raw = asset._regime_model.predict_proba(features_df)
                        regime_p_long = regime_raw[:, 1]
                        base_p_long = raw[:, 1]
                        three_col, ensemble_signals = ensemble.combine_and_expand(base_p_long, regime_p_long)
                        proba = three_col
                        logger.debug("%s: ensemble blended (base=%.2f regime=%.2f)",
                                     asset.name, ensemble.base_weight, ensemble.regime_weight)
                    except Exception as e:
                        logger.debug("%s: ensemble inference failed: %s", asset.name, e)

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

        # ── Ensemble breakdown logging ──
        asset._ensemble_breakdown = {}
        try:
            latest_row = alpha_df.iloc[-1]
            asset_name_u = asset.name.upper()
            carry_val = latest_row.get(f"{asset_name_u}_carry_vol_adj", np.nan)
            mom_21 = latest_row.get(f"{asset_name_u}_mom_21d", np.nan)
            mom_63 = latest_row.get(f"{asset_name_u}_mom_63d", np.nan)
            zscore_val = latest_row.get(f"{asset_name_u}_zscore_20", np.nan)
            dow_val = latest_row.get(f"{asset_name_u}_dow_signal", np.nan)
            vol_ratio = latest_row.get(f"{asset_name_u}_vol_ratio", np.nan)
            asset._ensemble_breakdown = {
                "xgb_prob": round(float(proba[-1, 2]), 4),
                "carry_normalized": round(float(carry_val), 4) if not np.isnan(carry_val) else 0.0,
                "mom_normalized": round(float(mom_21 * 0.6 + mom_63 * 0.4), 4) if not (np.isnan(mom_21) or np.isnan(mom_63)) else 0.0,
                "reversion_normalized": round(float(zscore_val * -0.1), 4) if not np.isnan(zscore_val) else 0.0,
                "dow_signal": round(float(dow_val), 4) if not np.isnan(dow_val) else 0.0,
                "vol_ratio": round(float(vol_ratio), 4) if not np.isnan(vol_ratio) else 0.0,
                "ensemble_score": round(float(result.confidence_pct / 100.0), 4),
            }
            logger.info(
                "%s ensemble breakdown — xgb=%.4f carry=%.4f mom=%.4f rev=%.4f dow=%.4f vol=%.4f score=%.4f",
                asset.name,
                asset._ensemble_breakdown["xgb_prob"],
                asset._ensemble_breakdown["carry_normalized"],
                asset._ensemble_breakdown["mom_normalized"],
                asset._ensemble_breakdown["reversion_normalized"],
                asset._ensemble_breakdown["dow_signal"],
                asset._ensemble_breakdown["vol_ratio"],
                asset._ensemble_breakdown["ensemble_score"],
            )
        except Exception as e:
            logger.debug("%s: ensemble breakdown logging failed: %s", asset.name, e)

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

        close_price = float(latest["close"])
        if pd.isna(close_price) or close_price == 0.0:
            close_price = float(df["close"].ffill().iloc[-1])
        if pd.isna(close_price) and asset.current_price is not None:
            close_price = float(asset.current_price)

        decision = TradeDecision(
            asset=asset.name,
            signal=SignalType(result.signal_type),
            label=result.label,
            confidence=result.confidence_pct,
            prob_long=round(float(latest["prob_long"]), 4),
            prob_short=round(float(latest["prob_short"]), 4),
            prob_neutral=round(float(latest["prob_neutral"]), 4),
            close_price=round(close_price, 4),
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
            close_price=close_price,
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
