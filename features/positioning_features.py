"""Positioning features — volume momentum as OI substitute.

Open Interest (OI) time-series data is not available through any of our
existing data pipelines (MT5, yfinance, FRED).  Yfinance provides a
current OI *snapshot* for futures tickers (GC, CL, ES, NQ) via
``Ticker.info["openInterest"]``, but no historical time series.

Volume is used as the best-available proxy for positioning activity:
- Rising volume confirms directional conviction (trend strength)
- Falling volume signals exhaustion / indecision
- Volume spiking relative to its moving average flags regime changes

Coverage
--------
- Volume momentum:  ALL 35 assets (MT5 tick_volume / yfinance Volume)
- OI time series:   NONE (flagged via ``oi_available: 0``)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.positioning_features")

_VOL_CLIP = 2.0
_VOL_MA_RATIO_CLIP = 5.0
_VOL_MIN_PERIODS = 5

# Futures tickers where yfinance provides an OI snapshot (not time series).
# Listed for documentation; OI momentum is not computable from snapshots.
_FUTURES_WITH_OI_SNAPSHOT = frozenset({"GC=F", "CL=F", "ES=F", "NQ=F"})


def compute_volume_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute volume momentum features from OHLCV data.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        Must contain a ``volume`` column.  Columns: open, high, low, close, volume.

    Returns
    -------
    pd.DataFrame
        Three columns indexed by *ohlcv*'s index:
        - ``vol_5d_chg``: 5-day log change in volume, clipped to [-2, 2]
        - ``vol_21d_chg``: 21-day log change in volume, clipped to [-2, 2]
        - ``vol_ma_ratio``: volume / 21d rolling mean volume, clipped to [0, 5]
          Values > 1.5 = volume spike; < 0.5 = volume drought.

    Notes
    -----
    - Log changes are used because volume distributions are log-normal.
    - Volume of 0 is replaced with NaN to avoid division by zero.
    - All values are clipped to bound outlier influence.
    - No leakage: rolling windows end at the current bar.
    """
    if ohlcv is None or ohlcv.empty or "volume" not in ohlcv.columns:
        return pd.DataFrame(index=getattr(ohlcv, "index", None) if ohlcv is not None else None)

    volume = ohlcv["volume"].replace(0, np.nan).astype(float)

    # yfinance returns volume=0 for forex pairs — volume momentum is
    # meaningless in that case.  Return empty to avoid NaN contamination.
    if volume.isna().all():
        return pd.DataFrame(index=ohlcv.index)
    log_vol = np.log(volume.clip(lower=1e-10))

    chg_5d = (log_vol - log_vol.shift(5)).clip(-_VOL_CLIP, _VOL_CLIP)
    chg_21d = (log_vol - log_vol.shift(21)).clip(-_VOL_CLIP, _VOL_CLIP)

    vol_ma = volume.rolling(21, min_periods=_VOL_MIN_PERIODS).mean()
    ratio = (volume / vol_ma.replace(0, np.nan)).clip(0, _VOL_MA_RATIO_CLIP)

    return pd.DataFrame(
        {
            "vol_5d_chg": chg_5d,
            "vol_21d_chg": chg_21d,
            "vol_ma_ratio": ratio,
        },
        index=ohlcv.index,
    )


def check_oi_availability(ticker: str) -> int:
    """Return 1 if clean OI time-series data is available for *ticker*.

    Currently returns 0 for all tickers because:
    - MT5 does not expose Open Interest (only tick_volume)
    - yfinance historical data does not include Open Interest
    - yfinance ``Ticker.info`` has an OI snapshot for futures (GC, CL, ES, NQ)
      but this is a single current value, not a time series
    - FRED does not provide OI data

    Returns
    -------
    int
        0 for all tickers — OI time series not available.
    """
    _ = ticker  # unused — kept for forward compatibility
    return 0
