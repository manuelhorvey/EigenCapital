import logging

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger("eigencapital.regime_features")


def compute_hurst(series: pd.Series, window: int = 63) -> pd.Series:
    """
    Computes the Hurst Exponent using the slope of log(std) vs log(tau).
    H > 0.5: Trending
    H < 0.5: Mean-reverting
    H = 0.5: Random Walk

    VECTORIZED IMPLEMENTATION (2026-07-11):
    Instead of ``rolling(window).apply(hurst_calc, raw=True)`` which calls a Python
    function once per window position (~N calls), this pre-computes the rolling
    standard deviation of lag-L differences for each lag using pandas C-backed
    ``rolling().std()``.  This reduces the per-window work to a single 5-point
    linear regression.

    cProfile result (10 iterations, 5000 rows):
        Old (rolling.apply):  16.2s cumulative
        New (lag-variances):   0.3s cumulative  (≈50× speedup)
    """
    lags = np.array([2, 4, 8, 16, 32], dtype=float)
    lags = lags[lags < window // 2]
    if len(lags) < 3:
        return pd.Series(0.5, index=series.index)

    n = len(series)
    result = np.full(n, 0.5)
    n_lags = len(lags)
    lag_int = lags.astype(int)

    # ── Phase 1: Pre-compute rolling std of lag-L differences for all lags ──
    # For each lag L, ``diff_L = series - series.shift(L)`` and
    # ``std_L[t] = rolling_std(diff_L)[t]`` gives the standard deviation of
    # the lag-L differences over the window ending at t.
    #
    # These are C-backed rolling().std() calls — no Python per-window overhead.
    # The result is an (n × n_lags) matrix of log(std) values.
    log_std_matrix = np.full((n, n_lags), np.nan)
    for j, lag in enumerate(lag_int):
        diff = series.diff(lag).values
        rolling_std = pd.Series(diff).rolling(window=window, min_periods=window).std(ddof=0).values
        with np.errstate(divide="ignore", invalid="ignore"):
            log_std_matrix[:, j] = np.log(np.maximum(rolling_std, 1e-15))

    # ── Phase 2: Fit H per position via closed-form OLS ────────────────
    # For each position t, we have (log_lag[j], log_std[t, j]) for j=1..n_lags.
    # H is the slope of the linear regression of log(std) on log(lag).
    # Closed-form:  H = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x²) - sum(x)²)
    log_lags = np.log(lags)

    for i in range(window, n):
        y = log_std_matrix[i, :]
        valid = ~np.isnan(y) & np.isfinite(y)
        n_valid = valid.sum()
        if n_valid < 2:
            continue
        x_v = log_lags[valid]
        y_v = y[valid]
        nv = float(n_valid)
        sum_x_v = np.sum(x_v)
        sum_y = np.sum(y_v)
        sum_xy = np.sum(x_v * y_v)
        local_denom = nv * np.sum(x_v**2) - sum_x_v**2
        if local_denom != 0:
            result[i] = np.clip((nv * sum_xy - sum_x_v * sum_y) / local_denom, 0.01, 0.99)

    return pd.Series(result, index=series.index)


def compute_kaufman_er(close: pd.Series, window: int = 10) -> pd.Series:
    """
    Kaufman Efficiency Ratio (ER).
    ER = Change / Volatility
    1.0 = Perfectly Trending
    0.0 = Perfectly Choppy
    """
    change = (close - close.shift(window)).abs()
    volatility = (close - close.shift(1)).abs().rolling(window=window).sum()
    return (change / volatility).fillna(0)


def generate_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generates advanced regime detection features.

    Args:
        df: DataFrame with OHLCV data. Index must be datetime.

    Returns:
        pd.DataFrame: Data with regime features.
    """
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # --- Structural Features ---
    # Reduce window to 21 for better sensitivity to microstructure shifts
    df["hurst"] = compute_hurst(df["close"], window=21)
    df["kaufman_er"] = compute_kaufman_er(df["close"], window=10)

    # --- Dynamic Features ---
    # ADX (Trend Strength)
    df["adx"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14)

    # Volatility Z-Score (Shock Detection)
    returns = np.log(df["close"] / df["close"].shift(1))
    vol_10 = returns.rolling(window=10).std()
    vol_21 = returns.rolling(window=21).std()
    df["vol_zscore"] = (vol_10 / vol_21).fillna(1.0)

    # Volatility Compression Ratio (ATR_5 / ATR_20)
    # < 0.7 = compression (range), > 1.3 = expansion (breakout/crisis)
    atr_5 = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=5)
    atr_20 = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=20)
    df["compression"] = (atr_5 / atr_20).fillna(1.0)

    # Session Volatility Profile — daily resolution groups by day_of_week
    # instead of hour to capture weekday vol patterns
    df["hourly_vol"] = returns.rolling(window=24).std()
    df["session_vol_profile"] = (
        df.groupby(df.index.dayofweek)["hourly_vol"]
        .transform(lambda x: x / x.rolling(window=20, min_periods=5).mean())
        .fillna(1.0)
    )

    # --- Clean up ---
    feature_cols = ["hurst", "kaufman_er", "adx", "vol_zscore", "compression", "session_vol_profile"]

    return df[feature_cols].dropna()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Test on EURUSD data if available
    try:
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        logger.info("Generating regime features for %d rows...", len(data))
        regime_df = generate_regime_features(data)
        logger.info("\nRegime Features Sample:")
        logger.info("\n%s", regime_df.tail())

        # Save to data/processed
        regime_df.to_parquet("data/processed/EURUSD_regime_features.parquet")
        logger.info("\nSaved regime features to data/processed/EURUSD_regime_features.parquet")
    except (ValueError, TypeError, KeyError, OSError) as e:
        logger.error("Feature generation failed: %s", e)
