import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib.pyplot as plt

def train_baseline_xgboost(data_path: str):
    """
    Trains a baseline XGBoost model on the provided feature set.
    """
    df = pd.read_parquet(data_path)
    
    # Ensure index is datetime
    df.index = pd.to_datetime(df.index)
    
    # Split by date
    train_df = df[df.index < '2020-01-01']
    test_df = df[(df.index >= '2020-01-01') & (df.index < '2022-01-01')]
    
    if len(train_df) == 0 or len(test_df) == 0:
        print(f"Insufficient data for split. Train: {len(train_df)}, Test: {len(test_df)}")
        return
        
    X_train = train_df.drop('label', axis=1)
    y_train = train_df['label']
    
    # XGBoost expects 0, 1, 2 for multiclass
    # Our labels are -1, 0, 1. Map to 0, 1, 2
    y_train_mapped = y_train + 1
    
    X_test = test_df.drop('label', axis=1)
    y_test = test_df['label']
    y_test_mapped = y_test + 1
    
    print(f"Training on {len(X_train)} samples, testing on {len(X_test)} samples...")
    
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        objective='multi:softprob',
        random_state=42
    )
    
    model.fit(X_train, y_train_mapped)
    
    # Predictions
    preds_mapped = model.predict(X_test)
    preds = preds_mapped - 1
    
    # Metrics
    print("\nClassification Report (Test Set 2020-2021):")
    print(classification_report(y_test, preds))
    
    # Feature Importance
    importance = pd.Series(model.feature_importances_, index=X_train.columns).sort_values(ascending=False)
    print("\nFeature Importance:")
    print(importance)
    
    # Simple Equity Curve (Daily Returns * Signal)
    # Note: This is a very naive simulation
    test_data_raw = pd.read_parquet("data/raw/EURUSD_1d.parquet")
    test_returns = test_data_raw['close'].pct_change().loc[test_df.index]
    
    strategy_returns = test_returns * preds
    cumulative_returns = (1 + strategy_returns).cumprod()
    
    sharpe = np.sqrt(252) * strategy_returns.mean() / strategy_returns.std()
    print(f"\nNaive Sharpe Ratio (OOS): {sharpe:.2f}")
    
    return model

if __name__ == "__main__":
    train_baseline_xgboost("data/processed/EURUSD_features.parquet")
