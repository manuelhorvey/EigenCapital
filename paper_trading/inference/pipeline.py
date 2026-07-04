import hashlib
import json
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
from shared.calibration.registry import CalibrationRegistry

logger = logging.getLogger("eigencapital.inference_pipeline")

# ── Eagerly hoist shadow/diagnostics imports (issue #3 pattern) ──────
# ``_run_shadow_feedback`` previously imported these inside the function
# body after inference state had already been written.  Hoist to module
# level so import errors surface at process start rather than mid-cycle.
try:
    from paper_trading.governance.drift import get_shadow_intelligence as _get_drift
except ImportError as _exc:
    _get_drift = None  # type: ignore[assignment]
    logger.warning("shadow_intelligence import unavailable — %s", _exc)

try:
    from paper_trading.governance.risk import evaluate as _risk_evaluate
except ImportError as _exc:
    _risk_evaluate = None  # type: ignore[assignment]
    logger.warning("risk.evaluate import unavailable — %s", _exc)

try:
    from paper_trading.ops import diagnostics as _diag
except ImportError as _exc:
    _diag = None  # type: ignore[assignment]
    logger.warning("ops.diagnostics import unavailable — %s", _exc)

try:
    from paper_trading.ops.tracer import trace_diagnostic_report as _trace_diag
except ImportError as _exc:
    _trace_diag = None  # type: ignore[assignment]
    logger.warning("tracer.trace_diagnostic_report import unavailable — %s", _exc)

try:
    from paper_trading.shadow.actions import compute_shadow_actions as _compute_shadow
except ImportError as _exc:
    _compute_shadow = None  # type: ignore[assignment]
    logger.warning("shadow.actions import unavailable — %s", _exc)

try:
    from paper_trading.shadow.feedback import record_shadow_feedback as _record_feedback
except ImportError as _exc:
    _record_feedback = None  # type: ignore[assignment]
    logger.warning("shadow.feedback import unavailable — %s", _exc)

try:
    from paper_trading.shadow.learning import compile_shadow_learning as _compile_learning
except ImportError as _exc:
    _compile_learning = None  # type: ignore[assignment]
    logger.warning("shadow.learning import unavailable — %s", _exc)

try:
    from paper_trading.shadow.memory import store_event as _shadow_store
except ImportError as _exc:
    _shadow_store = None  # type: ignore[assignment]
    logger.warning("shadow.memory import unavailable — %s", _exc)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ET = pytz.timezone("US/Eastern")

_MAX_INDICATOR_LOOKBACK = 253


