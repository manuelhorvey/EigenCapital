import pandas as pd
import numpy as np
from models.regime.regime_classifier import RegimeClassifier
from models.hybrid_ensemble import HybridRegimeEnsemble

class RegimeAwareSignalGenerator:
    """
    Institutional Gearbox Signal Engine.
    Routes to specialized models and applies dynamic thresholds/scaling.
    Uses the Hybrid Expert Ensemble.
    """
    def __init__(self, ensemble: HybridRegimeEnsemble):
        self.regime_classifier = RegimeClassifier(confidence_threshold=0.45)
        self.ensemble = ensemble

    def generate_signals(self, 
                         X_manifold: pd.DataFrame, 
                         regime_features: pd.DataFrame) -> pd.DataFrame:
        """
        Main routing logic using the hybrid manifold.
        """
        # 1. Classify Regime
        regime_data = self.regime_classifier.classify(regime_features)
        regimes = regime_data['regime']
        
        # 2. Layer 1: Hybrid Model Prediction
        # X_manifold contains the full geometric and interaction space
        probs = self.ensemble.predict_proba(X_manifold, regimes)
        
        results = regime_data.copy()
        results['raw_prob_short'] = probs[:, 0]
        results['raw_prob_neutral'] = probs[:, 1]
        results['raw_prob_long'] = probs[:, 2]
        
        print("\n--- Probability Stats ---")
        print(results[['raw_prob_short', 'raw_prob_neutral', 'raw_prob_long']].describe().loc[['mean', 'max']])
        
        # 3. Layer 2: Fixed signal thresholding.
        # Regime routing happens once inside the ensemble. Downstream logic is
        # intentionally stateless to avoid compounding regime decisions.
        results['signal'] = 0

        long_threshold = 0.387
        short_threshold = 0.37
        long_mask = results['raw_prob_long'] > long_threshold
        short_mask = results['raw_prob_short'] > short_threshold
        results.loc[long_mask, 'signal'] = 1
        results.loc[short_mask, 'signal'] = -1
        both_mask = long_mask & short_mask
        results.loc[both_mask, 'signal'] = (results.loc[both_mask, 'raw_prob_long'] >= results.loc[both_mask, 'raw_prob_short']).astype(int) * 2 - 1

        # 4. Fixed risk layer.
        results['risk_multiplier'] = 1.0
        
        return results

if __name__ == "__main__":
    try:
        # Load Manifold
        base = pd.read_parquet("data/processed/EURUSD_features.parquet")
        regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
        struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
        interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
        labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
        
        common_idx = base.index.intersection(regime_meta.index).intersection(struct.index).intersection(interact.index).intersection(labeled.index)
        
        X = pd.concat([
            base.loc[common_idx].drop('label', axis=1),
            regime_meta.loc[common_idx][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
            struct.loc[common_idx],
            interact.loc[common_idx]
        ], axis=1)
        
        y = labeled.loc[common_idx, 'label'] + 1
        regimes = regime_meta.loc[common_idx, 'regime']
        
        # Train Ensemble (In a real system, this would be a loaded checkpoint)
        ensemble = HybridRegimeEnsemble()
        ensemble.train(X, y, regimes)
        
        # Generate Signals
        generator = RegimeAwareSignalGenerator(ensemble)
        signals = generator.generate_signals(X, regime_meta.loc[common_idx])
        
        print("\nSignal Summary:")
        print(signals['signal'].value_counts())
        
        # Save signals
        signals.to_parquet("data/processed/EURUSD_signals.parquet")
        print("\nSaved signals to data/processed/EURUSD_signals.parquet")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
