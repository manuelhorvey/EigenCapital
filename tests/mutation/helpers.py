"""Shared mutation injection helpers for temporal leakage tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_series(n: int = 300, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.005, n)
    return pd.Series(100.0 * np.exp(np.cumsum(steps)), name="close")


def synthetic_asset_data(
    n: int = 500, seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    close = pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(0, 0.005, n))),
        name="TEST",
    )
    idx = close.index
    prices = close.to_frame("TEST")
    rate_diffs = pd.DataFrame({"TEST": np.full(n, 0.02)}, index=idx)
    dxy = pd.Series(100.0 + np.cumsum(np.random.default_rng(seed + 1).normal(0, 0.003, n)), index=idx, name="dxy")
    vix = pd.Series(15.0 + abs(np.random.default_rng(seed + 2).normal(0, 2, n)), index=idx, name="vix")
    spx = pd.Series(3000.0 + np.cumsum(np.random.default_rng(seed + 3).normal(0, 5, n)), index=idx, name="spx")
    commodities = pd.DataFrame({"WTI": 50.0 + np.cumsum(np.random.default_rng(seed + 4).normal(0, 0.5, n))}, index=idx)
    return prices, rate_diffs, dxy, vix, spx, commodities


# ── Mutated feature functions (one per L-class) ────────────────────────────


def L1_future_index_momentum(price: pd.Series, horizon: int = 21) -> pd.Series:
    """Uses .shift(-1) — references future data (L1 violation)."""
    ret = np.log(price.astype(float) / price.astype(float).shift(-1))
    return ret.clip(-0.20, 0.20)


def L2_global_quantile_carry(price: pd.Series, rate_diff: pd.Series, vol_window: int = 21) -> pd.Series:
    """Global .quantile() on full series (L2 + L5 violation)."""
    from features.alpha_features import vol_adjusted_carry as _clean

    s = _clean(price, rate_diff, vol_window)
    lo, hi = s.quantile([0.05, 0.95])
    return s.clip(lo, hi)


def L3_global_ffill(series: pd.Series) -> pd.Series:
    """ffill on full series before any split (L3 violation)."""
    return series.ffill()


def L4_tz_stripping(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Strip timezone via .date conversion (L4 violation)."""
    return pd.to_datetime(index.date)


def L5_global_normalized_zscore(price: pd.Series, window: int = 20) -> pd.Series:
    """Z-score using global mean/std instead of rolling (L2+L5 violation)."""
    mu = price.mean()
    sigma = price.std()
    z = (price - mu) / sigma
    return z.clip(-3, 3)


_drift_counter: int = 0


def L6_schema_drift_features(
    prices: pd.DataFrame, rate_diffs: pd.DataFrame, **kwargs,
) -> pd.DataFrame:
    """Adds a random-suffix column name (L6 violation)."""
    global _drift_counter
    _drift_counter += 1
    from features.alpha_features import build_alpha_features

    df = build_alpha_features(prices, rate_diffs, **kwargs)
    df[f"drift_col_{_drift_counter}"] = 0.0
    return df


def L7_zero_division_feature(price: pd.Series) -> pd.Series:
    """Division by zero-vol without guard (L7 violation)."""
    log_ret = np.log(price.astype(float) / price.astype(float).shift(1))
    vol = log_ret.rolling(21).std()
    # INTENTIONAL BUG: no .replace(0, np.nan) before division
    return price / vol


def L8_nondeterministic_feature(price: pd.Series, seed: int) -> pd.Series:
    """Uses global RNG without explicit seed per call (L8 violation)."""
    noise = np.random.normal(0, 0.001, len(price))
    return price * (1.0 + noise)
