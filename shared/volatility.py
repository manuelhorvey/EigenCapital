"""Frozen volatility primitive — single source of truth for all volatility estimation.

This module defines the single approved volatility primitive consumed by:
  - labels (triple-barrier barrier width)
  - execution geometry (SL/TP placement)
  - shadow replay (counterfactual evaluation)
  - attribution (volatility-derived metrics)

Architecture invariant::

    VolatilityPrimitive version → same formula, same smoothing,
    same fallback semantics, same edge-case behavior everywhere.

    ``vol. version`` is propagated into label artifacts,
    walk-forward summaries, execution snapshots, and attribution records
    for historical replay integrity when the primitive evolves later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.volatility")

VOLATILITY_PRIMITIVE_VERSION = "v1"

ATRMode = Literal["ohlc", "close_fallback"]


@dataclass(frozen=True)
class VolatilityPrimitive:
    """Frozen execution volatility contract.

    Attributes
    ----------
    method : str
        Always ``"atr"`` — not a free-form experimentation knob.
    period : int
        ATR lookback period (default 14).
    mode : ATRMode
        ``"ohlc"`` when high/low/close all available; ``"close_fallback"``
        otherwise.  Persisted so label-metadata reflects what was used.
    version : str
        Primitive version string for artifact traceability.
    """

    method: str = "atr"
    period: int = 14
    mode: ATRMode = "ohlc"
    version: str = VOLATILITY_PRIMITIVE_VERSION

    @classmethod
    def detect(cls, df: pd.DataFrame, period: int = 14) -> VolatilityPrimitive:
        """Auto-detect mode based on available columns."""
        has_ohlc = {"high", "low"}.issubset(df.columns)
        return cls(period=period, mode="ohlc" if has_ohlc else "close_fallback")


# ── Public API ────────────────────────────────────────────────────────────


def compute_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute average true range series.

    Primary path: true range from ``high`` / ``low`` / ``close`` columns.
    Fallback path:  close-to-close absolute change (same approximation used
    by the live execution engine).

    Returns a Series with the same index as *df*, zero-filled for the first
    ``period`` rows.
    """
    if {"high", "low"}.issubset(df.columns):
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
    else:
        # Fallback: close-only approximation matching DynamicSLTPEngine
        close = df["close"].astype(float)
        tr = close.diff().abs()

    atr = tr.rolling(period, min_periods=1).mean()
    return atr


def compute_atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as a fraction of close price.

    Used as the volatility estimate for barrier placement in both
    triple-barrier labeling and live SL/TP geometry.
    """
    atr = compute_atr_series(df, period)
    close = df["close"].astype(float)
    return atr / close.replace(0, np.nan)


def compute_latest_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return the single most recent ATR value (scalar).

    Guaranteed positive.  Returns 0.01 as a last-resort floor.
    """
    atr = compute_atr_series(df, period)
    val = float(atr.iloc[-1]) if not atr.empty else 0.01
    return max(val, 0.01)


def compute_latest_atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """Return the most recent ATR/close ratio (scalar)."""
    atr = compute_latest_atr(df, period)
    close = float(df["close"].iloc[-1]) if not df.empty else 1.0
    return max(atr / max(close, 1e-9), 1e-9)


def estimate_gap_risk(df: pd.DataFrame, window: int = 20) -> float:
    """Estimate the expected overnight / weekend gap in price units.

    Used by the execution engine to widen SL distance and by attribution
    to explain gap-through stop-outs.
    """
    if len(df) < 5:
        return 0.0
    gaps = abs(df["close"].pct_change().shift(-1))
    mean_gap_pct = float(gaps.rolling(window).mean().iloc[-1]) if len(gaps) >= window else float(gaps.mean())
    if pd.isna(mean_gap_pct):
        return 0.0
    return mean_gap_pct * float(df["close"].iloc[-1])


def estimate_ewm_vol(close: pd.Series, span: int = 100) -> float:
    """EWM volatility estimate (legacy — kept for backward compatibility)."""
    returns = np.log(close.astype(float) / close.astype(float).shift(1))
    vol = returns.ewm(span=span).std()
    val = float(vol.iloc[-1]) if not vol.empty else 0.01
    return max(val, 0.01)
