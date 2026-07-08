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
    """

    def hurst_calc(z):
        # Use a subset of lags for stability
        lags = np.array([2, 4, 8, 16, 32])
        lags = lags[lags < len(z) // 2]
        if len(lags) < 3:
            return 0.5

        tau = [np.std(np.subtract(z[lag:], z[:-lag])) for lag in lags]
        tau = np.array(tau)

        # Filter zero/negative std to avoid log errors
        valid = tau > 0
        if not valid.any():
            return 0.5

        reg = np.polyfit(np.log(lags[valid]), np.log(tau[valid]), 1)
        return reg[0]

    return series.rolling(window=window).apply(hurst_calc, raw=True)


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

    # --- Temporal / Session Features ---
    # NOTE: This is a 1D daily-bar system. _normalize_index() in data_fetch.py
    # normalizes all timestamps to UTC midnight, making df.index.hour always 0.
    # utc_hour is a constant zero and provides no signal during training (the
    # model learns to ignore it). It is preserved for backward-compatible
    # feature count; models can be retrained to drop it.
    df["utc_hour"] = df.index.hour

    # Session Volatility Profile — daily resolution groups by day_of_week
    # instead of hour to capture weekday vol patterns
    df["hourly_vol"] = returns.rolling(window=24).std()
    df["session_vol_profile"] = (
        df.groupby(df.index.dayofweek)["hourly_vol"]
        .transform(lambda x: x / x.rolling(window=20, min_periods=5).mean())
        .fillna(1.0)
    )

    # --- Clean up ---
    feature_cols = ["hurst", "kaufman_er", "adx", "vol_zscore", "compression", "utc_hour", "session_vol_profile"]

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
