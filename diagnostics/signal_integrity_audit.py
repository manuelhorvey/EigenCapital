import pandas as pd
import numpy as np

def verify_signal_integrity():
    try:
        # Load raw data and signals
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        signals = pd.read_parquet("data/processed/EURUSD_signals.parquet")
        labeled_data = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
        
        # 1. Label Alignment Check
        print("\n--- 1. Label Alignment Check ---")
        # Sample 5 entries where label is +1
        long_labels = labeled_data[labeled_data['label'] == 1].sample(min(5, len(labeled_data[labeled_data['label'] == 1])))
        for idx in long_labels.index:
            entry_price = data.loc[idx, 'close']
            # Look ahead 20 bars
            future = data.loc[idx:].iloc[1:21]['close']
            max_gain = (future.max() - entry_price) / entry_price
            max_loss = (future.min() - entry_price) / entry_price
            print(f"Index: {idx} | Label=+1 | Max Gain: {max_gain:.2%} | Max Loss: {max_loss:.2%}")

        # 2. Signal vs Label Direction (In TREND regime)
        print("\n--- 2. Signal vs Label Direction (TREND) ---")
        trend_signals = signals[signals['regime'] == 'trend']
        # Merge with actual labels
        merged = trend_signals.join(labeled_data['label'], how='inner')
        
        # Accuracy of signal matching label
        correct_direction = (merged['signal'] == merged['label']).mean()
        inverse_direction = (merged['signal'] == -merged['label']).mean()
        
        print(f"Signal matches Label: {correct_direction:.2%}")
        print(f"Signal inverts Label: {inverse_direction:.2%}")
        
        # 3. Model Probability Mapping Check
        print("\n--- 3. Prob vs Signal Mapping (Sample) ---")
        print(merged[['raw_prob_long', 'signal', 'label']].tail(10))

        # 4. Volatile Regime Zero-Check
        print("\n--- 4. Volatile Regime Check ---")
        vol_data = signals[signals['regime'] == 'volatile']
        print(f"Volatile Sample Count: {len(vol_data)}")
        print(f"Volatile Risk Multipliers: {vol_data['risk_multiplier'].unique()}")
        print(f"Volatile Signals: {vol_data['signal'].unique()}")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_signal_integrity()
