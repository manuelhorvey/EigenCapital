import logging
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import ta

from features.regime_features import generate_regime_features
from paper_trading.config_manager import get_config
from paper_trading.entry.decision import SignalType, TradeDecision
from paper_trading.governance.conviction_gate import RegimeRow
from paper_trading.inference.async_diagnostics import (
    DiagnosticsSnapshot,
    get_diagnostics_queue,
)
from paper_trading.ops import wrappers as _w
from paper_trading.ops.data_fetcher import fetch_live
from paper_trading.ops.tracer import (
    shadow_compare_signal,
    shadow_compare_sizing,
    trace_decision,
)

logger = logging.getLogger("quantforge.inference_pipeline")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ET = pytz.timezone("US/Eastern")

_MAX_INDICATOR_LOOKBACK = 253


class AssetInferencePipeline:
    def __init__(self, asset):
        self.asset = asset
        self._truncation_validated = False
        self._validated_model_id = -1

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        _t0 = time.perf_counter()
        asset = self.asset

        self._apply_async_diagnostics(asset)
        self._ensure_ready(asset)
        df = self._fetch_and_prepare_data(asset)

        _t_fetch = time.perf_counter()
        alpha_df, features_df, x = self._build_feature_set(asset, df)

        _t_features = time.perf_counter()
        self._check_archetype_nans(asset, features_df)
        self._check_psi_drift(asset, x)
        x, features_df = self._validate_and_truncate(asset, x, features_df)

        _t_infer = time.perf_counter()
        proba, _infer_idx = self._run_inference(asset, x, features_df)
        result, pos_size = self._compute_sizing_and_signal(asset, df, proba, _infer_idx, threshold)

        self._log_ensemble_breakdown(asset, alpha_df, proba, result)
        archetype = self._classify_archetype(asset, features_df)
        decision = self._build_decision(asset, result, pos_size, archetype, df)

        asset._apply_decision(decision, df)
        self._trace_and_diagnostics(asset, decision, proba, x, df, threshold)

        _t_total = time.perf_counter()
        self._log_pipeline_benchmark(asset, x, _t0, _t_fetch, _t_features, _t_infer, _t_total)

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

    # ── Focused pipeline stages ────────────────────────────────────

    def _apply_async_diagnostics(self, asset) -> None:
        get_diagnostics_queue().apply_pending(asset.name, asset)

    def _ensure_ready(self, asset) -> None:
        asset._ensure_position_synced()
        if not asset._trained:
            asset.train()

    def _fetch_and_prepare_data(self, asset):
        df = fetch_live(asset.ticker)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").normalize()
        else:
            df.index = df.index.tz_localize("UTC").normalize()
        asset.refresh_price()
        if asset.current_price is not None:
            df.loc[df.index[-1], "close"] = asset.current_price
        asset.price_data = df
        asset._refresh_liquidity(df)
        df["close"] = df["close"].ffill()
        df = df[~df.index.duplicated(keep="last")]
        return df

    def _build_feature_set(self, asset, df):
        from features.alpha_features import build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv

        hist_prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset.name, asset.ticker)
        if getattr(asset, "_truncate_inference", False):
            _trunc_rows = _MAX_INDICATOR_LOOKBACK + 50
            hist_prices = hist_prices.iloc[-_trunc_rows:]
            if not rate_diffs.empty:
                rate_diffs = rate_diffs.iloc[-_trunc_rows:]
            dxy = dxy.iloc[-_trunc_rows:]
            vix = vix.iloc[-_trunc_rows:]
            spx = spx.iloc[-_trunc_rows:]
            if not commodities.empty:
                commodities = commodities.iloc[-_trunc_rows:]

        alpha_df = build_alpha_features(hist_prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities)
        alpha_idx = alpha_df.index

        ohlcv = fetch_asset_ohlcv(asset.ticker)
        if not ohlcv.empty:
            if getattr(asset, "_truncate_inference", False):
                ohlcv = ohlcv.iloc[-_trunc_rows:]
            ohlcv = ohlcv.reindex(alpha_idx).ffill()

        archetype_df = pd.DataFrame(index=alpha_idx)
        if not ohlcv.empty:
            ema_20 = ta.trend.ema_indicator(ohlcv["close"], window=20)
            ema_50 = ta.trend.ema_indicator(ohlcv["close"], window=50)
            archetype_df["ema_spread"] = ((ema_20 - ema_50) / ema_50).reindex(alpha_idx)
            archetype_df["adx"] = ta.trend.adx(ohlcv["high"], ohlcv["low"], ohlcv["close"], window=14).reindex(
                alpha_idx
            )
            archetype_df["rsi"] = ta.momentum.rsi(ohlcv["close"], window=14).reindex(alpha_idx)
            bb = ta.volatility.BollingerBands(ohlcv["close"], window=20, window_dev=2)
            bb_mavg = bb.bollinger_mavg()
            bb_std = bb.bollinger_hband() - bb_mavg
            archetype_df["bb_zscore"] = ((ohlcv["close"] - bb_mavg) / (bb_std / 2)).reindex(alpha_idx)
        archetype_df = archetype_df.bfill()

        feature_cols = getattr(asset, "_alpha_feature_cols", None)
        if not feature_cols:
            feature_cols = [c for c in alpha_df.columns]
            asset._alpha_feature_cols = feature_cols
        available = [c for c in feature_cols if c in alpha_df.columns]
        if not available:
            raise ValueError(f"No alpha feature columns found for {asset.name}")
        x = alpha_df[available]
        features_df = pd.concat([alpha_df, archetype_df], axis=1)
        return alpha_df, features_df, x

    def _check_archetype_nans(self, asset, features_df) -> None:
        for col in ["adx", "rsi", "bb_zscore", "ema_spread"]:
            if col in features_df.columns and features_df[col].isna().any():
                n_nan = features_df[col].isna().sum()
                if n_nan > 30:
                    logger.warning(
                        "%s: archetype feature '%s' has %d NaN rows (classifier will fall back to defaults)",
                        asset.name,
                        col,
                        n_nan,
                    )

    def _check_psi_drift(self, asset, x) -> None:
        if not getattr(asset, "_psi_drift_initialized", False):
            asset._psi_drift_initialized = True
            return
        try:
            latest_df, _ = asset._importance_store.get_latest_two_snapshots(asset.name)
            if latest_df is not None and not latest_df.empty:
                top10 = latest_df[latest_df["rank"] <= 10]
                top_features = [(r["feature"], r["importance_score"]) for r in top10.to_dict("records")]
                x_current = x.tail(21)
                asset._last_psi_drift = asset._psi_monitor.compute_drift(asset.name, x_current, top_features)
        except Exception as e:
            logger.debug("%s: PSI drift skipped: %s", asset.name, e)

    def _validate_and_truncate(self, asset, x, features_df):
        _model_id = id(asset.model)
        if not self._truncation_validated or self._validated_model_id != _model_id:
            self._validate_inference_truncation(asset, x)
            self._truncation_validated = True
            self._validated_model_id = _model_id
        if getattr(asset, "_truncate_inference", False):
            return x.iloc[-1:], features_df.iloc[-1:]
        return x, features_df

    def _run_inference(self, asset, x, features_df):
        _infer_idx = x.index[-1:] if getattr(asset, "_truncate_inference", False) else x.index

        raw = asset._model_iface.predict(asset.model, x)
        if raw.shape[1] == 2:
            proba = np.column_stack([1.0 - raw[:, 1], np.zeros(raw.shape[0]), raw[:, 1]])
        elif raw.shape[1] >= 3:
            proba = raw[:, :3]
        else:
            raise ValueError(f"Model returned {raw.shape[1]} columns, expected >=2")

        ensemble = getattr(asset, "_ensemble", None)
        if ensemble is not None and getattr(asset, "_regime_model", None) is not None:
            regime_feats = getattr(asset, "regime_feature_names", None)
            if regime_feats:
                regime_available = [c for c in regime_feats if c in features_df.columns]
                if regime_available:
                    try:
                        regime_raw = asset._regime_model.predict_proba(features_df[regime_available])
                        regime_p_long = regime_raw[:, 1]
                        base_p_long = raw[:, 1]
                        three_col, _ = ensemble.combine_and_expand(base_p_long, regime_p_long)
                        proba = three_col
                        logger.debug(
                            "%s: ensemble blended (base=%.2f regime=%.2f)",
                            asset.name,
                            ensemble.base_weight,
                            ensemble.regime_weight,
                        )
                    except Exception as e:
                        logger.debug("%s: ensemble inference failed: %s", asset.name, e)

        asset._last_meta_proba = None
        if asset._meta_label_model is not None and asset._meta_label_model._trained:
            try:
                asset._last_meta_proba = asset._meta_label_model.predict_proba(x, proba)
            except Exception as e:
                logger.debug("%s: meta-label inference failed: %s", asset.name, e)

        return proba, _infer_idx

    def _compute_sizing_and_signal(self, asset, df, proba, infer_idx, threshold):
        sizing_cfg = asset._sizing_config(df["close"])
        if asset.config.get("regime_sizing"):
            regime_features_df = generate_regime_features(df)
            regime_results = asset.regime_classifier.classify(regime_features_df)
            last_row = regime_results.iloc[-1]
            asset._current_regime = last_row["regime"]
            asset._last_regime_row = RegimeRow(
                P_trend=float(last_row["P_trend"]),
                P_range=float(last_row["P_range"]),
                P_volatile=float(last_row["P_volatile"]),
                regime_label=str(last_row["regime"]),
            )
            pos_size = asset._sizing_strategy.compute(df["close"], sizing_cfg, regime=asset._current_regime)
        else:
            asset._current_regime = "neutral"
            asset._last_regime_row = None
            pos_size = asset._sizing_strategy.compute(df["close"], sizing_cfg)

        result = asset._signal_strategy.compute(proba, infer_idx, threshold, df["close"], pos_size)
        return result, pos_size

    def _log_ensemble_breakdown(self, asset, alpha_df, proba, result) -> None:
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
                "mom_normalized": round(float(mom_21 * 0.6 + mom_63 * 0.4), 4)
                if not (np.isnan(mom_21) or np.isnan(mom_63))
                else 0.0,
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

    def _classify_archetype(self, asset, features_df) -> str:
        archetype = "UNKNOWN"
        if asset._archetype_classifier is not None:
            try:
                archetype_enum = asset._archetype_classifier.classify(features_df.iloc[-1])
                archetype = archetype_enum.value
            except Exception as e:
                logger.debug("%s: archetype classification failed: %s", asset.name, e)
        return archetype

    def _build_decision(self, asset, result, pos_size, archetype, df):
        self._record_inference_proxies(result.signal_data, result.signal_type)
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
        logger.debug(
            "%s ENTRY: signal=%s close_price=%.4f current_price=%s confidence=%.1f pos_size=%.4f",
            asset.name,
            decision.signal,
            decision.close_price,
            asset.current_price,
            decision.confidence,
            pos_size,
        )
        return decision

    def _trace_and_diagnostics(self, asset, decision, proba, x, df, threshold) -> None:
        trace_decision(
            asset=asset.name,
            features={k: round(float(v), 6) for k, v in x.iloc[-1].items()},
            proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            pos_size=float(decision.position_size),
            close_price=decision.close_price,
            current_side=asset.pos_mgr.current_side(),
            halt_flags=asset.check_halt_conditions(),
        )

        _shadow_signal_df = _w.compute_signals(proba[-1:], x.index[-1:], threshold)
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
            original_size=float(decision.position_size),
        )

        _cfg = get_config()
        if _cfg.optimizations.get("async_diagnostics", True):
            _snap = DiagnosticsSnapshot(
                asset_name=asset.name,
                proba_long=float(proba[-1, 0]),
                proba_short=float(proba[-1, 1]),
                proba_neutral=float(proba[-1, 2]),
                threshold=threshold,
                signal=decision.signal,
                confidence=decision.confidence,
                shadow_stype=_shadow_stype,
                shadow_conf_pct=_shadow_conf_pct,
                feature_row={k: float(v) for k, v in x.iloc[-1].items()},
                close_prices=df["close"].ffill().iloc[-20:].tolist(),
                timestamp=str(datetime.now(tz=ET).date()),
                model=asset.model,
                features=asset.features,
            )
            get_diagnostics_queue().enqueue(_snap)
        else:
            self._run_shadow_feedback(asset, decision, proba, x, df, threshold, _shadow_stype, _shadow_conf_pct)

    def _run_shadow_feedback(self, asset, decision, proba, x, df, threshold, shadow_stype, shadow_conf_pct) -> None:
        try:
            from paper_trading.governance.drift import get_shadow_intelligence as _get_drift
            from paper_trading.governance.risk import evaluate as _risk_evaluate
            from paper_trading.ops import diagnostics as diag
            from paper_trading.ops.tracer import trace_diagnostic_report
            from paper_trading.shadow.actions import compute_shadow_actions as _compute_shadow
            from paper_trading.shadow.feedback import record_shadow_feedback as _record_feedback
            from paper_trading.shadow.learning import compile_shadow_learning as _compile_learning
            from paper_trading.shadow.memory import store_event as _shadow_store

            _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
            _sig_div = diag.analyze_signal_divergence(
                _proba_list,
                threshold,
                decision.signal,
                decision.confidence,
                shadow_stype,
                shadow_conf_pct,
            )
            _mod_div = diag.analyze_model_distribution(asset.name, _proba_list)
            _feat_drivers = diag.analyze_feature_impact(asset.model, x.iloc[[-1]], asset.features, proba[-1:])
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

    def _log_pipeline_benchmark(self, asset, x, t0, t_fetch, t_features, t_infer, t_total) -> None:
        fetch_time = t_fetch - t0
        feat_time = t_features - t_fetch
        infer_time = t_infer - t_features
        apply_time = t_total - t_infer
        logger.debug(
            "PIPELINE_BENCHMARK %s: fetch=%.3fs feat=%.3fs infer=%.3fs apply=%.3fs total=%.3fs truncate=%s rows=%d",
            asset.name,
            fetch_time,
            feat_time,
            infer_time,
            apply_time,
            t_total - t0,
            getattr(asset, "_truncate_inference", False),
            len(x),
        )

    def _validate_inference_truncation(self, asset, x: pd.DataFrame) -> None:
        if len(x) < _MAX_INDICATOR_LOOKBACK + 1:
            logger.warning(
                "%s: insufficient rows (%d) for truncation validation — disabling",
                asset.name,
                len(x),
            )
            asset._truncate_inference = False
            return
        x_warm = x.iloc[_MAX_INDICATOR_LOOKBACK:]
        try:
            full = asset._model_iface.predict(asset.model, x_warm)
            truncated = asset._model_iface.predict(asset.model, x_warm.iloc[-1:])
        except Exception as e:
            logger.warning("%s: truncation validation failed — %s", asset.name, e)
            asset._truncate_inference = False
            return
        max_diff = float(np.max(np.abs(full[-1:] - truncated)))
        if max_diff > 1e-6:
            logger.warning(
                "%s: inference truncation diff=%.2e (>=1e-6) — disabling truncation",
                asset.name,
                max_diff,
            )
            asset._truncate_inference = False
        else:
            logger.info(
                "%s: inference truncation validated (diff=%.2e, rows=%d)",
                asset.name,
                max_diff,
                len(x),
            )
            asset._truncate_inference = True

    def _record_inference_proxies(self, signal_data, signal: str) -> None:
        asset = self.asset
        asset._last_macro_dir = None
        asset._last_blend_dir = None
        asset._entry_signal_dir = 1 if signal == "BUY" else (-1 if signal == "SELL" else 0)

        macro_head = getattr(asset.model, "macro_head", None) if asset.model else None
        if macro_head is None:
            return
        try:
            macro_cols = [c for c in macro_head.features if c in signal_data.columns]
            if len(macro_cols) < 3:
                return
            macro_probs = macro_head.predict_proba(signal_data.iloc[[-1]][macro_cols])[0]
            asset._last_macro_dir = int(np.argmax(macro_probs)) - 1
            asset._last_blend_dir = int(np.argmax(signal_data.iloc[-1].values)) - 1
        except Exception:
            logger.debug("%s: macro proxy inference failed", asset.name)
