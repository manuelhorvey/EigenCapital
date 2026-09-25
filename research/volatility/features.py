"""Volatility feature measurement — descriptive research layer.

Volatility Taxonomy & Trade-Path research (docs/research/VOLATILITY_TAXONOMY_RESEARCH.md).

DESCRIPTIVE INFRASTRUCTURE ONLY:
- consumes the frozen data/mt5 D1 snapshot (R5_data_manifest.json, verified)
- reuses the canonical volatility conventions from
  ``eigencapital.features.base.volatility`` (realized vol on log returns,
  annualized x sqrt(252)) and is conformance-tested against them
- computes NO signal, NO alpha, NO production rule.

All estimators are point-in-time-safe: each function operates on a history
window ending at the evaluation bar and never uses bars after it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Sequence

import numpy as np
import pandas as pd

TRADING_DAYS = 252  # canonical annualization (features/base/volatility.py)

# Realized-volatility lookbacks (trading days), canonical RV horizon set.
RV_HORIZONS: Dict[str, int] = {"RV_5": 5, "RV_10": 10, "RV_20": 20, "RV_60": 60}


# ─────────────────────────────────────────────────────────────────────────────
# Data integrity (DATA_CONTRACT.md gates, exclusion-not-imputation)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IntegrityReport:
    """Per-asset data-integrity summary over the frozen snapshot."""

    instrument: str
    rows: int
    duplicate_timestamps: int
    non_chronological: int
    ohlc_violations: int
    nonpositive_prices: int
    missing_values: int
    max_gap_days: float
    first_ts: str
    last_ts: str
    excluded_bars: int

    def to_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


def check_integrity(df: pd.DataFrame, instrument: str) -> IntegrityReport:
    """Structural integrity gates per docs/DATA_CONTRACT.md.

    Violations are COUNTED, never imputed or silently repaired. Rows flagged
    INVALID are excluded downstream and counted in ``excluded_bars``.
    """
    n = len(df)
    dup = int(df.index.duplicated().sum())
    non_chrono = int((df.index.to_series().diff() < pd.Timedelta(0)).sum())
    ohlc_bad = int(
        ((df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))).sum()
    )
    nonpos = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    missing = int(df[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    gaps = df.index.to_series().diff().dt.total_seconds().dropna() / 86400.0
    max_gap = float(gaps.max()) if len(gaps) else 0.0
    invalid = df.index[df.index.duplicated()]
    invalid = invalid.union(
        df.index[(df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))]
    )
    invalid = invalid.union(df.index[(df[["open", "high", "low", "close"]] <= 0).any(axis=1)])
    invalid = invalid.union(df.index[df[["open", "high", "low", "close"]].isna().any(axis=1)])
    return IntegrityReport(
        instrument=instrument,
        rows=n,
        duplicate_timestamps=dup,
        non_chronological=non_chrono,
        ohlc_violations=ohlc_bad,
        nonpositive_prices=nonpos,
        missing_values=missing,
        max_gap_days=max_gap,
        first_ts=str(df.index[0]),
        last_ts=str(df.index[-1]),
        excluded_bars=int(len(invalid)),
    )


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Exclude INVALID rows (counted by check_integrity); no imputation."""
    ok = ~(
        df.index.duplicated(False)
        | (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | df[["open", "high", "low", "close"]].isna().any(axis=1)
    )
    return df.loc[ok].copy()


# ─────────────────────────────────────────────────────────────────────────────
# Core estimators (conventions of features/base/volatility.py)
# ─────────────────────────────────────────────────────────────────────────────


def log_returns(close: pd.Series) -> pd.Series:
    """Close-to-close log returns (canonical estimator input)."""
    c = close.astype(float)
    return np.log(c / c.shift(1)).iloc[1:]


def realized_vol(close: pd.Series, lookback: int) -> pd.Series:
    """Annualized realized volatility from close-to-close log returns.

    Conformance: identical statistic to
    ``eigencapital.features.base.volatility.compute_realized_volatility``
    (sample std of the last ``lookback`` log returns x sqrt(252)), evaluated
    as a rolling window ending at each bar (point-in-time).
    """
    r = log_returns(close)
    return r.rolling(lookback).std(ddof=1) * math.sqrt(TRADING_DAYS)


def returns_panel(closes: pd.DataFrame) -> pd.DataFrame:
    """Close-to-close simple returns, column-wise (shared convention)."""
    return closes.astype(float).pct_change(fill_method=None)


def abs_returns_panel(closes: pd.DataFrame) -> pd.DataFrame:
    """|simple return| panel (clustering-persistence input)."""
    return returns_panel(closes).abs()


def parkinson_vol(high: pd.Series, low: pd.Series, lookback: int) -> pd.Series:
    """Annualized Parkinson (1980) high-low range volatility (rolling)."""
    hl2 = (np.log(high.astype(float) / low.astype(float)) ** 2).rolling(lookback).sum()
    return np.sqrt(hl2 / (4.0 * lookback * math.log(2))) * math.sqrt(TRADING_DAYS)


def garman_klass_vol(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> pd.Series:
    """Annualized Garman-Klass (1980) OHLC volatility (rolling)."""
    lh2 = (np.log(high.astype(float) / low.astype(float)) ** 2).rolling(lookback).sum()
    co2 = (np.log(close.astype(float) / open_.astype(float)) ** 2).rolling(lookback).sum()
    var = 0.5 * lh2 / lookback - (2.0 * math.log(2) - 1.0) * co2 / lookback
    return np.sqrt(var.clip(lower=0.0)) * math.sqrt(TRADING_DAYS)


def atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 14) -> pd.Series:
    """ATR (Wilder-smoothed true range) divided by close — dimensionless.

    True range matches ``eigencapital.features.base.ranges.compute_true_range``.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / lookback, adjust=False, min_periods=lookback).mean()
    return atr / close.astype(float)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence, vol-of-vol, tails, jumps
# ─────────────────────────────────────────────────────────────────────────────


def autocorr(series: pd.Series, lags: Sequence[int]) -> Dict[int, float]:
    """Autocorrelation at each lag (NaN-skipping, min 30 observations)."""
    out: Dict[int, float] = {}
    s = series.dropna()
    for lag in lags:
        if len(s) <= lag + 30:
            out[int(lag)] = float("nan")
            continue
        a, b = s.iloc[lag:].to_numpy(), s.iloc[:-lag].to_numpy()
        if a.std() < 1e-15 or b.std() < 1e-15:
            out[int(lag)] = float("nan")
        else:
            out[int(lag)] = float(np.corrcoef(a, b)[0, 1])
    return out


def vol_of_vol(rv20: pd.Series) -> Dict[str, float]:
    """Volatility-of-volatility: std and CV of RV_20 (documented definitions)."""
    s = rv20.dropna()
    if len(s) < 30:
        return {"vol_of_vol_std": float("nan"), "vol_of_vol_cv": float("nan")}
    std = float(s.std(ddof=1))
    mean = float(s.mean())
    return {"vol_of_vol_std": std, "vol_of_vol_cv": (std / mean) if mean > 1e-15 else float("nan")}


def rv_change_stats(rv20: pd.Series, horizon: int = 21) -> Dict[str, float]:
    """Rolling change in RV: std of 21-day RV diff (acceleration proxy)."""
    d = rv20.diff(horizon).dropna()
    return {"rv_change_std": float(d.std(ddof=1)) if len(d) >= 30 else float("nan")}


def estimator_dispersion(rv: pd.Series, pk: pd.Series, gk: pd.Series) -> Dict[str, float]:
    """Cross-estimator dispersion: mean absolute pairwise log-ratio."""
    df = pd.concat([rv, pk, gk], axis=1).dropna()
    df.columns = ["rv", "pk", "gk"]
    df = df[(df > 1e-12).all(axis=1)]
    if len(df) < 30:
        return {"estimator_dispersion": float("nan")}
    lr = np.abs(np.log(df["pk"] / df["rv"])) + np.abs(np.log(df["gk"] / df["rv"])) + np.abs(np.log(df["gk"] / df["pk"]))
    return {"estimator_dispersion": float(lr.mean() / 3.0)}


def tail_stats(returns: pd.Series) -> Dict[str, float]:
    """Skew, excess kurtosis, tail quantiles, extreme-event frequency.

    Definitions (fixed ex-ante):
    - extreme frequency: |r| > 3 sigma_1y (sigma_1y = std x sqrt(252)) —
      i.e. a 3-sigma daily move under the asset's own unconditional scale.
    """
    r = returns.dropna()
    if len(r) < 100:
        return {
            k: float("nan")
            for k in (
                "skew",
                "excess_kurtosis",
                "q01",
                "q99",
                "downside_q05",
                "upside_q95",
                "extreme_freq_3sigma",
                "downside_extreme_freq",
                "upside_extreme_freq",
            )
        }
    sigma = float(r.std(ddof=1))
    thr = 3.0 * sigma
    return {
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurtosis()),
        "q01": float(r.quantile(0.01)),
        "q99": float(r.quantile(0.99)),
        "downside_q05": float(r.quantile(0.05)),
        "upside_q95": float(r.quantile(0.95)),
        "extreme_freq_3sigma": float((r.abs() > thr).mean()),
        "downside_extreme_freq": float((r < -thr).mean()),
        "upside_extreme_freq": float((r > thr).mean()),
    }


def jump_proxies(returns: pd.Series, rv20: pd.Series, k: float = 3.0) -> Dict[str, float]:
    """Jump PROXIES (not true jumps — no bipower/realized-jump identification).

    Definitions (fixed ex-ante):
    - jump_freq: fraction of days with |r| > k x RV_20_daily
      (RV_20_daily = RV_20_annualized / sqrt(252))
    - mean_jump_ratio: mean of |r| / RV_20_daily
    - rv_spike_freq: fraction of days RV_20 > 1.5 x its trailing 63-day median
    """
    daily_vol = rv20 / math.sqrt(TRADING_DAYS)
    ratio = (returns.abs() / daily_vol).replace([np.inf, -np.inf], np.nan).dropna()
    spike = (rv20 > 1.5 * rv20.rolling(63).median()).dropna()
    return {
        "jump_proxy_k": k,
        "jump_freq": float((ratio > k).mean()) if len(ratio) >= 100 else float("nan"),
        "mean_jump_ratio": float(ratio.mean()) if len(ratio) >= 100 else float("nan"),
        "rv_spike_freq": float(spike.mean()) if len(spike) >= 100 else float("nan"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-asset assembly
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AssetVolSeries:
    """Per-asset volatility measurement series (all point-in-time)."""

    instrument: str
    asset_class: str
    bars: pd.DataFrame  # cleaned OHLC, chronological index
    returns: pd.Series
    rv: Dict[int, pd.Series] = field(default_factory=dict)  # lookback -> series
    rv20: pd.Series = None  # type: ignore[assignment]
    pk20: pd.Series = None  # type: ignore[assignment]
    gk20: pd.Series = None  # type: ignore[assignment]
    atr14_pct: pd.Series = None  # type: ignore[assignment]
    integrity: IntegrityReport = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for lb in RV_HORIZONS.values():
            self.rv[lb] = realized_vol(self.bars["close"], lb)
        self.rv20 = self.rv[20]
        self.pk20 = parkinson_vol(self.bars["high"], self.bars["low"], 20)
        self.gk20 = garman_klass_vol(self.bars["open"], self.bars["high"], self.bars["low"], self.bars["close"], 20)
        self.atr14_pct = atr_pct(self.bars["high"], self.bars["low"], self.bars["close"], 14)


def summarize_series(a: AssetVolSeries) -> Dict[str, float]:
    """Asset-level volatility summary statistics (report table 51 input)."""
    rv20 = a.rv20.dropna()
    mean_rv = float(rv20.mean()) if len(rv20) else float("nan")
    std_rv = float(rv20.std(ddof=1)) if len(rv20) >= 2 else float("nan")
    persistence = autocorr(a.rv20, [1, 5, 21])
    absr_ac = autocorr(a.returns.abs(), [1, 5])
    sq_ac = autocorr(a.returns**2, [1, 5])
    out: Dict[str, float] = {
        "mean_rv20": mean_rv,
        "median_rv20": float(rv20.median()) if len(rv20) else float("nan"),
        "rv20_std": std_rv,
        "rv20_cv": (std_rv / mean_rv) if mean_rv and mean_rv > 1e-15 and not math.isnan(std_rv) else float("nan"),
        "rv_ac_lag1": persistence[1],
        "rv_ac_lag5": persistence[5],
        "rv_ac_lag21": persistence[21],
        "absret_ac_lag1": absr_ac[1],
        "absret_ac_lag5": absr_ac[5],
        "sqret_ac_lag1": sq_ac[1],
        "pk20_mean": float(a.pk20.dropna().mean()) if a.pk20.notna().sum() else float("nan"),
        "gk20_mean": float(a.gk20.dropna().mean()) if a.gk20.notna().sum() else float("nan"),
        "atr14_pct_mean": float(a.atr14_pct.dropna().mean()) if a.atr14_pct.notna().sum() else float("nan"),
    }
    out.update(vol_of_vol(a.rv20))
    out.update(rv_change_stats(a.rv20, 21))
    out.update(estimator_dispersion(a.rv20, a.pk20, a.gk20))
    out.update(tail_stats(a.returns))
    out.update(jump_proxies(a.returns, a.rv20))
    return out


def build_asset_series(instrument: str, asset_class: str, df: pd.DataFrame) -> AssetVolSeries:
    """Clean, verify and measure one asset's D1 history."""
    integrity = check_integrity(df, instrument)
    bars = clean_bars(df)
    rets = log_returns(bars["close"])
    return AssetVolSeries(
        instrument=instrument,
        asset_class=asset_class,
        bars=bars,
        returns=rets,
        integrity=integrity,
    )
