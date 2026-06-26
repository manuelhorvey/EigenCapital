"""Meta-label model: secondary binary classifier that predicts whether
a trade will hit TP before SL (i.e. label == 1 vs label == -1).

This model is trained on the same features as the primary model PLUS
the primary model's output probabilities.  During live inference it is
used as a trade filter: only enter when meta-label predicts TP > SL.

Meta-label = 1  → trade will hit TP first (or timeout neutral)
Meta-label = 0  → trade will hit SL first
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import pickle

import numpy as np
import pandas as pd
import xgboost as xgb

logger = logging.getLogger("quantforge.meta_labels")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_MODEL_DIR = os.path.join(BASE, "models", "meta")
os.makedirs(META_MODEL_DIR, exist_ok=True)


class MetaLabelModel:
    """Binary classifier for P(TP hit before SL).

    Parameters
    ----------
    n_estimators : int
    max_depth : int
    learning_rate : float
    threshold : float
        Minimum predicted probability of TP > SL to allow a trade
        (default 0.55 — slightly above random to filter marginal trades).
    min_train_samples : int
        Minimum samples to train (default 200).
    retain_meta_on_disk : bool
        Whether to persist the trained model.
    """

    def __init__(
        self,
        n_estimators: int = 150,
        max_depth: int = 2,
        learning_rate: float = 0.03,
        threshold: float = 0.55,
        min_train_samples: int = 200,
        retain_meta_on_disk: bool = True,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.threshold = threshold
        self.min_train_samples = min_train_samples
        self.retain_meta_on_disk = retain_meta_on_disk
        self.model: xgb.XGBClassifier | None = None
        self._trained = False
        self._feature_names: list[str] | None = None

    # ── Public API ────────────────────────────────────────────────

    def train(
        self,
        X: pd.DataFrame,
        y_primary: np.ndarray,
        features: list[str],
        asset: str,
        force: bool = False,
    ) -> None:
        """Train the meta-label model.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix (same as primary model training).
        y_primary : np.ndarray
            Primary model predictions (0=short, 1=neutral, 2=long).
        features : list[str]
            Feature column names.
        asset : str
            Asset name (for model path).
        force : bool
            Force retrain even if cached model exists.
        """
        model_path = self._model_path(asset)
        if os.path.exists(model_path) and not force:
            self._load(model_path)
            return

        # Meta label = 1 if trade would be profitable (TP hit or timeout)
        # We use the original triple-barrier label column from the training data
        if "label" not in X.columns:
            logger.warning("%s: no 'label' column in meta training data", asset)
            return

        raw_labels = X["label"].values
        meta_y = np.where(raw_labels == 1, 1, 0).astype(int)

        if meta_y.sum() < self.min_train_samples:
            logger.warning(
                "%s: insufficient meta-positive samples (%d < %d), skipping",
                asset,
                meta_y.sum(),
                self.min_train_samples,
            )
            return

        # Build meta feature set: primary features + model probabilities
        meta_X = self._build_meta_features(X, features, y_primary)

        if len(meta_X) < 100:
            logger.warning("%s: too few meta training rows (%d)", asset, len(meta_X))
            return

        self._feature_names = list(meta_X.columns)

        # Time-based validation split (no lookahead)
        n = len(meta_X)
        n_valid = max(int(n * 0.2), 1)
        split_idx = n - n_valid
        X_tr = meta_X.iloc[:split_idx].values
        X_va = meta_X.iloc[-n_valid:].values
        y_tr = meta_y[:split_idx]
        y_va = meta_y[-n_valid:]

        scale_pos_weight = (y_tr == 0).sum() / (y_tr == 1).sum()
        self.model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            objective="binary:logistic",
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        self.model.fit(
            X_tr,
            y_tr,
            eval_set=[(X_va, y_va)],
            verbose=False,
        )
        self._trained = True

        if self.retain_meta_on_disk:
            with open(model_path, "wb") as f:
                pickle.dump(self, f)
            logger.info(
                "%s: meta model trained (pos_weight=%.2f, n=%d, threshold=%.2f)",
                asset,
                scale_pos_weight,
                len(X_tr),
                self.threshold,
            )

    def predict_proba(self, X: pd.DataFrame, y_primary: np.ndarray) -> float | None:
        """Return predicted probability of TP > SL for latest row.

        Returns None if model is untrained.
        """
        if self.model is None or self._feature_names is None:
            return None

        meta_X = self._build_meta_features(X, self._feature_names, y_primary, infer=True)
        if meta_X.empty:
            return None

        proba = self.model.predict_proba(meta_X.values)[0]
        return float(proba[1])

    def should_enter(self, proba_tp_hit: float | None) -> bool:
        """Return True if trade is allowed by meta-label filter."""
        if proba_tp_hit is None:
            return True
        return proba_tp_hit >= self.threshold

    # ── Internal ──────────────────────────────────────────────────

    def _build_meta_features(
        self,
        X: pd.DataFrame,
        features: list[str],
        y_primary: np.ndarray,
        infer: bool = False,
    ) -> pd.DataFrame:
        if infer:
            orig = [f for f in features if not f.startswith("meta_")]
            base = X[orig].copy()
        else:
            base = X[features].copy()

        # Add primary model probabilities as meta features
        if len(y_primary.shape) == 1 or y_primary.shape[1] == 1:
            base["meta_primary_pred"] = y_primary
            base["meta_primary_long_prob"] = (y_primary == 2).astype(float)
            base["meta_primary_short_prob"] = (y_primary == 0).astype(float)
        else:
            for i, label in enumerate(["short", "neutral", "long"]):
                base[f"meta_primary_prob_{label}"] = y_primary[:, i]

        # Label column is used for training target, not as feature
        if "label" in base.columns:
            base = base.drop(columns=["label"])

        return base

    def _model_path(self, asset: str) -> str:
        return os.path.join(META_MODEL_DIR, f"{asset}_meta.pkl")

    def _load(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                content = f.read()
            sig_path = path + ".sig"
            if os.path.exists(sig_path):
                with open(sig_path, "r") as sf:
                    expected = sf.read().strip()
                actual = hashlib.sha256(content).hexdigest()
                if not hmac.compare_digest(expected, actual):
                    raise ValueError(f"Model integrity check failed for {path}")
            obj = pickle.loads(content)
            self.model = obj.model
            self._feature_names = obj._feature_names
            self._trained = obj._trained
            self.threshold = obj.threshold
            logger.info("Loaded meta model from %s", path)
        except Exception as e:
            logger.warning("Failed to load meta model: %s", e)


# ── Helpers for feature engineering ──────────────────────────────


def meta_label_feature_suggestions() -> list[str]:
    """Recommended additional features for meta-label model.

    These capture factors that influence whether a trade survives
    to hit TP vs getting stopped out.
    """
    return [
        "volatility_regime",  # High vol → more SL hits
        "spread_bps",  # Wide spread → worse fills
        "recent_win_rate_10",  # Hot/cold streak
        "avg_r_multiple_20",  # Recent R-multiple average
        "atr_ratio_14_100",  # Short-term vs long-term vol
        "entry_hour",  # Time-of-day effects
        "day_of_week",  # Day-of-week effects
        "correlation_spy_21",  # Beta to SPY during trade
        "vix_level",  # Fear gauge
    ]