class AssetInferencePipeline:
    def __init__(self, asset):
        self.asset = asset
        self._truncation_validated = False
        self._validated_model_id = -1
        self._truncate_inference = False
        self._regime_features_cache: pd.DataFrame | None = None
        self._regime_cache_cycle: int = -1

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        _t0 = time.perf_counter()
        asset = self.asset

        self._apply_async_diagnostics(asset)
        self._ensure_ready(asset)
        asset.refresh_spread()
        df = self._fetch_and_prepare_data(asset)

        _t_fetch = time.perf_counter()
        self._truncate_inference = True
        alpha_df, features_df, x = self._build_feature_set(asset, df)

        _t_features = time.perf_counter()
        self._check_archetype_nans(asset, features_df)
        self._check_psi_drift(asset, x)
        x, features_df = self._validate_and_truncate(asset, x, features_df)

        # ── Feature snapshot (causal boundary P0.1) ─────────────────────
        feature_vector = {k: float(v) for k, v in x.iloc[-1].items()}
        feature_hash = hashlib.md5((asset.name + json.dumps(feature_vector, sort_keys=True)).encode()).hexdigest()[:12]
        asset._last_feature_vector = feature_vector
        asset._last_feature_hash = feature_hash
        asset._last_feature_schema = sorted(feature_vector.keys())

        _t_infer = time.perf_counter()
        proba, _infer_idx = self._run_inference(asset, x, features_df, feature_hash)

        # ── Calibrate probabilities ──────────────────────────────────
        cal_registry: CalibrationRegistry | None = getattr(asset, "_calibration_registry", None)
        if cal_registry is not None:
            _cal_cfg = get_config().defaults.get("calibration", {})
            if _cal_cfg.get("enabled", False):
                try:
                    raw_p_long = proba[:, 2].copy()
                    cal_p_long = cal_registry.calibrate(asset.name, raw_p_long)
                    proba[:, 2] = cal_p_long
                    proba[:, 0] = 1.0 - cal_p_long
                    asset._calibration_applied = True
                except (ValueError, TypeError, IndexError) as e:
                    logger.error("%s: calibration inference failed: %s", asset.name, e)
                    asset._calibration_applied = False
            else:
                asset._calibration_applied = False
        else:
            asset._calibration_applied = False

        # Guard: if calibration is enabled but failed, handle per-asset:
        #   - No calibrator trained for this asset → use raw XGBoost probabilities with warning
        #   - Calibrator exists but inference failed → force neutral with error
        _cal_cfg = get_config().defaults.get("calibration", {})
        if _cal_cfg.get("enabled", False) and not asset._calibration_applied:
            if cal_registry is None or asset.name not in cal_registry._calibrators:
                logger.warning(
                    "%s: calibration enabled but no calibrator found — using raw XGBoost probabilities",
                    asset.name,
                )
            else:
                logger.error(
                    "%s: calibration inference failed — forcing neutral",
                    asset.name,
                )
                proba[:, :] = [0.0, 1.0, 0.0]

        result, pos_size = self._compute_sizing_and_signal(asset, df, proba, _infer_idx, threshold)

        self._log_ensemble_breakdown(asset, alpha_df, proba, result)
        archetype = self._classify_archetype(asset, features_df)
        decision = self._build_decision(asset, result, pos_size, archetype, df, feature_hash=feature_hash)

        asset._apply_decision(decision, df)
        self._trace_and_diagnostics(asset, decision, proba, x, df, threshold, feature_vector, feature_hash)

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
        return asset._decision_to_dict(decision, final_signal=getattr(asset, "_last_final_signal", None))

    # ── Focused pipeline stages ────────────────────────────────────

    def _apply_async_diagnostics(self, asset) -> None:
        get_diagnostics_queue().apply_pending(asset.name, asset)

    def _ensure_ready(self, asset) -> None:
        asset._ensure_position_synced()
        if not asset._trained:
            asset.train()

    def _detect_bar_jump(self, asset, bars: int) -> None:
        """Detect significant bar-count changes and set suppression timer.

        A bar jump indicates a data-source switch (yfinance↔MT5) that
        contaminates feature vectors.  Suppress trading decisions for
        60 minutes after detection.
        """
        threshold = 100
        suppress_secs = 3600

        last = getattr(asset, "_last_bar_count", None)
        if last is not None and abs(bars - last) > threshold:
            asset._suppress_until = time.time() + suppress_secs
            logger.warning(
                "%s: bar jump detected %d→%d (Δ=%d), suppressing decisions for %ds",
                asset.name,
                last,
                bars,
                bars - last,
                suppress_secs,
            )
        asset._last_bar_count = bars

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
        from features.alpha_features import _compute_shared_features, build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, fetch_cot_features

        hist_prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset.name, asset.ticker)
        self._detect_bar_jump(asset, len(hist_prices))
        cot_data = fetch_cot_features(hist_prices.index)
        if self._truncate_inference:
            _trunc_rows = _MAX_INDICATOR_LOOKBACK + 50
            hist_prices = hist_prices.iloc[-_trunc_rows:]
            if not rate_diffs.empty:
                rate_diffs = rate_diffs.iloc[-_trunc_rows:]
            dxy = dxy.iloc[-_trunc_rows:]
            vix = vix.iloc[-_trunc_rows:]
            spx = spx.iloc[-_trunc_rows:]
            if not commodities.empty:
                commodities = commodities.iloc[-_trunc_rows:]
            if not cot_data.empty:
                cot_data = cot_data.iloc[-_trunc_rows:]

        # Cross-asset features (DXY, VIX, SPX, commodities) computed once per
        # asset call and shared — avoids recomputing for every row in the loop.
        # COT features are handled separately by build_alpha_features (has its own
        # shift(3) lag logic), so cot_data is intentionally omitted here.
        shared_features = _compute_shared_features(
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            index=hist_prices.index,
        )

        # Fetch OHLCV for trend-exhaustion features (Tier 1+2)
        ohlcv = fetch_asset_ohlcv(asset.ticker)

        alpha_df = build_alpha_features(
            hist_prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            cot_data=cot_data,
            shared_features=shared_features,
            ohlcv=ohlcv,
        )
        alpha_idx = alpha_df.index

        if not ohlcv.empty:
            if self._truncate_inference:
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

        # Generate regime features from OHLCV, prefixed per-asset (matches training).
        # Cache per cycle to avoid recomputation when regime sizing is enabled.
        from features.data_fetch import _cycle_id

        regime_inference_df = pd.DataFrame(index=alpha_idx)
        if not ohlcv.empty:
            if self._regime_cache_cycle != _cycle_id:
                raw_regime = generate_regime_features(ohlcv)
                self._regime_features_cache = raw_regime
                self._regime_cache_cycle = _cycle_id
            else:
                raw_regime = self._regime_features_cache
            prefix = asset.name.upper()
            renaming = {col: f"{prefix}_{col}" for col in raw_regime.columns}
            prefixed = raw_regime.rename(columns=renaming)
            common_idx = alpha_idx.intersection(prefixed.index)
            regime_inference_df = prefixed.reindex(common_idx)

        feature_cols = getattr(asset, "_alpha_feature_cols", None)
        if not feature_cols:
            feature_cols = [c for c in alpha_df.columns]
            asset._alpha_feature_cols = feature_cols
        available = [c for c in feature_cols if c in alpha_df.columns]
        if not available:
            raise ValueError(f"No alpha feature columns found for {asset.name}")
        x = alpha_df[available]
        features_df = pd.concat([alpha_df, archetype_df, regime_inference_df], axis=1)

        self._detect_risk_off(asset, features_df)
        return alpha_df, features_df, x

    def _detect_risk_off(self, asset, features_df) -> None:
        if asset.name not in ("AUDUSD",):
            asset._risk_off = False
            return
        try:
            vix_mom = features_df["vix_mom_5d"].iloc[-1]
            spx_mom = features_df["spx_mom_5d"].iloc[-1]
            asset._risk_off = vix_mom > 0.0 and spx_mom < 0.0
        except (KeyError, IndexError):
            asset._risk_off = False

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
                x_current = x.iloc[_MAX_INDICATOR_LOOKBACK:]
                if len(x_current) < 21:
                    x_current = x.tail(21)
                asset._last_psi_drift = asset._psi_monitor.compute_drift(asset.name, x_current, top_features)
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("%s: PSI drift skipped: %s", asset.name, e)

    def _validate_and_truncate(self, asset, x, features_df):
        _model_id = id(asset.model)
        if not self._truncation_validated or self._validated_model_id != _model_id:
            self._validate_inference_truncation(asset, x)
            self._truncation_validated = True
            self._validated_model_id = _model_id
        if self._truncate_inference:
            return x.iloc[-1:], features_df.iloc[-1:]
        return x, features_df

    def _run_inference(self, asset, x, features_df, feature_hash=""):
        _infer_idx = x.index[-1:] if self._truncate_inference else x.index

        raw = asset._model_iface.predict(asset.model, x)
        if raw.shape[1] == 2:
            proba = np.column_stack([1.0 - raw[:, 1], np.zeros(raw.shape[0]), raw[:, 1]])
        elif raw.shape[1] >= 3:
            proba = raw[:, :3]
        else:
            raise ValueError(f"Model returned {raw.shape[1]} columns, expected >=2")

        ensemble = getattr(asset, "_ensemble", None)
        if ensemble is not None and getattr(asset, "_regime_model", None) is not None:
            rm_feats = asset._regime_model._feature_names if asset._regime_model._feature_names else None
            regime_feats = rm_feats if rm_feats else getattr(asset, "regime_feature_names", None)
            if regime_feats:
                regime_available = [c for c in regime_feats if c in features_df.columns]
                if not regime_available:
                    logger.warning(
                        "%s: regime features not found in features_df (%d requested, 0 available) — skipping blend",
                        asset.name,
                        len(regime_feats),
                    )
                if regime_available:
                    try:
                        regime_raw = asset._regime_model.predict_proba(features_df[regime_available])
                        regime_p_long = regime_raw[:, 1]
                        base_p_long = raw[:, 1]
                        three_col, _ = ensemble.combine_and_expand(base_p_long, regime_p_long)
                        proba = three_col
                        # Store regime raw output for observability
                        try:
                            asset._last_regime_raw_probas = (float(regime_raw[0, 0]), float(regime_raw[0, 1]))
                            asset._last_regime_long_prob = float(regime_p_long[0])
                            asset._last_regime_features = {
                                str(k): float(v) for k, v in features_df[regime_available].iloc[-1].items()
                            }
                        except (IndexError, TypeError, ValueError) as e:
                            logger.warning("%s: regime feature storage failed: %s", asset.name, e)
                        logger.debug(
                            "%s: ensemble blended (base=%.2f regime=%.2f)",
                            asset.name,
                            ensemble.base_weight,
                            ensemble.regime_weight,
                        )
                    except (ValueError, TypeError) as e:
                        logger.debug("%s: ensemble inference failed: %s", asset.name, e)
                        asset._last_regime_raw_probas = None
                        asset._last_regime_long_prob = None
                        asset._last_regime_features = None
        else:
            asset._last_regime_raw_probas = None
            asset._last_regime_long_prob = None
            asset._last_regime_features = None

        asset._last_meta_proba = None
        if asset._meta_label_model is not None and asset._meta_label_model._trained:
            try:
                asset._last_meta_proba = asset._meta_label_model.predict_proba(x, proba)
            except (ValueError, TypeError) as e:
                logger.debug("%s: meta-label inference failed: %s", asset.name, e)

        # ── Inference output WAL event (causal boundary P0.3, pre-gate) ──
        wal = getattr(asset, "_wal_writer", None)
        if wal is not None:
            try:
                wal.write(
                    "inference_output",
                    {
                        "asset": asset.name,
                        "prob_long": round(float(proba[-1, 2]), 6),
                        "prob_short": round(float(proba[-1, 0]), 6),
                        "prob_neutral": round(float(proba[-1, 1]), 6),
                        "model_hash": getattr(asset, "_model_hash", "unknown"),
                        "feature_hash": feature_hash,
                    },
                )
            except Exception:
                logger.warning("WAL write failed for inference_output on %s", asset.name, exc_info=True)

        return proba, _infer_idx

    def _compute_sizing_and_signal(self, asset, df, proba, infer_idx, threshold):
        sizing_cfg = asset._sizing_config(df["close"])
        if asset.config.get("regime_sizing"):
            from features.data_fetch import _cycle_id

            if self._regime_cache_cycle == _cycle_id and self._regime_features_cache is not None:
                regime_features_df = self._regime_features_cache
            else:
                regime_features_df = generate_regime_features(df)
                self._regime_features_cache = regime_features_df
                self._regime_cache_cycle = _cycle_id
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
            prefix = asset.name.upper()
            carry_val = latest_row.get(f"{prefix}_carry_vol_adj", np.nan)
            mom_21 = latest_row.get(f"{prefix}_mom_21d", np.nan)
            mom_63 = latest_row.get(f"{prefix}_mom_63d", np.nan)
            zscore_val = latest_row.get(f"{prefix}_zscore_20", np.nan)
            dow_val = latest_row.get(f"{prefix}_dow_signal", np.nan)
            vol_ratio = latest_row.get(f"{prefix}_vol_ratio", np.nan)
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
                "regime_long_prob": round(float(asset._last_regime_long_prob), 4)
                if asset._last_regime_long_prob is not None
                else None,
                "regime_short_prob": round(float(asset._last_regime_raw_probas[0]), 4)
                if asset._last_regime_raw_probas is not None
                else None,
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
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("%s: ensemble breakdown logging failed: %s", asset.name, e)

    def _classify_archetype(self, asset, features_df) -> str:
        archetype = "UNKNOWN"
        if asset._archetype_classifier is not None:
            try:
                archetype_enum = asset._archetype_classifier.classify(features_df.iloc[-1])
                archetype = archetype_enum.value
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("%s: archetype classification failed: %s", asset.name, e)
        return archetype

    def _build_decision(self, asset, result, pos_size, archetype, df, feature_hash=""):
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
            feature_hash=feature_hash,
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

    def _trace_and_diagnostics(
        self,
        asset,
        decision,
        proba,
        x,
        df,
        threshold,
        feature_vector=None,
        feature_hash="",
    ) -> None:
        # ── WAL: features_snapshot (causal boundary P0.1) ─────────────────
        wal = getattr(asset, "_wal_writer", None)
        if wal is not None and feature_vector is not None:
            try:
                wal.write(
                    "features_snapshot",
                    {
                        "asset": asset.name,
                        "features": feature_vector,
                        "feature_hash": feature_hash,
                        "feature_schema": getattr(asset, "_last_feature_schema", sorted(feature_vector.keys())),
                        "model_hash": getattr(asset, "_model_hash", "unknown"),
                    },
                )
            except Exception:
                logger.warning("WAL write failed for features_snapshot on %s", asset.name, exc_info=True)

        # ── Trace.jsonl decision entry (derives from same feature_vector) ──
        _regime_label = (
            asset._last_regime_row.regime_label if getattr(asset, "_last_regime_row", None) is not None else None
        )
        trace_decision(
            asset=asset.name,
            features=(
                feature_vector if feature_vector is not None else {k: round(float(v), 6) for k, v in x.iloc[-1].items()}
            ),
            proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            pos_size=float(decision.position_size),
            close_price=decision.close_price,
            current_side=asset.pos_mgr.current_side(),
            halt_flags=asset.check_halt_conditions(),
            current_price=asset.current_price,
            regime_long_prob=asset._last_regime_long_prob,
            regime_short_prob=(
                round(float(asset._last_regime_raw_probas[0]), 6) if asset._last_regime_raw_probas is not None else None
            ),
            regime_label=_regime_label,
            regime_features=asset._last_regime_features,
            feature_hash=feature_hash,
            model_hash=getattr(asset, "_model_hash", "unknown"),
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
                proba_long=float(proba[-1, 2]),
                proba_short=float(proba[-1, 0]),
                proba_neutral=float(proba[-1, 1]),
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
        # Guard: all shadow imports must be available
        if any(
            dep is None
            for dep in (
                _get_drift,
                _risk_evaluate,
                _diag,
                _trace_diag,
                _compute_shadow,
                _record_feedback,
                _compile_learning,
                _shadow_store,
            )
        ):
            logger.debug("%s: shadow feedback skipped — one or more modules unavailable at process start", asset.name)
            return

        try:
            _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
            _sig_div = _diag.analyze_signal_divergence(
                _proba_list,
                threshold,
                decision.signal,
                decision.confidence,
                shadow_stype,
                shadow_conf_pct,
            )
            _mod_div = _diag.analyze_model_distribution(asset.name, _proba_list)
            _feat_drivers = _diag.analyze_feature_impact(asset.model, x.iloc[[-1]], asset.features, proba[-1:])
            _regime = _diag.analyze_regime_context(df["close"])
            _report = _diag.build_shadow_report(
                asset=asset.name,
                timestamp=str(datetime.now(tz=ET).date()),
                signal_match=_sig_div["match"],
                signal_divergence=_sig_div,
                model_divergence=_mod_div,
                feature_drivers=_feat_drivers,
                regime_context=_regime,
            )
            _trace_diag(_report)
            if _shadow_store is not None:
                _shadow_store(asset.name, _report)
            asset._risk_signal = _risk_evaluate(asset.name)
            asset._shadow_drift_intel = _get_drift(asset.name)
            asset._shadow_action = _compute_shadow(
                asset=asset.name,
                state=None,
                drift_report=asset._shadow_drift_intel,
                risk_signal=asset._risk_signal,
            )
            if _record_feedback is not None:
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
        except (ValueError, TypeError, KeyError):
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
            self._truncate_inference,
            len(x),
        )

    def _validate_inference_truncation(self, asset, x: pd.DataFrame) -> None:
        if len(x) < _MAX_INDICATOR_LOOKBACK + 1:
            logger.warning(
                "%s: insufficient rows (%d) for truncation validation — disabling",
                asset.name,
                len(x),
            )
            self._truncate_inference = False
            return
        x_warm = x.iloc[_MAX_INDICATOR_LOOKBACK:]
        try:
            full = asset._model_iface.predict(asset.model, x_warm)
            truncated = asset._model_iface.predict(asset.model, x_warm.iloc[-1:])
        except (ValueError, TypeError) as e:
            logger.warning("%s: truncation validation failed — %s", asset.name, e)
            self._truncate_inference = False
            return
        max_diff = float(np.max(np.abs(full[-1:] - truncated)))
        if max_diff > 1e-6:
            logger.warning(
                "%s: inference truncation diff=%.2e (>=1e-6) — disabling truncation",
                asset.name,
                max_diff,
            )
            self._truncate_inference = False
        else:
            logger.info(
                "%s: inference truncation validated (diff=%.2e, rows=%d)",
                asset.name,
                max_diff,
                len(x),
            )
            self._truncate_inference = True

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
        except (ValueError, TypeError, IndexError):
            logger.debug("%s: macro proxy inference failed", asset.name)
