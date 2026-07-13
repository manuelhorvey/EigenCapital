"""Group 3 — Rates & carry features.

Yield curve slope, carry differential momentum, real rate momentum,
and breakeven inflation momentum.

Data Sources
------------
- Yield curve slope: ``^TNX`` (10Y) and ``^IRX`` (3M) or ``^2YR`` (2Y)
  from the macro batch (yfinance primary, FRED fallback).
- Carry differential: ``rate_diff`` computed per-asset in ``fetch_asset_data``
  (base yield - quote yield).
- Real rate: ``^TIPS10Y`` (TIPS 10Y real yield) from FRED via DFII10.
- Breakeven inflation: ``^BREKEVEN10Y`` (10Y breakeven) from FRED via T10YIE.

All yield tickers are already normalized to decimal (percent / 100) in
the data_fetch pipeline.

Coverage
--------
- Yield curve slope:  ALL assets (US rates are shared).
- Carry diff momentum: ALL 22 assets (all have rate_diffs; BTC/GC/etc. use 0).
- TIPS real rate:     ALL assets (US TIPS are shared).
- Breakeven:          ALL assets (US breakeven is shared).
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("eigencapital.rates_features")


def compute_yield_slope(
    tnx: pd.Series,
    irx: pd.Series,
) -> pd.DataFrame:
    """Compute yield curve slope (10Y - 3M) and its momentum.

    Parameters
    ----------
    tnx : pd.Series
        10-year Treasury yield in decimal (e.g. 0.045 = 4.5%).
    irx : pd.Series
        3-month T-bill yield in decimal.

    Returns
    -------
    pd.DataFrame
        Columns:
        - ``yield_slope``: 10Y - 3M spread (in decimal, e.g. 0.02 = 200bp)
        - ``yield_slope_5d_chg``: 5-day change of the slope
        - ``yield_slope_21d_chg``: 21-day change of the slope

    Notes
    -----
    A steepening yield curve (slope rising) historically precedes
    improving economic conditions; a flattening/inverted curve
    precedes recessions.  Momentum captures the rate of change.
    """
    slope = (tnx - irx).reindex(tnx.index)
    result = pd.DataFrame({"yield_slope": slope}, index=tnx.index)
    result["yield_slope_5d_chg"] = slope.diff(5)
    result["yield_slope_21d_chg"] = slope.diff(21)
    return result


def compute_carry_momentum(
    rate_diffs: pd.Series,
    index: pd.Index,
) -> pd.DataFrame:
    """Compute cross-asset carry differential momentum.

    Parameters
    ----------
    rate_diffs : pd.Series
        Rate differential for this asset: base_yield - quote_yield (decimal).
    index : pd.Index
        Target index for alignment.

    Returns
    -------
    pd.DataFrame
        Columns:
        - ``rate_diff_5d_chg``: 5-day change of the rate differential
        - ``rate_diff_21d_chg``: 21-day change of the rate differential

    Notes
    -----
    Carry differential momentum captures shifts in the interest rate
    advantage between two currencies.  Rising rate_diff = widening
    yield advantage for the base currency.
    """
    rd = rate_diffs.reindex(index)
    return pd.DataFrame(
        {
            "rate_diff_5d_chg": rd.diff(5),
            "rate_diff_21d_chg": rd.diff(21),
        },
        index=index,
    )


def compute_real_rate_features(
    tips: pd.Series,
) -> pd.DataFrame:
    """Compute TIPS real rate momentum.

    Parameters
    ----------
    tips : pd.Series
        TIPS 10-year real yield in decimal (FRED DFII10 / 100).

    Returns
    -------
    pd.DataFrame
        Columns:
        - ``real_rate_5d_chg``: 5-day change of TIPS real yield
        - ``real_rate_21d_chg``: 21-day change of TIPS real yield

    Notes
    -----
    Rising real yields indicate tighter monetary conditions.
    The 5d/21d momentum captures the speed of tightening/easing.
    """
    r = tips.reindex(tips.index)
    return pd.DataFrame(
        {
            "real_rate_5d_chg": r.diff(5),
            "real_rate_21d_chg": r.diff(21),
        },
        index=tips.index,
    )


def compute_breakeven_features(
    breakeven: pd.Series,
) -> pd.DataFrame:
    """Compute breakeven inflation momentum.

    Parameters
    ----------
    breakeven : pd.Series
        10-year breakeven inflation rate in decimal (FRED T10YIE / 100).

    Returns
    -------
    pd.DataFrame
        Columns:
        - ``breakeven_5d_chg``: 5-day change of breakeven inflation
        - ``breakeven_21d_chg``: 21-day change of breakeven inflation

    Notes
    -----
    Breakeven inflation = nominal 10Y yield - TIPS 10Y real yield.
    Rising breakeven = rising inflation expectations.
    """
    b = breakeven.reindex(breakeven.index)
    return pd.DataFrame(
        {
            "breakeven_5d_chg": b.diff(5),
            "breakeven_21d_chg": b.diff(21),
        },
        index=breakeven.index,
    )


def compute_all(
    macro: dict[str, pd.Series],
    rate_diffs: pd.Series,
    target_index: pd.Index,
) -> pd.DataFrame:
    """Convenience wrapper — compute all Group 3 features and align to target.

    Parameters
    ----------
    macro : dict[str, pd.Series]
        Macro data dict from the data_fetch pipeline.  Must contain
        ``^TNX``, ``^IRX``, ``^TIPS10Y``, ``^BREKEVEN10Y``.
    rate_diffs : pd.Series
        Rate differential Series for this asset.
    target_index : pd.Index
        Index to align all features to (typically ``features.index``).

    Returns
    -------
    pd.DataFrame
        All Group 3 columns aligned to *target_index*, NaN-filled.
        Returns an empty DataFrame if no macro data is available.
    """
    if not macro:
        carry = compute_carry_momentum(rate_diffs, target_index)
        return carry.fillna(0.0)

    parts: list[pd.DataFrame] = []

    tnx = macro.get("^TNX", pd.Series(dtype=float))
    irx = macro.get("^IRX", pd.Series(dtype=float))
    if not tnx.empty and not irx.empty:
        p = compute_yield_slope(tnx, irx)
        if p is not None and not p.empty:
            parts.append(p)

    tips = macro.get("^TIPS10Y", pd.Series(dtype=float))
    if not tips.empty:
        p = compute_real_rate_features(tips)
        if p is not None and not p.empty:
            parts.append(p)

    breakeven = macro.get("^BREKEVEN10Y", pd.Series(dtype=float))
    if not breakeven.empty:
        p = compute_breakeven_features(breakeven)
        if p is not None and not p.empty:
            parts.append(p)

    carry = compute_carry_momentum(rate_diffs, target_index)
    parts.append(carry)

    if not parts:
        return pd.DataFrame(index=target_index)

    # Normalise timezone awareness across all parts: yfinance macro data
    # returns tz-naive indexes while the training pipeline may produce a
    # tz-aware target_index (UTC).  Stripping tz avoids ``Cannot join
    # tz-naive with tz-aware DatetimeIndex``.
    target_clean = target_index.tz_localize(None) if getattr(target_index, "tz", None) is not None else target_index

    def _drop_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
        if getattr(idx, "tz", None) is not None:
            return idx.tz_localize(None)
        return idx

    parts = [p.set_axis(_drop_tz(p.index)) for p in parts]

    combined = pd.concat(parts, axis=1)
    combined = combined.reindex(target_clean).ffill()
    return combined.fillna(0.0)
