"""Pair Estimation — pure statistical primitives for the R4-MR pipeline.

R4 Phase B1 (docs/research/R4_MEAN_REVERSION.md, frozen contract). Every
function here is PIT-neutral: it operates on the window it is GIVEN. The
pipeline (pipeline.py) is solely responsible for slicing windows that end
strictly before the decision bar (contract item 3 — no exception path).

All estimation uses LOG PRICES (contract item 2). No threshold search, no
method selection: statsmodels `adfuller` / `coint` / OLS are reused unchanged
(R4-A verification table). Rejected estimation inputs raise EstimationError —
degenerate statistics are never silently returned.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint


class EstimationError(ValueError):
    """Raised for degenerate estimation inputs — never silently swallowed."""


MIN_WINDOW = 60  # honest minimum for any estimation this module performs


def _require_series(name: str, series: pd.Series, min_len: int, positive: bool = False) -> pd.Series:
    """Validate an input series.

    NOTE on `positive`: inputs to this module are LOG prices (contract item
    2), which are real numbers of any sign — positivity is NOT an invariant
    here (log(0.6) < 0 for FX pairs). The pre-log positivity check belongs
    to the data loader (run_r4_b1_pairs._load_log_prices), which enforces
    it before np.log. `positive=True` remains available for any future
    raw-price primitive.
    """
    if len(series) < min_len:
        raise EstimationError(f"{name}: need ≥ {min_len} bars, got {len(series)}")
    values = series.to_numpy(dtype=float)
    if not np.all(np.isfinite(values)):
        raise EstimationError(f"{name}: non-finite values present")
    if positive and np.any(values <= 0.0):
        raise EstimationError(f"{name}: non-positive raw prices present (raw-price basis requires > 0)")
    return series


def adf_pvalue(log_prices: pd.Series) -> float:
    """Gate 1 — ADF on LOG PRICE LEVELS (contract item 2), two-sided p.

    H0 of ADF is a unit root; p < 0.05 rejects a unit root in favor of
    stationarity of the log-price level.
    """
    _require_series("adf", log_prices, MIN_WINDOW)
    stat, pvalue, *_ = adfuller(log_prices.to_numpy(dtype=float), autolag="AIC")
    del stat
    return float(pvalue)


def coint_pvalue(log_a: pd.Series, log_b: pd.Series) -> float:
    """Gate 2 — Engle-Granger cointegration p-value (statsmodels `coint`).

    H0: no cointegration; p < 0.05 rejects in favor of a cointegrating
    relationship between the two log-price levels.
    """
    _require_series("coint_a", log_a, MIN_WINDOW)
    _require_series("coint_b", log_b, MIN_WINDOW)
    if len(log_a) != len(log_b):
        raise EstimationError("coint: series length mismatch")
    _, pvalue, _ = coint(log_a.to_numpy(dtype=float), log_b.to_numpy(dtype=float))
    return float(pvalue)


def hedge_ratio(log_a: pd.Series, log_b: pd.Series) -> Tuple[float, float]:
    """OLS hedge ratio β and intercept from statsmodels-quality lstsq (log basis).

    spread = log(A) − β·log(B) − α. Returns (beta, alpha).
    """
    _require_series("hedge_a", log_a, MIN_WINDOW)
    _require_series("hedge_b", log_b, MIN_WINDOW)
    x = log_b.to_numpy(dtype=float)
    y = log_a.to_numpy(dtype=float)
    if float(np.std(x)) < 1e-12:
        raise EstimationError("hedge: constant regressor (zero-variance leg) — degenerate fit")
    design = np.column_stack([x, np.ones_like(x)])
    beta, alpha = np.linalg.lstsq(design, y, rcond=None)[0]
    if not (math.isfinite(beta) and math.isfinite(alpha)):
        raise EstimationError("hedge: non-finite OLS solution")
    return float(beta), float(alpha)


def spread_from(log_a: pd.Series, log_b: pd.Series, beta: float, alpha: float) -> pd.Series:
    """Spread in log space: log(A) − β·log(B) − α (frozen construction)."""
    return log_a - beta * log_b - alpha


def half_life(spread: pd.Series) -> float | None:
    """Gate 3 — AR(1) half-life of mean reversion, in bars.

    Fits Δs_t = b·s_{t−1} (+ intercept). b ≥ 0 ⇒ no mean reversion ⇒ None
    (the caller treats None as a failed gate — never a manufactured number).
    Otherwise HL = −ln(2)/b.
    """
    _require_series("half_life", spread, MIN_WINDOW, positive=False)
    s = spread.to_numpy(dtype=float)
    s_prev, ds = s[:-1], np.diff(s)
    design = np.column_stack([s_prev, np.ones_like(s_prev)])
    b = np.linalg.lstsq(design, ds, rcond=None)[0][0]
    if not math.isfinite(b) or b >= -1e-12:
        return None
    hl = -math.log(2.0) / b
    if not math.isfinite(hl) or hl <= 0.0:
        return None
    return float(hl)


def rolling_zscore(spread: pd.Series, window: int = 60) -> pd.Series:
    """Rolling z-score of the spread (frozen 60-bar window, contract item 5)."""
    if window < 2:
        raise EstimationError(f"zscore window must be ≥ 2, got {window}")
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std(ddof=1)
    return (spread - mean) / std.where(std > 0.0)
