import pandas as pd
import numpy as np
from models.mean_reversion.mr_model import MeanReversionModel

def debug_mr_signals():
    try:
        # Load features and signals
        features = pd.read_parquet("data/processed/EURUSD_features.parquet")
        signals = pd.read_parquet("data/processed/EURUSD_signals.parquet")
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        
        # Merge
        df = signals.join(features[['rsi', 'bb_zscore']], how='inner')
        df['returns'] = data['close'].pct_change().shift(-1) # Forward return
        
        range_df = df[df['regime'] == 'range']
        print(f"\n--- Range Debug (Samples: {len(range_df)}) ---")
        
        # Check Oversold (Low RSI) -> Signal
        oversold = range_df[range_df['rsi'] < 35]
        print(f"Oversold (RSI < 35) Signal Mean: {oversold['signal'].mean():.2f} (Expected > 0)")
        print(f"Oversold Win Rate: {(oversold['signal'] * oversold['returns'] > 0).mean():.2%}")
        
        # Check Overbought (High RSI) -> Signal
        overbought = range_df[range_df['rsi'] > 65]
        print(f"Overbought (RSI > 65) Signal Mean: {overbought['signal'].mean():.2f} (Expected < 0)")
        print(f"Overbought Win Rate: {(overbought['signal'] * overbought['returns'] > 0).mean():.2%}")

        # Sample Check
        print("\nSample Rows (RANGE):")
        print(range_df[['rsi', 'bb_zscore', 'raw_prob_long', 'signal', 'returns']].tail(10))

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_mr_signals()
