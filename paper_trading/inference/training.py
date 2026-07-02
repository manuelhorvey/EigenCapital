import hashlib
import logging
import os

import pandas as pd
import xgboost as xgb

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, fetch_cot_features
from features.regime_features import generate_regime_features
from labels.meta_labels import MetaLabelModel
from labels.triple_barrier import apply_triple_barrier
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel

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

    def train(self, force=False):
        asset = self.asset
        model_path = f"{asset.model_path.rsplit('.', 1)[0]}.json"

        if os.path.exists(model_path) and not force:
            asset.model = xgb.XGBClassifier()
            asset.model.load_model(model_path)
            asset._trained = True
            asset._enable_adaptive_macro()
            asset._load_meta_label_model()
            self._train_regime_if_configured()
            return

        logger.info("%s: downloading history from yfinance...", asset.name)
        prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(
            asset.name,
            asset.ticker,
        )

        cot_data = fetch_cot_features(prices.index)

        # Fetch OHLCV early — needed for trend-exhaustion features, vectorized
        # labels, and regime features
        ohlcv = fetch_asset_ohlcv(asset.ticker)

        features = build_alpha_features(
            prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            cot_data=cot_data,
            ohlcv=ohlcv,
        )

        tp_mult = float(getattr(asset, "tp_mult", 2.0))
        sl_mult = float(getattr(asset, "sl_mult", 2.0))
        pt_sl = (tp_mult, sl_mult)
        logger.info("%s: training pt_sl=%s (tp_mult=%.2f, sl_mult=%.2f)", asset.name, pt_sl, tp_mult, sl_mult)
        vb = asset.contract.label_params.get("vertical_barrier", 20)
        logger.info("%s: training vertical_barrier=%d (from contract)", asset.name, vb)
        if not ohlcv.empty:
            labeled = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=vb)
            labels = labeled["label"].reindex(features.index).fillna(0).astype(int)
        else:
            logger.warning("%s: no OHLCV data for vectorized labels — using legacy fallback", asset.name)
            from labels.compat import triple_barrier_labels as _legacy_labels

            labels = _legacy_labels(prices, pt_sl=pt_sl, vertical_barrier=vb)
        features["label"] = labels.reindex(features.index).astype(int)
        features = features.dropna()
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
        train_end = n - n_valid - vb
        if train_end < 50:
            train_end = n - n_valid

        x_tr = x_binary.iloc[:train_end]
        y_tr = y_vals[:train_end]
        x_ev = x_binary.iloc[-n_valid:]
        y_ev = y_vals[-n_valid:]

        n0 = (y_tr == 0).sum()
        n1 = (y_tr == 1).sum()
        imbalance_ratio = n0 / max(n1, 1)
        logger.info("%s: binary labels: 0=%d 1=%d imbalance_ratio=%.2f", asset.name, n0, n1, imbalance_ratio)

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
            early_stopping_rounds=50,
        )
        model.fit(x_tr, y_tr, eval_set=[(x_ev, y_ev)], verbose=False)

        asset.model = model
        asset._trained = True
        asset._enable_adaptive_macro()
        model.save_model(model_path)
        hash_path = model_path.replace(".json", "_hash.txt")
        with open(model_path, "rb") as _fm:
            model_hash = hashlib.sha256(_fm.read()).hexdigest()[:16]
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
        except Exception as e:
            logger.warning("%s: failed to persist PSI baseline: %s", asset.name, e)

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
            except Exception as e:
                logger.warning("%s: meta-label training failed: %s", asset.name, e)

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
        except Exception as e:
            logger.warning("%s: failed to log feature importances: %s", asset.name, e)

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
