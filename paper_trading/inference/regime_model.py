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


class RegimeConditionalModel:
    """
    Binary XGBoost classifier trained with regime features as conditioning context.

    Uses objective='binary:logistic' and XGBoost native JSON persistence
    (no pickle / no joblib).

    Labels expected: {0 = SHORT, 1 = LONG}.
    HOLD/neutral samples are filtered out before training.
    """

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 2,
        learning_rate: float = 0.03,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self._model: xgb.XGBClassifier | None = None
        self._trained = False
        self._feature_names: list[str] = []
        self._asset_name: str = ""

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

        self._model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            objective="binary:logistic",
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        self._model.fit(x[self._feature_names], y_int)
        self._trained = True

        path = self._base_path(asset_name)
        self._model.save_model(f"{path}.json")
        # Persist feature names alongside the model (plain text, one per line)
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
