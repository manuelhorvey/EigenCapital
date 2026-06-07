import logging
import os

import pandas as pd
import xgboost as xgb

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data
from features.labels import triple_barrier_labels
from labels.meta_labels import MetaLabelModel
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel

logger = logging.getLogger("quantforge.training_pipeline")


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

        features = build_alpha_features(
            prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
        )

        tp_mult = float(getattr(asset, "tp_mult", 2.0))
        sl_mult = float(getattr(asset, "sl_mult", 2.0))
        pt_sl = (tp_mult, sl_mult)
        logger.info("%s: training pt_sl=%s (tp_mult=%.2f, sl_mult=%.2f)", asset.name, pt_sl, tp_mult, sl_mult)
        labels = triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=10)
        features["label"] = labels.reindex(features.index).astype(int)
        features = features.dropna()
        logger.info("%s: %d alpha feature rows, %d columns", asset.name, len(features), len(features.columns) - 1)

        # Store alpha feature column names on the asset for inference
        asset._alpha_feature_cols = [c for c in features.columns if c != "label"]

        end_date = features.index[-1]
        start_date = end_date - pd.DateOffset(years=getattr(asset, "_retrain_window", 5))
        train = features[features.index >= start_date]
        if len(train) < 200:
            train = features

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

        from sklearn.model_selection import train_test_split

        min_class = y_binary.value_counts().min()
        strat = y_binary if min_class >= 2 else None
        x_tr, x_ev, y_tr, y_ev = train_test_split(
            x_binary,
            y_vals,
            test_size=0.2,
            random_state=42,
            stratify=strat,
        )

        depth = getattr(asset, "max_depth", 2)
        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=depth,
            learning_rate=0.02,
            objective="binary:logistic",
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(x_tr, y_tr, eval_set=[(x_ev, y_ev)], verbose=False)

        asset.model = model
        asset._trained = True
        asset._enable_adaptive_macro()
        model.save_model(model_path)
        logger.info(
            "%s: binary model saved to %s (%d features)", asset.name, model_path, len(asset._alpha_feature_cols)
        )

        # Persist PSI baseline
        try:
            asset._psi_monitor.persist_baseline(asset.name, x)
        except Exception as e:
            logger.warning("%s: failed to persist PSI baseline: %s", asset.name, e)

        # Train meta-label model
        if asset.config.get("meta_labeling", {}).get("enabled", False):
            asset._meta_label_model = MetaLabelModel(
                threshold=asset.config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            try:
                primary_pred = model.predict_proba(x_binary)
                full_train = train.copy()
                full_train["label"] = y
                asset._meta_label_model.train(full_train, primary_pred, asset._alpha_feature_cols, asset.name)
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
        regime_feats = getattr(asset, "regime_feature_names", None)
        if not regime_feats:
            return

        regime_model = RegimeConditionalModel()
        if regime_model.load():
            asset._regime_model = regime_model
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
            regime_model.train(x_regime.loc[common], y_regime.loc[common], available)
            asset._regime_model = regime_model
        else:
            return

        base_weight = asset.config.get("ensemble", {}).get("base_weight", 0.6)
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
