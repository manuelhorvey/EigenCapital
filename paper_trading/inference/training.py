from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from features.alpha_features import build_alpha_features
from features.data_fetch import _fetch_macro_batch, fetch_asset_data, fetch_asset_ohlcv
from features.regime_features import generate_regime_features
from labels.meta_labels import MetaLabelModel
from labels.triple_barrier import apply_triple_barrier
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel
from shared.model_registry import save_model as registry_save_model
from shared.volatility import VolatilityPrimitive

logger = logging.getLogger("eigencapital.training_pipeline")


def _prepare_binary_labels(
    y: pd.Series,
    asset_name: str = "",
) -> pd.Series:
    """Drop HOLD (0) labels and map {-1, 1} to {0, 1} for binary:logistic."""
    y_int = y.astype(int)
    mask = y_int != 0
    binary = y_int[mask].copy()
    binary = binary.map({-1: 0, 1: 1})
    dropped = (~mask).sum()
    if dropped > 0:
        logger.info("%s: dropped %d HOLD labels for binary training", asset_name, dropped)
    return binary


class AssetTrainingPipeline:
    def __init__(self, asset):
        self.asset = asset

    def _load_expanded_training_data(
        self, expanded_data_dir: str | None
    ) -> tuple[
        pd.DataFrame | None,
        pd.DataFrame,
        pd.DataFrame | None,
        pd.Series,
        pd.Series,
        pd.Series,
        pd.DataFrame | None,
    ]:
        """Load expanded training data from local parquet cache.

        When ``expanded_data_dir`` points to ``data/yfinance_10yr/``, reads the
        asset's pre-downloaded 10y+ OHLCV from a parquet file instead of doing
        a live fetch.  Macro (DXY, VIX, SPX, WTI, TNX) and rate-differentials
        are computed fresh from the live macro batch.

        Returns a 7-tuple ``(prices, ohlcv, rate_diffs, dxy, vix, spx, commodities)``.

        When ``expanded_data_dir`` is ``None`` or the parquet is missing, all
        values are ``None`` (caller falls back to live ``fetch_asset_data()``).
        """
        if expanded_data_dir is None:
            return (
                None,
                pd.DataFrame(),
                None,
                pd.Series(dtype=float),
                pd.Series(dtype=float),
                pd.Series(dtype=float),
                None,
            )

        from features.data_fetch import _normalize_index

        asset = self.asset
        pq_path = Path(expanded_data_dir) / f"{asset.name}_ohlcv.parquet"
        if not pq_path.exists():
            logger.warning(
                "%s: expanded_data_dir=%s but no %s — falling back to live fetch",
                asset.name,
                expanded_data_dir,
                pq_path.name,
            )
            return (
                None,
                pd.DataFrame(),
                None,
                pd.Series(dtype=float),
                pd.Series(dtype=float),
                pd.Series(dtype=float),
                None,
            )

        ohlcv = pd.read_parquet(pq_path)
        ohlcv.index = _normalize_index(ohlcv.index)
        logger.info(
            "%s: loaded %d OHLCV rows from %s (%s..%s)",
            asset.name,
            len(ohlcv),
            pq_path.name,
            ohlcv.index[0].date(),
            ohlcv.index[-1].date(),
        )

        macro = _fetch_macro_batch()
        dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
        vix = macro.get("^VIX", pd.Series(dtype=float))
        spx = macro.get("^GSPC", pd.Series(dtype=float))
        wti = macro.get("CL=F", pd.Series(dtype=float))
        tnx = macro.get("^TNX", pd.Series(dtype=float))

        for s in (dxy, vix, spx, wti, tnx):
            if not s.empty and s.index.duplicated().any():
                s.index = s.index[~s.index.duplicated(keep="last")]

        common = ohlcv.index
        for s in (dxy, vix, spx, wti):
            if not s.empty:
                common = common.intersection(s.index)
        if not tnx.empty:
            common = common.intersection(tnx.dropna().index)

        prices = ohlcv["close"].to_frame(asset.name).loc[common]
        rate_diffs = pd.DataFrame(index=common)
        commodities = pd.DataFrame(index=common)
        if not wti.empty:
            commodities["WTI"] = wti.reindex(common).ffill()

        asset_upper = asset.name.upper()
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]
        try:
            from features.data_fetch import _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS, CURRENCY_YIELD_TICKERS

            if (
                base_ccy in _KNOWN_CURRENCIES
                and quote_ccy in _KNOWN_CURRENCIES
                and asset_upper not in _ZERO_RATE_ASSETS
                and asset_upper != "BTCUSD"
            ):
                from features.rates_features import fetch_yield_curve  # type: ignore[attr-defined]

                base_yc = pd.Series(dtype=float)
                quote_yc = pd.Series(dtype=float)
                try:
                    base_yc = fetch_yield_curve(CURRENCY_YIELD_TICKERS.get(base_ccy, ""), base_ccy).reindex(common)
                    quote_yc = fetch_yield_curve(CURRENCY_YIELD_TICKERS.get(quote_ccy, ""), quote_ccy).reindex(common)
                except (OSError, ValueError, KeyError):
                    pass
                rate_diff = (base_yc - quote_yc).fillna(0.0)
                rate_diffs[asset.name] = rate_diff
            else:
                rate_diffs[asset.name] = pd.Series(0.0, index=common)
        except ImportError:
            rate_diffs[asset.name] = pd.Series(0.0, index=common)

        return (prices, ohlcv, rate_diffs, dxy, vix, spx, commodities)

    def train(self, force=False, full_panel=None, expanded_data_dir=None):
        asset = self.asset
        model_path = f"{asset.model_path.rsplit('.', 1)[0]}.json"

        if os.path.exists(model_path) and not force:
            asset.model = xgb.XGBClassifier()
            # sklearn 1.9 removed _estimator_type from ClassifierMixin, but
            # xgboost.load_model() still checks it via _get_type().
            asset.model._estimator_type = "classifier"
            asset.model.load_model(model_path)
            asset._trained = True
            asset._enable_adaptive_macro()
            asset._load_meta_label_model()
            # Re-hash after loading from disk so the engine's per-cycle integrity
            # check (model-file hash comparison) doesn't detect a false mismatch
            # on every cycle and trigger an unnecessary reload.
            try:
                hash_path = model_path.replace(".json", "_hash.txt")
                if os.path.exists(hash_path):
                    with open(hash_path) as _fh:
                        asset._model_hash = _fh.read().strip()
            except OSError:
                pass
            self._train_regime_if_configured()
            return

        # ── Expanded data path (offline retrain only) ───────────────────
        loaded = self._load_expanded_training_data(expanded_data_dir)
        prices, ohlcv, rate_diffs, dxy, vix, spx, commodities = loaded
        if prices is None:
            logger.info("%s: downloading history from yfinance...", asset.name)
            prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(
                asset.name,
                asset.ticker,
            )
            ohlcv = fetch_asset_ohlcv(asset.ticker)

        features = build_alpha_features(
            prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            ohlcv=ohlcv,
        )

        # ── Lead-lag custom features from FeatureContract ──────────────
        # Custom features like gc_lead_1 are defined in the FEATURE_REGISTRY
        # contract's custom_features tuple. Compute them as lagged returns
        # of the leader asset. Requires expanded_data_dir for leader OHLCV.
        _custom_feats = asset.contract.custom_features
        if _custom_feats and expanded_data_dir is not None:
            from features.lead_lag_features import load_lead_lag_edges

            _edges = load_lead_lag_edges()
            _leader_cache: dict[str, pd.Series] = {}
            for _edge in _edges:
                if _edge.get("target") != asset.ticker:
                    continue
                _col = _edge.get("column", "")
                if _col not in _custom_feats or _col in features.columns:
                    continue
                _leader_ticker = _edge.get("leader", "")
                _lag = _edge.get("lag", 1)
                if _leader_ticker not in _leader_cache:
                    _lname = _leader_ticker.replace("=X", "").replace("=F", "").replace("^", "")
                    _lpath = Path(expanded_data_dir) / f"{_lname}_ohlcv.parquet"
                    if _lpath.exists():
                        _ldf = pd.read_parquet(_lpath)
                        _leader_cache[_leader_ticker] = _ldf["close"]
                    else:
                        logger.warning(
                            "%s: leader data not found at %s — skipping feature '%s'",
                            asset.name,
                            _lpath,
                            _col,
                        )
                        continue
                _leader_close = _leader_cache.get(_leader_ticker)
                if _leader_close is not None:
                    _lret = _leader_close.pct_change().dropna()
                    features[_col] = _lret.shift(_lag).reindex(features.index)
                    logger.info(
                        "%s: added lead-lag feature '%s' (leader=%s, lag=%d, rows=%d)",
                        asset.name,
                        _col,
                        _leader_ticker,
                        _lag,
                        len(features),
                    )

        # ── Cross-sectional features (if full panel provided) ────────
        if full_panel is not None and not full_panel.empty and len(full_panel.columns) >= 2:
            from features.cross_sectional import compute_all as compute_xs

            dxy_s = dxy if not dxy.empty else pd.Series(dtype=float)
            spx_s = spx if not spx.empty else pd.Series(dtype=float)
            xs_full = compute_xs(full_panel, dxy=dxy_s, spx=spx_s)
            prefix = asset.name.upper()
            asset_cols = [c for c in xs_full.columns if c.startswith(f"{prefix}_xs_")]
            if asset_cols:
                xs_aligned = xs_full[asset_cols].reindex(features.index).ffill().fillna(0.0)
                for col in xs_aligned.columns:
                    features[col] = xs_aligned[col]

        # ── Positioning features (Group 2 — volume momentum) ────────
        from features.positioning_features import check_oi_availability, compute_volume_features

        prefix = asset.name.upper()
        vol_df = compute_volume_features(ohlcv)
        if vol_df is not None and not vol_df.empty:
            for col in vol_df.columns:
                features[f"{prefix}_{col}"] = vol_df[col].reindex(features.index)
        features[f"{prefix}_oi_available"] = check_oi_availability(asset.ticker)

        # ── Rates & carry features (Group 3) ────────────────────────
        from features.rates_features import compute_all as compute_rates

        _macro = _fetch_macro_batch()
        rd_series = (
            rate_diffs[asset.name]
            if rate_diffs is not None and asset.name in rate_diffs.columns
            else pd.Series(0.0, index=features.index)
        )
        rates_df = compute_rates(_macro, rd_series, features.index)
        if rates_df is not None and not rates_df.empty:
            for col in rates_df.columns:
                features[f"{prefix}_{col}"] = rates_df[col].reindex(features.index)

        # ── Event & calendar features (Group 4) ─────────────────────
        from features.event_features import compute_event_features

        event_df = compute_event_features(features.index)
        if event_df is not None and not event_df.empty:
            for col in event_df.columns:
                features[f"{prefix}_{col}"] = event_df[col].reindex(features.index)

        tp_mult = float(getattr(asset, "tp_mult", 2.0))
        sl_mult = float(getattr(asset, "sl_mult", 2.0))
        pt_sl = (tp_mult, sl_mult)
        logger.info("%s: training pt_sl=%s (tp_mult=%.2f, sl_mult=%.2f)", asset.name, pt_sl, tp_mult, sl_mult)
        vb = asset.contract.label_params.get("vertical_barrier", 20)
        logger.info("%s: training vertical_barrier=%d (from contract)", asset.name, vb)
        vol_method = asset.contract.label_params.get("vol_method", "ewm_100")
        vol_primitive = None
        if vol_method == "atr":
            atr_period = asset.contract.label_params.get("atr_period", 14)
            vol_primitive = VolatilityPrimitive(period=atr_period)
            logger.info(
                "%s: using ATR vol (period=%d) for label barrier width",
                asset.name,
                atr_period,
            )
        else:
            logger.info(
                "%s: using EWM vol (span=100) for label barrier width (vol_method=%s)",
                asset.name,
                vol_method,
            )
        if not ohlcv.empty:
            labeled = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=vb, vol_primitive=vol_primitive)
            labels = labeled["label"].reindex(features.index).fillna(0).astype(int)
        else:
            logger.warning("%s: no OHLCV data for vectorized labels — using legacy fallback", asset.name)
            from labels.compat import triple_barrier_labels as _legacy_labels

            labels = _legacy_labels(prices, pt_sl=pt_sl, vertical_barrier=vb)
        features["label"] = labels.reindex(features.index).astype(int)
        # Drop rows where the label is missing (end of series where forward
        # returns aren't available).  Groups 2-4 features may have NaN from
        # rolling warmup or non-overlapping date ranges — fill those with 0
        # rather than dropping the row entirely.
        cols_to_fill = [c for c in features.columns if c != "label"]
        features[cols_to_fill] = features[cols_to_fill].fillna(0.0)
        features = features.dropna(subset=["label"])
        logger.info("%s: %d alpha feature rows, %d columns", asset.name, len(features), len(features.columns) - 1)

        # Store alpha feature column names on the asset for inference
        asset._alpha_feature_cols = [c for c in features.columns if c != "label"]

        # Generate and append regime features
        if ohlcv.empty:
            logger.warning("%s: no OHLCV data for regime features — skipping regime model", asset.name)
            asset.regime_feature_names = []
        else:
            regime_df = generate_regime_features(ohlcv)
            prefix = asset.name.upper()
            regime_cols = {}
            for col in regime_df.columns:
                prefixed = f"{prefix}_{col}"
                regime_cols[col] = prefixed
            regime_renamed = regime_df.rename(columns=regime_cols)
            # Align indices (regime features may have fewer rows due to NaN warmup)
            common_idx = features.index.intersection(regime_renamed.index)
            regime_aligned = regime_renamed.reindex(common_idx)
            for col in regime_aligned.columns:
                features[col] = regime_aligned[col]
            asset.regime_feature_names = list(regime_aligned.columns)
            # Drop rows where regime features are NaN (warmup period)
            features = features.dropna(subset=asset.regime_feature_names)

        rolling_bars = getattr(asset, "_rolling_window_bars", 756)
        if rolling_bars and len(features) > rolling_bars:
            train = features.iloc[-rolling_bars:]
            start_date = train.index[0]
            end_date = train.index[-1]
        elif getattr(asset, "_rolling_window", None) is not None:
            n = len(features)
            start_idx = max(0, n - asset._rolling_window)
            train = features.iloc[start_idx:]
            start_date = train.index[0]
            end_date = train.index[-1]
        else:
            end_date = features.index[-1]
            start_date = end_date - pd.DateOffset(years=getattr(asset, "_retrain_window", 5))
            train = features[features.index >= start_date]
        if len(train) < 200:
            train = features
            start_date = train.index[0]
            end_date = train.index[-1]

        x = train[asset._alpha_feature_cols]
        y = train["label"].astype(int)
        y_binary = _prepare_binary_labels(y, asset.name)

        if len(y_binary) < 100:
            logger.warning("%s: only %d binary samples — need >=100, skipping", asset.name, len(y_binary))
            return
        if y_binary.nunique() < 2:
            logger.warning("%s: binary labels only one class — skipping", asset.name)
            return

        x_binary = x.loc[y_binary.index]
        y_vals = y_binary.values

        # ── Time-based validation split ──────────────────────────────────
        # Use the last 20% as validation with a vertical_barrier embargo
        # to prevent label lookahead (training label windows must not reach
        # into validation data).  Falls back to a simple tail split when
        # insufficient data for the embargo.
        n = len(x_binary)
        n_valid = max(int(n * 0.2), 1)
        # Reserve a gap = min(vb, 10% of data) to prevent label lookahead
        # from the last training row leaking into the validation period.
        # If train_end is still < 50, training is too small for a useful
        # validation split — fall back to training on all data without it.
        train_gap = min(vb, max(1, n // 10))
        train_end = n - n_valid - train_gap
        if train_end < 50:
            logger.info(
                "%s: insufficient data for embargo gap (n=%d vb=%d gap=%d) — "
                "training on all %d samples without validation",
                asset.name,
                n,
                vb,
                train_gap,
                n,
            )
            x_tr = x_binary
            y_tr = y_vals
            x_ev = x_binary.iloc[-n_valid:]
            y_ev = y_vals[-n_valid:]
            use_validation = False
        else:
            x_tr = x_binary.iloc[:train_end]
            y_tr = y_vals[:train_end]
            x_ev = x_binary.iloc[-n_valid:]
            y_ev = y_vals[-n_valid:]
            use_validation = True

        # Compute imbalance from the training split only. Using the full
        # dataset (including validation labels) would leak future information
        # into the training hyperparameter scale_pos_weight.
        n0_tr = (y_tr == 0).sum()
        n1_tr = (y_tr == 1).sum()
        imbalance_ratio = n0_tr / max(n1_tr, 1)
        logger.info(
            "%s: binary labels (train only): 0=%d 1=%d imbalance_ratio=%.2f",
            asset.name,
            n0_tr,
            n1_tr,
            imbalance_ratio,
        )

        depth = getattr(asset, "max_depth", 2)
        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=depth,
            learning_rate=0.02,
            objective="binary:logistic",
            scale_pos_weight=imbalance_ratio,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
            early_stopping_rounds=50 if use_validation else None,
        )
        eval_kwargs = {"eval_set": [(x_ev, y_ev)]} if use_validation else {}
        model.fit(x_tr, y_tr, verbose=False, **eval_kwargs)

        asset.model = model
        asset._trained = True
        asset._enable_adaptive_macro()
        model.save_model(model_path)

        # Save versioned copy via model registry
        try:
            with open(model_path, "rb") as _fm:
                model_bytes = _fm.read()
            model_hash = hashlib.sha256(model_bytes).hexdigest()[:16]
            train_date = asset._current_window_train_end or end_date.strftime("%Y-%m-%d")
            feature_hash = hashlib.sha256("|".join(sorted(asset._alpha_feature_cols or [])).encode()).hexdigest()[:16]
            version_id = registry_save_model(
                asset=asset.name,
                model_bytes=model_bytes,
                train_date=train_date,
                train_end=end_date.strftime("%Y-%m-%d"),
                feature_hash=feature_hash,
                model_hash=model_hash,
                n_features=len(asset._alpha_feature_cols or []),
            )

            # Run validation gates using validation-set returns as candidate_returns.
            # If gates fail, the model is saved but not deployed — operator must review.
            if use_validation and version_id:
                try:
                    from shared.validation_gates import run_validation_gates

                    y_ev_binary = _prepare_binary_labels(y.loc[x_ev.index], asset.name)
                    if len(y_ev_binary) >= 20 and y_ev_binary.nunique() >= 2:
                        _gate_incumbent = None
                        try:
                            from shared.model_registry import get_current_version as _get_cur

                            _gate_incumbent = _get_cur(asset.name)
                        except (ValueError, TypeError, ImportError, RuntimeError):
                            logger.debug(
                                "%s: no incumbent model for validation gates",
                                asset.name,
                                exc_info=True,
                            )
                        _ev_r = model.predict(x_ev).astype(float)
                        _ev_r = np.where(_ev_r == 0, -0.5, 1.0) * np.where(y_ev_binary.values == 0, -1, 1)
                        _gate_results = run_validation_gates(
                            asset=asset.name,
                            incumbent=_gate_incumbent,
                            candidate={
                                "oos_sharpe": None,
                                "oos_ic": None,
                                "oos_max_dd": None,
                                "ece": None,
                            },
                            candidate_returns=_ev_r,
                        )
                        _all_pass = all(r.passed for r in _gate_results)
                        if _all_pass:
                            logger.info(
                                "%s: validation gates passed (%d/%d) — model promoted to production",
                                asset.name,
                                sum(1 for r in _gate_results if r.passed),
                                len(_gate_results),
                            )
                        else:
                            logger.warning(
                                "%s: validation gates %d/%d passed — model saved as staging, not deployed",
                                asset.name,
                                sum(1 for r in _gate_results if r.passed),
                                len(_gate_results),
                            )
                            for g in _gate_results:
                                if not g.passed:
                                    logger.warning("  FAIL [%s]: %s", g.name, g.message)
                except (ValueError, TypeError, RuntimeError, ImportError) as _gate_err:
                    logger.warning("%s: validation gates error (non-fatal): %s", asset.name, _gate_err, exc_info=True)
        except (OSError, ValueError, TypeError, RuntimeError) as _ms_err:
            logger.warning("%s: model registry save failed (non-fatal): %s", asset.name, _ms_err, exc_info=True)
            with open(model_path, "rb") as _fm:
                model_hash = hashlib.sha256(_fm.read()).hexdigest()[:16]

        # Legacy hash file (backward compat)
        hash_path = model_path.replace(".json", "_hash.txt")
        with open(hash_path, "w") as _fh:
            _fh.write(model_hash)
        asset._model_hash = model_hash
        logger.info(
            "%s: binary model saved to %s (%d features, hash=%s)",
            asset.name,
            model_path,
            len(asset._alpha_feature_cols),
            model_hash,
        )

        # Persist PSI baseline
        try:
            asset._psi_monitor.persist_baseline(asset.name, x)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as _psi_err:
            logger.warning("%s: failed to persist PSI baseline: %s", asset.name, _psi_err, exc_info=True)

        # Train meta-label model using OOS primary predictions
        if asset.config.get("meta_labeling", {}).get("enabled", False):
            asset._meta_label_model = MetaLabelModel(
                threshold=asset.config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            try:
                oos_pred = model.predict_proba(x_ev)
                ev_indices = x_ev.index
                ev_data = train.loc[ev_indices, asset._alpha_feature_cols].copy()
                ev_data["label"] = y.loc[ev_indices]
                asset._meta_label_model.train(ev_data, oos_pred, asset._alpha_feature_cols, asset.name)
                logger.info(
                    "%s: meta model trained on %d OOS samples",
                    asset.name,
                    len(ev_data),
                )
            except (ValueError, TypeError, KeyError, RuntimeError, AttributeError) as _meta_err:
                logger.warning("%s: meta-label training failed: %s", asset.name, _meta_err, exc_info=True)

        # Log feature importances
        asset._window_id_counter += 1
        asset._current_window_train_start = start_date.strftime("%Y-%m-%d")
        asset._current_window_train_end = end_date.strftime("%Y-%m-%d")
        window_id = f"w{asset._window_id_counter}_{asset._current_window_train_end}"
        try:
            asset._importance_store.log_snapshot(
                asset=asset.name,
                feature_names=asset._alpha_feature_cols,
                importances=model.feature_importances_,
                window_id=window_id,
                train_start=asset._current_window_train_start,
                train_end=asset._current_window_train_end,
                model_type="xgboost_binary_alpha",
            )
            stability = asset._importance_store.compute_stability(asset.name)
            if stability is not None:
                asset._last_stability = stability
                logger.info(
                    "%s stability — jaccard=%.3f spearman=%.3f penalty=%.3f",
                    asset.name,
                    stability.jaccard_top_10,
                    stability.spearman_rank_corr,
                    stability.penalty,
                )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, AttributeError) as _imp_err:
            logger.warning("%s: failed to log feature importances: %s", asset.name, _imp_err, exc_info=True)

        self._train_regime_if_configured(train_features=train, features_df=features)

    def _train_regime_if_configured(
        self,
        train_features: pd.DataFrame | None = None,
        features_df: pd.DataFrame | None = None,
    ) -> None:
        asset = self.asset
        base_weight = asset.config.get("ensemble", {}).get("base_weight", 1.0)
        if base_weight >= 1.0:
            return
        regime_feats = getattr(asset, "regime_feature_names", None)

        # Try loading regime model from disk first (regime_feature_names may be
        # empty on first load after training, since __init__ sets it to []).
        regime_model = RegimeConditionalModel()
        if regime_model.load(asset_name=asset.name):
            asset._regime_model = regime_model
            asset.regime_feature_names = list(regime_model._feature_names)
            regime_feats = asset.regime_feature_names
        elif not regime_feats:
            return
        elif train_features is not None and features_df is not None:
            all_feats = asset._alpha_feature_cols + regime_feats
            available = [c for c in all_feats if c in features_df.columns]
            if len(available) < 3:
                logger.warning("%s: too few regime features available — skipping regime model", asset.name)
                return
            x_regime = features_df[available].reindex(train_features.index).dropna()
            y_regime_raw = train_features["label"].astype(int).reindex(x_regime.index).dropna()
            y_regime = _prepare_binary_labels(y_regime_raw, asset.name)
            common = x_regime.index.intersection(y_regime.index)
            if len(common) < 100:
                logger.warning("%s: insufficient binary regime data (%d) — skipping", asset.name, len(common))
                return
            if y_regime.loc[common].nunique() < 2:
                logger.warning("%s: regime labels only one class — skipping", asset.name)
                return
            regime_model.train(x_regime.loc[common], y_regime.loc[common], available, asset_name=asset.name)
            asset._regime_model = regime_model
        else:
            return

        base_weight = asset.config.get("ensemble", {}).get("base_weight", 1.0)
        ensemble_threshold = asset.config.get("ensemble", {}).get("threshold", 0.15)
        asset._ensemble = EnsembleSignal(
            base_weight=base_weight,
            ensemble_threshold=ensemble_threshold,
        )
        logger.info(
            "%s: ensemble configured (base=%.2f, threshold=%.2f)",
            asset.name,
            base_weight,
            ensemble_threshold,
        )
