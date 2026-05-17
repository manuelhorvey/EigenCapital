import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import log_loss
import shap

class HybridRegimeEnsemble:
    """
    Hybrid Expert Architecture:
    Global Backbone (shallow) + Regime-Specific Expert Heads.
    Blends general market behavior with specialized regime expertise.
    """
    def __init__(
        self,
        global_weight=0.4,
        expert_weight=0.6,
        directional_prior_weight=0.05,
        transition_penalty_weight=0.10,
    ):
        self.global_weight = global_weight
        self.expert_weight = expert_weight
        self.directional_prior_weight = directional_prior_weight
        self.transition_penalty_weight = transition_penalty_weight
        
        # XGBoost Config (Institutional Specs)
        self.xgb_params = {
            'n_estimators': 500,
            'learning_rate': 0.01,
            'max_delta_step': 1,
            'tree_method': 'hist',
            'min_child_weight': 10,
            'objective': 'multi:softprob',
            'num_class': 3, # 0, 1, 2 for -1, 0, 1 labels
            'random_state': 42
        }
        
        self.global_model = None
        self.expert_heads = {} # {regime: model}
        self.feature_names = None

    def _get_sample_weights(self, n_samples, regime_type=None):
        """Generates weights with recency decay and regime-aware scaling."""
        # 1. Recency Decay (0.5 to 1.0)
        recency = np.linspace(0.5, 1.0, n_samples)
        
        # 2. Regime-aware scaling
        scales = {'trend': 1.0, 'range': 0.8, 'volatile': 0.6, 'neutral': 0.5}
        regime_scale = scales.get(regime_type, 1.0)
        
        return recency * regime_scale

    def train(self, X, y, regimes):
        """
        Trains the global backbone and regime-specific experts.
        """
        self.feature_names = X.columns.tolist()
        
        # 1. Train Global Backbone
        print("Training Global Backbone...")
        self.global_model = xgb.XGBClassifier(**self.xgb_params, max_depth=2, early_stopping_rounds=30)
        weights_global = self._get_sample_weights(len(X))
        
        # Use simple time-based split for early stopping
        split = int(len(X) * 0.8)
        self.global_model.fit(
            X.iloc[:split], y.iloc[:split],
            sample_weight=weights_global[:split],
            eval_set=[(X.iloc[split:], y.iloc[split:])],
            verbose=False
        )
        
        # 2. Train Regime Experts
        unique_regimes = regimes.unique()
        for r in unique_regimes:
            if r == 'neutral' and len(regimes[regimes == r]) < 100: continue
            
            print(f"Training Expert Head: {r.upper()}...")
            mask = (regimes == r)
            X_r, y_r = X[mask], y[mask]
            
            if len(X_r) < 50: 
                print(f"Skipping {r} expert (insufficient data: {len(X_r)})")
                continue
                
            expert = xgb.XGBClassifier(**self.xgb_params, max_depth=3, early_stopping_rounds=20)
            weights_expert = self._get_sample_weights(len(X_r), regime_type=r)
            
            # Internal split for expert
            split_r = int(len(X_r) * 0.8)
            expert.fit(
                X_r.iloc[:split_r], y_r.iloc[:split_r],
                sample_weight=weights_expert[:split_r],
                eval_set=[(X_r.iloc[split_r:], y_r.iloc[split_r:])],
                verbose=False
            )
            self.expert_heads[r] = expert

    def _apply_directional_prior(self, X, probs, regimes):
        """
        Enforces regime-probability semantics at the model layer.

        TREND: higher P_trend increases long probability.
        RANGE: higher P_range increases non-neutral mean-reversion strength.
        VOLATILE: higher P_volatile lowers directional exposure.
        """
        adjusted = probs.copy()

        if not {'P_trend', 'P_range', 'P_volatile'}.issubset(X.columns):
            return adjusted

        for i in range(len(X)):
            row = X.iloc[i]
            regime = regimes.iloc[i]
            weight = self.directional_prior_weight

            if regime == 'trend':
                adjusted[i, 2] *= 1.0 + weight * np.clip(row['P_trend'], 0.0, 1.0)
            elif regime == 'range':
                boost = 1.0 + weight * np.clip(row['P_range'], 0.0, 1.0)
                adjusted[i, 0] *= boost
                adjusted[i, 2] *= boost
            elif regime == 'volatile':
                damp = 1.0 - weight * np.clip(row['P_volatile'], 0.0, 1.0)
                adjusted[i, 0] *= damp
                adjusted[i, 2] *= damp

            if 'transition_risk' in X.columns:
                transition_damp = 1.0 - self.transition_penalty_weight * np.clip(row['transition_risk'], 0.0, 1.0)
                adjusted[i, 0] *= transition_damp
                adjusted[i, 2] *= transition_damp

        adjusted = np.clip(adjusted, 1e-12, None)
        adjusted = adjusted / adjusted.sum(axis=1, keepdims=True)
        return adjusted

    def predict_proba(self, X, regimes):
        """
        Generates blended probabilities.
        """
        global_probs = self.global_model.predict_proba(X)
        final_probs = np.zeros_like(global_probs)
        
        for i in range(len(X)):
            r = regimes.iloc[i]
            if r in self.expert_heads:
                expert_prob = self.expert_heads[r].predict_proba(X.iloc[[i]])[0]
                final_probs[i] = (global_probs[i] * self.global_weight) + (expert_prob * self.expert_weight)
            else:
                final_probs[i] = global_probs[i] # Fallback to global
                
        return self._apply_directional_prior(X, final_probs, regimes)

    def explain(self, X_sample, regime_type):
        """Uses SHAP to explain decisions for a specific regime."""
        if regime_type not in self.expert_heads:
            return None
        
        explainer = shap.TreeExplainer(self.expert_heads[regime_type])
        shap_values = explainer.shap_values(X_sample)
        return shap_values

