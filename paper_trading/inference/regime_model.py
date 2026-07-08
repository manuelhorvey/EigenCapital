import logging
import os

import numpy as np
import pandas as pd
import xgboost as xgb

logger = logging.getLogger("eigencapital.regime_model")

REGIME_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models",
    "regime",
)
os.makedirs(REGIME_MODEL_DIR, exist_ok=True)

_MIN_TRAIN_ROWS = 100


class RegimeConditionalModel:
    """
    Binary XGBoost classifier trained with regime features as conditioning context.

    Uses objective='binary:logistic' and XGBoost native JSON persistence
    (no pickle / no joblib).

    Labels expected: {0 = SHORT, 1 = LONG}.
    HOLD/neutral samples are filtered out before training.

    Training uses an internal time-based validation split with embargo gap
    (default 20 rows) so early stopping and scale_pos_weight are correctly
    computed from the training set only.
    """

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 2,
        learning_rate: float = 0.03,
        early_stopping_rounds: int = 50,
        embargo: int = 20,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.early_stopping_rounds = early_stopping_rounds
        self.embargo = embargo
        self._model: xgb.XGBClassifier | None = None
        self._trained = False
        self._feature_names: list[str] = []
        self._asset_name: str = ""
        self._val_score: float | None = None
        self._best_iteration: int | None = None

    def _base_path(self, asset_name: str = "") -> str:
        stem = "regime_conditional"
        if asset_name:
            stem = f"{asset_name}_regime"
        return os.path.join(REGIME_MODEL_DIR, stem)

    def train(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        feature_names: list[str],
        asset_name: str = "",
    ) -> None:
        self._feature_names = feature_names
        self._asset_name = asset_name
        y_int = y.astype(int)

        present = set(y_int.unique())
        if present != {0, 1}:
            logger.warning("regime model: labels %s — need {0, 1} for binary", sorted(present))
            return
        if y_int.sum() == 0 or y_int.sum() == len(y_int):
            logger.warning("regime model: only one class present — cannot train")
            return

        # Time-based validation split with embargo
        n = len(x)
        n_val = max(int(n * 0.2), 1)
        train_end = n - n_val - self.embargo
        if train_end < _MIN_TRAIN_ROWS:
            train_end = n - n_val
        has_val = len(x) - train_end - self.embargo >= 5 and train_end >= _MIN_TRAIN_ROWS

        if has_val:
            X_fit = x.iloc[:train_end]
            X_val = x.iloc[min(train_end + self.embargo, n):]
            y_fit = y_int.iloc[:train_end]
            y_val = y_int.iloc[min(train_end + self.embargo, n):]

            n0 = (y_fit == 0).sum()
            n1 = (y_fit == 1).sum()
            spw = n0 / max(n1, 1)

            self._model = xgb.XGBClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                objective="binary:logistic",
                scale_pos_weight=spw,
                early_stopping_rounds=self.early_stopping_rounds,
                random_state=42,
                n_jobs=1,
                tree_method="hist",
                verbosity=0,
            )
            self._model.fit(
                X_fit[self._feature_names], y_fit,
                eval_set=[(X_val[self._feature_names], y_val)],
                verbose=False,
            )
            self._best_iteration = self._model.best_iteration + 1 if hasattr(self._model, "best_iteration") else None
            self._val_score = float(self._model.score(X_val[self._feature_names], y_val))
            logger.info(
                "regime model %s: %d fit / %d val samples, "
                "spw=%.2f, best_iter=%s, val_score=%.4f",
                asset_name,
                len(X_fit),
                len(X_val),
                spw,
                self._best_iteration,
                self._val_score,
            )
        else:
            # Fallback: no validation split possible (small dataset)
            n0 = (y_int == 0).sum()
            n1 = (y_int == 1).sum()
            spw = n0 / max(n1, 1)

            self._model = xgb.XGBClassifier(
                n_estimators=min(self.n_estimators, 100),
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                objective="binary:logistic",
                scale_pos_weight=spw,
                random_state=42,
                n_jobs=1,
                tree_method="hist",
                verbosity=0,
            )
            self._model.fit(x[self._feature_names], y_int)
            self._val_score = None
            logger.info(
                "regime model %s: %d samples, spw=%.2f (no validation — dataset too small)",
                asset_name,
                n,
                spw,
            )

        self._trained = True

        path = self._base_path(asset_name)
        self._model.save_model(f"{path}.json")
        with open(f"{path}_features.txt", "w") as f:
            f.write("\n".join(feature_names))
        logger.info(
            "regime model trained on %d samples, %d features -> %s.json",
            len(x),
            len(feature_names),
            path,
        )

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        if not self._trained or self._model is None:
            raise RuntimeError("regime model not trained — call train() first")
        raw = self._model.predict_proba(x[self._feature_names])
        return raw  # shape (n, 2): column 0 = P(SHORT), column 1 = P(LONG)

    def predict_long_prob(self, x: pd.DataFrame) -> np.ndarray:
        raw = self.predict_proba(x)
        return raw[:, 1].reshape(-1, 1)  # shape (n, 1): P(LONG)

    def load(self, asset_name: str = "") -> bool:
        base = self._base_path(asset_name)
        json_path = f"{base}.json"
        feat_path = f"{base}_features.txt"
        if os.path.exists(json_path):
            self._model = xgb.XGBClassifier()
            self._model.load_model(json_path)
            self._trained = True
            # Restore feature names
            if os.path.exists(feat_path):
                with open(feat_path) as f:
                    self._feature_names = [line.strip() for line in f if line.strip()]
            logger.info("regime model loaded from %s.json (%d features)", base, len(self._feature_names))
            return True
        logger.warning("regime model not found at %s.json", base)
        return False
