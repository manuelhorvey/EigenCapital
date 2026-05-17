import pandas as pd
import numpy as np

def generate_interaction_features(base_features: pd.DataFrame, 
                                  regime_data: pd.DataFrame, 
                                  struct_features: pd.DataFrame) -> pd.DataFrame:
    """
    Creates soft-coupled interaction features and uncertainty metrics.
    """
    # 1. Align indices
    common_idx = base_features.index.intersection(regime_data.index).intersection(struct_features.index)
    base = base_features.loc[common_idx]
    regime = regime_data.loc[common_idx]
    struct = struct_features.loc[common_idx]
    
    df = pd.DataFrame(index=common_idx)
    
    # 2. Regime Contrast (Directional Regime Signal)
    # Scaled to [-1, 1]
    df['regime_contrast'] = np.clip(regime['P_trend'] - regime['P_range'], -1.0, 1.0)
    
    # 3. Soft Interactions (Indicator * Contrast)
    # This couples the "what" (indicator) with the "context" (regime)
    df['ema_contrast'] = base['ema_spread'] * df['regime_contrast']
    df['slope_contrast'] = struct['slope_20'] * df['regime_contrast']
    df['path_contrast'] = struct['path_efficiency_20'] * df['regime_contrast']
    
    # 4. Regime Entropy (Uncertainty Proxy)
    # -sum(p * log(p))
    probs = regime[['P_trend', 'P_range', 'P_volatile']].values
    # Avoid log(0)
    df['regime_entropy'] = -np.sum(probs * np.log(probs + 1e-9), axis=1)
    
    # 5. Transition Risk (Magnitude of probability shift)
    # Captures "boundary crossing" volatility
    prob_diffs = regime[['P_trend', 'P_range', 'P_volatile']].diff().abs()
    df['transition_risk'] = prob_diffs.sum(axis=1).fillna(0)
    
    return df

if __name__ == "__main__":
    try:
        # Load all components
        base = pd.read_parquet("data/processed/EURUSD_features.parquet")
        regime = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
        struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
        
        interactions = generate_interaction_features(base, regime, struct)
        
        print("\n--- Interaction Feature Audit ---")
        print(f"Features generated: {len(interactions.columns)}")
        print("\nSample Statistics:")
        print(interactions.describe().loc[['mean', 'std', 'min', 'max']])
        
        # Check transition risk spikes
        high_risk = interactions[interactions['transition_risk'] > interactions['transition_risk'].quantile(0.95)]
        print(f"\nTop 5% Transition Risk events: {len(high_risk)}")
        
        # Save
        interactions.to_parquet("data/processed/EURUSD_interaction_features.parquet")
        print("\nSaved to data/processed/EURUSD_interaction_features.parquet")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
