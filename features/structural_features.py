import pandas as pd
import numpy as np
from scipy import stats

def compute_slope_and_curvature(series: pd.Series, window: int = 10) -> tuple:
    """
    Computes rolling log-linear slope and normalized curvature.
    Normalization ensures curvature is not dominated by high-volatility regimes.
    """
    log_price = np.log(series)
    vol = log_price.rolling(window=20).std()
    
    # 1. Rolling Linear Slope
    def get_slope(y):
        x = np.arange(len(y))
        slope, _, _, _, _ = stats.linregress(x, y)
        return slope

    slope = log_price.rolling(window=window).apply(get_slope)
    
    # 2. Stabilize Slope with Smoothing
    slope_smoothed = slope.rolling(window=3).mean()
    
    # 3. Normalized Curvature (Acceleration / Vol)
    # Corrected: curvature = slope.diff() / vol
    curvature = slope_smoothed.diff() / (vol + 1e-9)
    
    return slope_smoothed, curvature

def compute_path_efficiency(series: pd.Series, window: int = 20) -> pd.Series:
    """
    Efficiency = Net Displacement / Total Distance Traveled.
    1.0 = Pure Trend, ~0.0 = Pure Chop.
    """
    def get_efficiency(x):
        # x is a numpy array when raw=True
        net = abs(x[-1] - x[0])
        dist = np.sum(np.abs(np.diff(x)))
        return net / (dist + 1e-9)

    return series.rolling(window=window).apply(get_efficiency, raw=True)

def compute_distributional_stats(returns: pd.Series, window: int = 63) -> pd.DataFrame:
    """
    Captures higher-order moments and safe tail risk using rolling windows.
    """
    df = pd.DataFrame(index=returns.index)
    df['skew'] = returns.rolling(window=window).skew()
    df['kurt'] = returns.rolling(window=window).kurt()
    
    # SAFE Tail Ratio: 90th percentile gain / 10th percentile loss (absolute)
    # Uses only past window data to avoid leakage.
    q90 = returns.rolling(window=window).quantile(0.9)
    q10 = returns.rolling(window=window).quantile(0.1).abs()
    df['tail_ratio'] = q90 / (q10 + 1e-9)
        
    return df

def generate_structural_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main entry point for structural market geometry features.
    """
    df = df.copy()
    
    # 1. Geometry (Slope and Normalized Curvature)
    df['slope_20'], df['curvature_20'] = compute_slope_and_curvature(df['close'], window=20)
    df['slope_10'], df['curvature_10'] = compute_slope_and_curvature(df['close'], window=10)
    
    # 2. Path Dependency
    df['path_efficiency_20'] = compute_path_efficiency(df['close'], window=20)
    df['path_efficiency_63'] = compute_path_efficiency(df['close'], window=63)
    
    # 3. Distributional Stats
    returns = np.log(df['close'] / df['close'].shift(1))
    dist_stats = compute_distributional_stats(returns, window=63)
    df = df.join(dist_stats)
    
    # --- Cleanup ---
    structural_cols = [
        'slope_20', 'curvature_20', 'slope_10', 'curvature_10',
        'path_efficiency_20', 'path_efficiency_63',
        'skew', 'kurt', 'tail_ratio'
    ]
    
    return df[structural_cols].dropna()

if __name__ == "__main__":
    try:
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        struct_features = generate_structural_features(data)
        
        print("\n--- Structural Feature Audit ---")
        print(f"Features generated: {len(struct_features.columns)}")
        
        # Sanity Test: Compare 2017 (Trending) vs 2021 (Choppy)
        df = struct_features.copy()
        df['year'] = df.index.year
        yearly_avg = df.groupby('year')[['path_efficiency_20', 'path_efficiency_63', 'skew', 'kurt']].mean()
        
        print("\nYearly Averages (Structure):")
        print(yearly_avg.loc[[2017, 2021]])
        
        eff_2017 = yearly_avg.loc[2017, 'path_efficiency_63']
        eff_2021 = yearly_avg.loc[2021, 'path_efficiency_63']
        
        if eff_2017 > eff_2021:
            print(f"\nSUCCESS: Path Efficiency (63d) correctly identified 2017 ({eff_2017:.3f}) as more efficient than 2021 ({eff_2021:.3f}).")
        else:
            print(f"\nWARNING: Path Efficiency (63d) did not distinguish 2017 from 2021.")
            
        # Save
        struct_features.to_parquet("data/processed/EURUSD_structural_features.parquet")
        print("\nSaved to data/processed/EURUSD_structural_features.parquet")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