if __name__ == "__main__":
    try:
        # 1. Assemble the Manifold
        base = pd.read_parquet("data/processed/EURUSD_features.parquet")
        regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
        struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
        interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
        labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
        
        # Align
        common_idx = base.index.intersection(regime_meta.index).intersection(struct.index).intersection(interact.index).intersection(labeled.index)
        
        X = pd.concat([
            base.loc[common_idx].drop('label', axis=1),
            regime_meta.loc[common_idx][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
            struct.loc[common_idx],
            interact.loc[common_idx]
        ], axis=1)
        
        y = labeled.loc[common_idx, 'label'] + 1 # Map -1,0,1 to 0,1,2
        regimes = regime_meta.loc[common_idx, 'regime']
        
        # 2. Train Ensemble
        ensemble = HybridRegimeEnsemble()
        ensemble.train(X, y, regimes)
        
        # 3. Simple OOS Test (Last 20% of TREND regime)
        trend_mask = (regimes == 'trend')
        X_trend = X[trend_mask]
        y_trend = y[trend_mask]
        
        split = int(len(X_trend) * 0.8)
        X_oos = X_trend.iloc[split:]
        y_oos = y_trend.iloc[split:]
        r_oos = regimes.loc[X_oos.index]
        
        probs = ensemble.predict_proba(X_oos, r_oos)
        preds = np.argmax(probs, axis=1)
        
        accuracy = (preds == y_oos).mean()
        print(f"\nTREND OOS Accuracy: {accuracy:.2%}")
        
        # 4. SHAP Verification (Sanity check for P_trend importance)
        print("\nRunning SHAP Verification for TREND expert...")
        explainer = shap.TreeExplainer(ensemble.expert_heads['trend'])
        shap_values = explainer.shap_values(X_oos)
        
        # Check type and shape
        if isinstance(shap_values, list):
            # For multiclass, shap_values[2] is class 2 (Label 1 - Long)
            class_idx = 2
            importance_data = np.abs(shap_values[class_idx]).mean(axis=0)
        else:
            # For some versions/configs, it might be a 3D array (samples, features, classes)
            # or (samples, classes, features)
            if len(shap_values.shape) == 3:
                # Average across samples for class 2
                importance_data = np.abs(shap_values[:, :, 2]).mean(axis=0)
            else:
                importance_data = np.abs(shap_values).mean(axis=0)
        
        importance = pd.Series(importance_data, index=X.columns).sort_values(ascending=False)
        print("\nTop 5 Features (TREND Head - Long Class):")
        print(importance.head(5))
        
        if 'P_trend' in importance.head(10).index:
            print("\nSUCCESS: P_trend is in the top 10 features for the TREND head.")
        else:
            print("\nWARNING: P_trend is missing from top features.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
