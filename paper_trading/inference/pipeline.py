from __future__ import annotations

import hashlib
import json
import logging
import time

import numpy as np
import pandas as pd

from eigencapital.domain.time import utc_now
from features.regime_features import generate_regime_features
from paper_trading.config_manager import get_config
from paper_trading.governance.conviction_gate import RegimeRow
from paper_trading.inference.async_diagnostics import get_diagnostics_queue
from paper_trading.inference.decision_builder import build_decision
from paper_trading.inference.feature_builder import FeatureBuilder
from paper_trading.inference.trace_diagnostics import trace_and_diagnostics
from paper_trading.ops.data_fetcher import fetch_live
from shared.calibration.registry import CalibrationRegistry

logger = logging.getLogger("eigencapital.inference_pipeline")

_MAX_INDICATOR_LOOKBACK = 253


class AssetInferencePipeline:
    def __init__(self, asset):
        self.asset = asset
        self._truncation_validated = False
        self._validated_model_id = -1
        self._truncate_inference = False
        self._feature_builder = FeatureBuilder()

    def generate_signal(self, threshold=0.45, shared_macro: dict[str, pd.Series] | None = None):
        return self._generate_and_apply(threshold, shared_macro=shared_macro)

    def _generate_and_apply(self, threshold=0.45, shared_macro: dict[str, pd.Series] | None = None):
        _t0 = time.perf_counter()
        asset = self.asset

        self._apply_async_diagnostics(asset)
        self._ensure_ready(asset)
        asset.refresh_spread()
        df = self._fetch_and_prepare_data(asset)

        # Bar-jump suppression: data-source switch contaminates feature vectors.
        # _detect_bar_jump sets _suppress_until; honour it here by returning a
        # safe neutral skeleton without inferring on potentially stale data.
        if time.time() < getattr(asset, "_suppress_until", 0.0):
            logger.warning(
                "%s: bar-jump suppression active — skipping inference this cycle",
                asset.name,
            )
            return {
                "asset": asset.name,
                "signal": "HOLD",
                "final_signal": "suppressed",
                "confidence": 0.0,
                "side": "none",
                "prob_long": 0.0,
                "prob_short": 0.0,
                "prob_neutral": 1.0,
                "position_size": 0.0,
            }

        _t_fetch = time.perf_counter()
        self._truncate_inference = True
        alpha_df, features_df, x = self._feature_builder.build(asset, df, shared_macro=shared_macro)

        _t_features = time.perf_counter()
        self._check_archetype_nans(asset, features_df)
        self._check_psi_drift(asset, x)
        x, features_df = self._validate_and_truncate(asset, x, features_df)

        # ── Feature snapshot (causal boundary P0.1) ─────────────────────
        feature_vector = {k: float(v) for k, v in x.iloc[-1].items()}
        feature_hash = hashlib.md5((asset.name + json.dumps(feature_vector, sort_keys=True)).encode()).hexdigest()[:12]  # nosec
        asset._last_feature_vector = feature_vector
        asset._last_feature_hash = feature_hash
        asset._last_feature_schema = sorted(feature_vector.keys())

        _t_infer = time.perf_counter()
        proba, _infer_idx = self._run_inference(asset, x, features_df, feature_hash)

        # ── Calibrate probabilities ──────────────────────────────────
        asset._calibration_applied = self._apply_calibration(asset, proba)

        # Guard: if calibration is enabled but failed, handle per-asset
        _cal_cfg = get_config().defaults.get("calibration", {})
        if _cal_cfg.get("enabled", False) and not asset._calibration_applied:
            cal_registry = getattr(asset, "_calibration_registry", None)
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

        # ── Risk-off gate: suppress BUY signals during risk-off regimes ──
        risk_off_enabled = asset.config.get("risk_off_enabled", False)
        if (
            risk_off_enabled
            and getattr(asset, "_risk_off", False)
            and hasattr(result, "signal_type")
            and result.signal_type == "BUY"
        ):
            logger.info(
                "%s: risk-off gate — suppressing BUY signal (risk_off=True)",
                asset.name,
            )
            result.signal_type = "HOLD"

        self._log_ensemble_breakdown(asset, alpha_df, proba, result)
        archetype = self._classify_archetype(asset, features_df)
        decision = build_decision(asset, result, pos_size, archetype, df, feature_hash=feature_hash)

        asset._apply_decision(decision, df)
        trace_and_diagnostics(asset, decision, proba, x, df, threshold, feature_vector, feature_hash)

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
            last_refresh = getattr(asset, "_last_price_refresh", None)
            if last_refresh is not None:
                staleness = (utc_now() - last_refresh).total_seconds()
                if staleness < 300:
                    df.loc[df.index[-1], "close"] = asset.current_price
                else:
                    logger.debug(
                        "Stale price for %s (%.0fs old) — skipping live override",
                        asset.name,
                        staleness,
                    )
            else:
                df.loc[df.index[-1], "close"] = asset.current_price
        asset.price_data = df
        asset._refresh_liquidity(df)
        df["close"] = df["close"].ffill()
        df = df[~df.index.duplicated(keep="last")]
        return df

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
        if len(x) < 100:
            return
        try:
            latest_df, _ = asset._importance_store.get_latest_two_snapshots(asset.name)
            if latest_df is not None and not latest_df.empty:
                top10 = latest_df[latest_df["rank"] <= 10]
                top_features = [(r["feature"], r["importance_score"]) for r in top10.to_dict("records")]
                x_current = x.iloc[_MAX_INDICATOR_LOOKBACK:]
                if len(x_current) < 100:
                    return
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
            except (OSError, RuntimeError, KeyError):
                logger.warning("WAL write failed for inference_output on %s", asset.name, exc_info=True)

        return proba, _infer_idx

    def _apply_calibration(self, asset, proba: np.ndarray) -> bool:
        """Apply the registry calibrator to ``proba[:, 2]``.

        C-03 fix (2026-07-06): the prior implementation overwrote
        ``proba[:, 0]`` with ``1 - cal_p_long`` unconditionally, which
        killed the model's softmax SELL probability on a 3-class XGBoost
        output and caused ``confidence = max(prob_long, prob_short)`` to
        saturate near 1.0 regardless of direction. The corrected path
        replaces only ``proba[:, 2]`` with the calibrated BUY probability
        and re-normalizes so the simplex is preserved.

        Returns ``"applied"``, ``"no_calibrator"``, ``"disabled"``, or
        ``"failed"`` so the caller can record the appropriate state on
        ``asset._calibration_applied`` and emit any diagnostic logging.
        """
        cal_registry: CalibrationRegistry | None = getattr(asset, "_calibration_registry", None)
        if cal_registry is None:
            return False
        _cal_cfg = get_config().defaults.get("calibration", {})
        if not _cal_cfg.get("enabled", False):
            return False
        if asset.name not in cal_registry._calibrators:
            return False
        try:
            raw_p_long = proba[:, 2].copy()
            cal_p_long = cal_registry.calibrate(asset.name, raw_p_long)
            proba[:, 2] = cal_p_long

            # ── D-01 fix: store direction-conditional calibrated confidence ──
            # The DirectionalCalibrator produces calibrated_p_long for both
            # directions. However, the SELL calibrator uses inverse perspective:
            #   - BUY:  calibrated_p_long = P(TP hit | BUY)  = P(win | BUY)
            #   - SELL: calibrated_p_long = P(TP hit | SELL) = 1 - P(win | SELL)
            # So for SELL predictions, the correct confidence is
            # ``1 - calibrated_p_long``, not ``calibrated_p_long``.
            #
            # Fixed 2026-07-12: use CALIBRATED direction (cal_p_long > 0.5) to
            # determine BUY vs SELL, not raw direction. When raw < 0.5 but
            # calibration flips the prediction to BUY (cal_p_long > 0.5),
            # the confidence should be cal_p_long, not 1 - cal_p_long.
            asset._calibrated_confidence = (
                float(cal_p_long[-1])  # BUY:  P(win|BUY)
                if cal_p_long[-1] > 0.5
                else float(1.0 - cal_p_long[-1])  # SELL: P(win|SELL)
            )

            _row_sum = proba.sum(axis=1, keepdims=True)
            np.divide(proba, _row_sum, out=proba, where=_row_sum > 0)
            return True
        except (ValueError, TypeError, IndexError) as e:
            logger.error("%s: calibration inference failed: %s", asset.name, e)
            self._calibration_failure = e
            return False

    def _compute_sizing_and_signal(self, asset, df, proba, infer_idx, threshold):
        sizing_cfg = asset._sizing_config(df["close"])
        if asset.config.get("regime_sizing"):
            from features.data_fetch import _cycle_id

            # Use the feature builder's regime cache to avoid redundant computation
            fb = self._feature_builder
            if fb._regime_cache_cycle == _cycle_id and fb._regime_features_cache is not None:
                regime_features_df = fb._regime_features_cache
            else:
                regime_features_df = generate_regime_features(df)
                fb._regime_features_cache = regime_features_df
                fb._regime_cache_cycle = _cycle_id
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
        if max_diff > 1e-4:
            logger.warning(
                "%s: inference truncation diff=%.2e (>=1e-4) — disabling truncation",
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

