import pandas as pd
import numpy as np

class BreakoutModel:
    """
    Specialized model for VOLATILE regimes.
    Focuses on momentum and breakout continuation.
    """
    def predict(self, features: pd.DataFrame) -> pd.Series:
        """
        Generates buy/sell/hold probabilities.
        """
        # Heuristic: Momentum continuation in expansion
        # Positive MACD diff + expanding vol -> Prob Up
        
        # Volatility expansion multiplier
        vol_expansion = (features['dist_ema_20'].abs() * 50).clip(0, 1)
        
        # Normalized MACD
        macd_std = features['macd_diff'].rolling(100).std().fillna(0.001)
        macd_prob = (features['macd_diff'] / macd_std).clip(-1, 1) / 2.0 + 0.5
        
        # Combine
        prob = macd_prob * 0.8 + vol_expansion * 0.2
        
        return prob

if __name__ == "__main__":
    # Test
    try:
        data = pd.read_parquet("data/processed/EURUSD_features.parquet")
        model = BreakoutModel()
        probs = model.predict(data)
        print("\nBreakout Probs (Sample):")
        print(probs.tail())
    except Exception as e:
        print(f"Vol Model test failed: {e}")
