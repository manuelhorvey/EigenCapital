import logging
import pandas as pd
import numpy as np
import xgboost as xgb
from data.loaders.macro_loader import MACRO_FEATURES

logger = logging.getLogger("quantforge.macro_expert")


class MacroExpertHead:
    """Protected macro-only expert head.
    Trained only on macro features (rate_diff, dxy_mom, yield_slope, etc.).
    Always fires at inference with a fixed blend weight so price noise
    cannot drown out the macro signal.

    Per-asset configuration: pass custom feature list and model params
    (e.g. learning_rate=0.30 for EURUSD COT-enhanced head).
    """
    def __init__(self, features=None, model_params=None, online_weight: bool = False):
        self.features = features or MACRO_FEATURES
        self.model_params = model_params or {}
        self.model = None
        self.online_weight = online_weight
        self.current_weight = 0.45 # default starting weight
        self.performance_history = [] # track (macro_ret, blend_ret)

    def _ensure_train_classes(self, X, y, split, num_classes):
        """Ensure training split has all `num_classes` by inserting zero-weight dummies."""
        y_train = y.iloc[:split]
        present = np.unique(y_train)
        missing = [c for c in range(num_classes) if c not in present]
        if not missing:
            return X, y, split
        dummy = X.iloc[:len(missing)]
        dy = pd.Series(missing, dtype=y.dtype, index=dummy.index)
        X_aug = pd.concat([X.iloc[:split], dummy, X.iloc[split:]])
        y_aug = pd.concat([y.iloc[:split], dy, y.iloc[split:]])
        return X_aug, y_aug, split + len(missing)

    def fit(self, X_macro, y):
        X = X_macro[self.features].copy()
        split = int(len(X) * 0.8)
        X, y, split = self._ensure_train_classes(X, y, split, 3)
        params = {
            'n_estimators': 100,
            'max_depth': 2,
            'learning_rate': 0.03,
            'subsample': 0.8,
            'min_child_weight': 5,
            'reg_alpha': 0.1,
            'reg_lambda': 1.0,
            'colsample_bytree': 1.0,
            'objective': 'multi:softprob',
            'num_class': 3,
            'random_state': 42,
            'tree_method': 'hist',
            'n_jobs': 1,
            'verbosity': 0,
        }
        params.update(self.model_params)
        self.model = xgb.XGBClassifier(**params)
        self.model.fit(
            X.iloc[:split], y.iloc[:split],
            eval_set=[(X.iloc[split:], y.iloc[split:])],
            verbose=False,
        )

    def predict_proba(self, X):
        return self.model.predict_proba(X[self.features])

    def update_weight(self, macro_ret: float, blend_ret: float):
        """
        Adjusts the expert blend weight based on relative performance.
        Uses a soft update: w += 0.01 * (macro_sharpe - blend_sharpe).
        Weight is bounded within [0.25, 0.65].
        """
        if not self.online_weight:
            return

        self.performance_history.append((macro_ret, blend_ret))
        if len(self.performance_history) >= 21: # Need some history
            recent = self.performance_history[-63:]
            m_rets = [r[0] for r in recent]
            b_rets = [r[1] for r in recent]

            m_sharpe = np.mean(m_rets) / (np.std(m_rets) + 1e-9)
            b_sharpe = np.mean(b_rets) / (np.std(b_rets) + 1e-9)

            # Soft update toward the outperforming head
            delta = 0.01 * (m_sharpe - b_sharpe)
            self.current_weight = np.clip(self.current_weight + delta, 0.25, 0.65)
            logger.debug(f"Macro weight updated to {self.current_weight:.4f} (m_sharpe={m_sharpe:.2f}, b_sharpe={b_sharpe:.2f})")
