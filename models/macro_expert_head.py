import pandas as pd
import numpy as np
import xgboost as xgb
from data.loaders.macro_loader import MACRO_FEATURES


class MacroExpertHead:
    """Protected macro-only expert head.
    Trained only on macro features (rate_diff, dxy_mom, yield_slope, etc.).
    Always fires at inference with a fixed blend weight so price noise
    cannot drown out the macro signal.

    Per-asset configuration: pass custom feature list and model params
    (e.g. learning_rate=0.30 for EURUSD COT-enhanced head).
    """
    def __init__(self, features=None, model_params=None):
        self.features = features or MACRO_FEATURES
        self.model_params = model_params or {}
        self.model = None

    def fit(self, X_macro, y):
        X = X_macro[self.features].copy()
        split = int(len(X) * 0.8)
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
