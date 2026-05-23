import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import log_loss
import shap
from models.macro_expert_head import MacroExpertHead
from data.loaders.macro_loader import MACRO_FEATURES

class HybridRegimeEnsemble:
    """
    Hybrid Expert Architecture:
    Global Backbone (shallow) + Regime-Specific Expert Heads +
    Protected Macro Expert Head.
    
    The macro head has a fixed blend weight (0.45) so price-driven
    features cannot drown out macro signal (rate_diff, dxy_mom, etc.).
    """
    def __init__(
        self,
        global_weight=0.4,
        expert_weight=0.6,
        directional_prior_weight=0.05,
        transition_penalty_weight=0.10,
        macro_weight=0.45,
        macro_feature_names=None,
        macro_head_config=None,
    ):
        self.global_weight = global_weight
        self.expert_weight = expert_weight
        self.directional_prior_weight = directional_prior_weight
        self.transition_penalty_weight = transition_penalty_weight
        self.macro_weight = macro_weight
        self.macro_feature_names = macro_feature_names or MACRO_FEATURES
        self.macro_head_config = macro_head_config or {}
        
        # XGBoost Config (Institutional Specs)
        self.xgb_params = {
            'n_estimators': 100,
            'learning_rate': 0.03,
            'max_delta_step': 0,
            'tree_method': 'hist',
            'min_child_weight': 3,
            'objective': 'multi:softprob',
            'num_class': 3,
            'random_state': 42
        }
        
        self.global_model = None
        self.expert_heads = {} # {regime: model}
        self.feature_names = None
        self.macro_head = None

    def _get_sample_weights(self, n_samples, regime_type=None):
        """Generates weights with recency decay and regime-aware scaling."""
        # 1. Recency Decay (0.5 to 1.0)
        recency = np.linspace(0.5, 1.0, n_samples)
        
        # 2. Regime-aware scaling
        scales = {'trend': 1.0, 'range': 0.8, 'volatile': 0.6, 'neutral': 0.5}
        regime_scale = scales.get(regime_type, 1.0)
        
        return recency * regime_scale

    def _ensure_train_classes(self, X, y, sample_weight, split, num_classes):
        """Ensure training split (first `split` rows) has all `num_classes` by appending zero-weight dummies."""
        y_train = y.iloc[:split]
        present = np.unique(y_train)
        missing = [c for c in range(num_classes) if c not in present]
        if not missing:
            return X, y, sample_weight, split
        dummy = X.iloc[:len(missing)]
        dy = pd.Series(missing, dtype=y.dtype)
        dw = np.zeros(len(missing))
        # Append dummies after training split, then extend split to include them
        X_aug = pd.concat([X.iloc[:split], dummy, X.iloc[split:]], ignore_index=True)
        y_aug = pd.concat([y.iloc[:split], dy, y.iloc[split:]], ignore_index=True)
        sw_aug = np.concatenate([sample_weight[:split], dw, sample_weight[split:]])
        split_aug = split + len(missing)
        return X_aug, y_aug, sw_aug, split_aug

    def train(self, X, y, regimes):
        """
        Trains the global backbone, regime-specific experts, and macro head.
        """
        self.feature_names = X.columns.tolist()
        nc = self.xgb_params['num_class']
        
        # 1. Train Global Backbone
        print("Training Global Backbone...")
        self.global_model = xgb.XGBClassifier(**self.xgb_params, max_depth=2, early_stopping_rounds=30)
        weights_global = self._get_sample_weights(len(X))
        
        split = int(len(X) * 0.8)
        X_g, y_g, sw_g, split_g = self._ensure_train_classes(X, y, weights_global, split, nc)
        self.global_model.fit(
            X_g.iloc[:split_g], y_g.iloc[:split_g],
            sample_weight=sw_g[:split_g],
            eval_set=[(X_g.iloc[split_g:], y_g.iloc[split_g:])],
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
            
            split_r = int(len(X_r) * 0.8)
            X_re, y_re, sw_re, split_re = self._ensure_train_classes(X_r, y_r, weights_expert, split_r, nc)
            
            expert.fit(
                X_re.iloc[:split_re], y_re.iloc[:split_re],
                sample_weight=sw_re[:split_re],
                eval_set=[(X_re.iloc[split_re:], y_re.iloc[split_re:])],
                verbose=False
            )
            self.expert_heads[r] = expert
        
        # 3. Train Macro Expert Head
        macro_cols = [c for c in self.macro_feature_names if c in X.columns]
        if len(macro_cols) >= 3:
            print("Training Macro Expert Head...")
            mh_features = self.macro_head_config.get('features', self.macro_feature_names)
            mh_params = self.macro_head_config.get('model_params', {})
            self.macro_head = MacroExpertHead(features=mh_features, model_params=mh_params)
            self.macro_head.fit(X[macro_cols], y)
            print("Macro Expert Head trained.")
        else:
            print(f"Skipping macro head (only {len(macro_cols)}/{len(self.macro_feature_names)} columns found in X)")

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
        Generates blended probabilities with protected macro head weight.
        final = macro_weight * macro_probs + (1 - macro_weight) * regime_blend
        """
        global_probs = self.global_model.predict_proba(X)
        regime_blend = np.zeros_like(global_probs)
        
        for i in range(len(X)):
            r = regimes.iloc[i]
            if r in self.expert_heads:
                expert_prob = self.expert_heads[r].predict_proba(X.iloc[[i]])[0]
                regime_blend[i] = (global_probs[i] * self.global_weight) + (expert_prob * self.expert_weight)
            else:
                regime_blend[i] = global_probs[i] # Fallback to global
        
        regime_blend = self._apply_directional_prior(X, regime_blend, regimes)
        
        # Blend with macro head if available
        if self.macro_head is not None:
            macro_cols = [c for c in self.macro_feature_names if c in X.columns]
            if len(macro_cols) >= 3:
                macro_probs = self.macro_head.predict_proba(X[macro_cols])
                
                # Use adaptive weight if online_weight is enabled in the macro head
                w = getattr(self.macro_head, "current_weight", self.macro_weight)
                
                final = (w * macro_probs + 
                         (1.0 - w) * regime_blend)
                final = final / final.sum(axis=1, keepdims=True)
                return final
        
        return regime_blend

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
