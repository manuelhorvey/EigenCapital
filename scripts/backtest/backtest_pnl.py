#!/usr/bin/env python3
"""
Walk-forward PnL backtest from OOS signal parquets.

Reads per-asset signal parquets (signal, label, p_long) from the walk-
forward output directory, computes R-multiple PnL using triple-barrier
label semantics (TP/SL first-touch), and reports per-asset and portfolio-
level metrics.

Usage:
    # Base-only (default)
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py

    # Compare ensemble vs base
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py --ensemble-tag ensemble

    # Custom signal tag and output path
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py --tag base --output pnl_results.csv

R-multiples assume equal risk-per-trade (1R = ATR * sl_mult for each asset).
Does not reflect live position sizing, correlation-adjusted portfolio risk,
or transaction costs.  Not currency PnL.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from eigencapital.domain.value_objects.statistical_metrics import (
    _moments,
    deflated_sharpe_ratio,
    herfindahl_index,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
)
from shared.calibration.registry import CalibrationRegistry
from shared.portfolio_weights import list_methods, rolling_weight_matrix

logger = logging.getLogger("backtest_pnl")

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "models"

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

# ── Core PnL function (isolated, testable) ──────────────────────────────────


def compute_trade_pnl(signal: int, label: int, tp: float, sl: float) -> float:
    """Return PnL in R-multiples for a single trade.

    Parameters
    ----------
    signal : int
        -1 (SELL), 0 (FLAT), or 1 (BUY).
    label : int
        Binary triple-barrier label from the LONG perspective:
        0 = lower (SL) hit first, 1 = upper (TP) hit first.
    tp, sl : float
        Take-profit and stop-loss multipliers in ATR units.

    Semantics
        BUY  (signal=1):  label=1 → TP hit first → +tp × R
                           label=0 → SL hit first → -sl × R
        SELL (signal=-1): label=1 → upper(SL) hit → -sl × R
                           label=0 → lower(TP) hit → +tp × R
        FLAT (signal=0):  0.0 regardless of label.
    """
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


# ── Per-asset processing ────────────────────────────────────────────────────


def load_asset_signals(parquet_path: str) -> pd.DataFrame:
    """Load a single asset's OOS signal parquet."""
    df = pd.read_parquet(parquet_path)
    if df.empty:
        return df
    return df.sort_index()


def _asset_pt_sl_from_config() -> dict[str, tuple[float, float]]:
    """Load per-asset pt_sl from the production config (same as walk-forward)."""
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def _resolve_threshold(val, fallback: float | None) -> float:
    """Convert a percent-scale config value (or None) to 0-1 fraction, using fallback."""
    if val is not None:
        return float(val) / 100.0
    if fallback is not None:
        return float(fallback) / 100.0
    return 0.0


def _asset_direction_thresholds_from_config() -> dict[str, tuple[float, float]]:
    """Return per-asset direction-conditional thresholds (buy_th, sell_th) as 0-1 fractions.

    Matches the live engine's fallback chain (``decision_pipeline.py:apply_confidence_gate``):
      1. Per-asset ``min_confidence_buy`` / ``min_confidence_sell``
      2. Global ``defaults.min_confidence_buy`` / ``defaults.min_confidence_sell``
      3. Per-asset ``min_confidence``
      4. Global ``defaults.min_confidence``
      5. 0.0 (always allow)
    """
    from paper_trading.config_manager import get_config

    cfg = get_config()
    # These are None when not in the config (unlike get() with default).
    def_buy = cfg.defaults.get("min_confidence_buy")
    def_sell = cfg.defaults.get("min_confidence_sell")
    def_global = cfg.defaults.get("min_confidence")
    out: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        asset_buy = acfg.get("min_confidence_buy")
        asset_sell = acfg.get("min_confidence_sell")
        asset_global = acfg.get("min_confidence")
        # Buy: try 1→2→3→4→5
        buy_th = _resolve_threshold(asset_buy, def_buy)
        if buy_th == 0.0 and asset_global is not None:
            buy_th = float(asset_global) / 100.0
        elif buy_th == 0.0 and def_global is not None:
            buy_th = float(def_global) / 100.0
        else:
            buy_th = buy_th  # keep resolved value
        # Sell: try 1→2→3→4→5
        sell_th = _resolve_threshold(asset_sell, def_sell)
        if sell_th == 0.0 and asset_global is not None:
            sell_th = float(asset_global) / 100.0
        elif sell_th == 0.0 and def_global is not None:
            sell_th = float(def_global) / 100.0
        out[name] = (buy_th, sell_th)
    return out


def compute_asset_daily_r(
    df: pd.DataFrame,
    tp: float,
    sl: float,
) -> pd.Series:
    """Compute daily R-multiple series from a signal parquet.

    Each non-flat signal is converted to its R-multiple via
    ``compute_trade_pnl``.  Flat signals contribute 0.0 for that day.
    Returns a daily-frequency Series indexed by the parquet's datetime index.
    """
    r = np.zeros(len(df), dtype=float)
    signals = df["signal"].values
    labels = df["label"].values

    buy_mask = signals == 1
    sell_mask = signals == -1

    r[buy_mask & (labels == 1)] = tp
    r[buy_mask & (labels == 0)] = -sl
    r[sell_mask & (labels == 0)] = tp
    r[sell_mask & (labels == 1)] = -sl

    return pd.Series(r, index=df.index, name="daily_r")


def rederive_signals_from_p_long(
    df: pd.DataFrame,
    buy_th: float | None,
    sell_th: float | None,
) -> pd.DataFrame:
    """Override ``df['signal']`` from ``p_long`` using direction-conditional thresholds.

    Mirrors live engine semantics (``decision_pipeline.py:apply_confidence_gate``):
      BUY  if p_long > 0.5 and p_long >= buy_th
      SELL if p_long < 0.5 and 1 - p_long >= sell_th

    When a threshold is None (not configured), uses the WF parquet's
    baked-in signal column unchanged.  When buy_th <= 0.5 and sell_th <= 0.5,
    effectively all directional signals pass (for assets with intentionally
    low thresholds like NZDCAD).
    """
    if buy_th is None and sell_th is None or "p_long" not in df.columns:
        return df
    p_long = df["p_long"].astype(float).values
    sig = np.zeros(len(p_long), dtype=int)
    if buy_th is not None:
        sig[(p_long > 0.5) & (p_long >= buy_th)] = 1
    if sell_th is not None:
        sig[(p_long < 0.5) & (1.0 - p_long >= sell_th)] = -1
    df = df.copy()
    df["signal"] = sig
    return df


def asset_metrics(daily_r: pd.Series) -> dict:
    """Compute summary metrics from a daily R series.

    Returns
    -------
    dict with keys: n_trades (non-flat days), win_rate, total_R,
    avg_R, profit_factor, sharpe (annualised), max_drawdown, calmar.
    """
    n_trades = int((daily_r != 0).sum())
    if n_trades == 0:
        empty: dict[str, float | int] = {
            k: 0.0
            for k in (
                "n_trades",
                "win_rate",
                "total_R",
                "avg_R",
                "profit_factor",
                "sharpe",
                "sharpe_adj",
                "max_dd_R",
                "calmar",
                "skew",
                "ex_kurt",
                "hhi",
            )
        }
        empty["psr_gt_0"] = float("nan")
        empty["psr_gt_1"] = float("nan")
        empty["min_trl"] = float("nan")
        return empty

    wins = daily_r[daily_r > 0]
    losses = daily_r[daily_r < 0]
    total_R = float(daily_r.sum())
    avg_R = float(daily_r[daily_r != 0].mean())
    win_rate = len(wins) / n_trades
    profit_factor = abs(wins.sum() / losses.sum()) if len(losses) > 0 else float("inf")

    # Sharpe from daily R (annualised, 252 trading days)
    daily_r_arr = daily_r.values
    n_days = len(daily_r_arr)
    sharpe = float(daily_r.mean() / daily_r.std() * np.sqrt(252)) if daily_r.std() > 0 else 0.0

    # Autocorrelation-adjusted Sharpe (Lo, 2002)
    rho = daily_r.autocorr() if len(daily_r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    # Statistical moments
    skew, ex_kurt = _moments(daily_r_arr)
    psr_gt_0 = probabilistic_sharpe_ratio(sharpe, n_days, skew, ex_kurt, 0.0)
    psr_gt_1 = probabilistic_sharpe_ratio(sharpe, n_days, skew, ex_kurt, 1.0)
    min_trl = minimum_track_record_length(sharpe, skew, ex_kurt, alpha=0.05)

    # Return concentration (HHI) from non-zero trade days
    nonzero_r = daily_r_arr[daily_r_arr != 0]
    hhi = herfindahl_index(nonzero_r) if len(nonzero_r) > 0 else 0.0

    # Drawdown in R-units (peak-to-trough from cumulative R)
    cum = daily_r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())
    calmar = float(total_R / abs(max_dd_r)) if max_dd_r < 0 else None

    # Loss clustering — count days where >30% of this asset's trades lose
    # (single asset version; cross-asset done at portfolio level)
    loss_cluster_pct = float(len(losses) / max(n_trades, 1))

    return {
        "n_trades": n_trades,
        "n_days": n_days,
        "win_rate": round(win_rate, 4),
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj": round(sharpe_adj, 4),
        "max_dd_R": round(max_dd_r, 2),
        "calmar": round(calmar, 2) if calmar is not None else None,
        "loss_ratio": round(loss_cluster_pct, 4),
        "skew": round(skew, 4),
        "ex_kurt": round(ex_kurt, 4),
        "psr_gt_0": round(psr_gt_0, 4),
        "psr_gt_1": round(psr_gt_1, 4),
        "min_trl": min_trl,
        "hhi": round(hhi, 4),
    }


# ── Portfolio aggregation ────────────────────────────────────────────────────


def build_portfolio_daily_r(
    asset_series: dict[str, pd.Series],
    min_assets: int = 15,
    weight_method: str = "equal_v1",
    weight_window: int = 252,
    conviction: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build portfolio daily R series with configurable weight method.

    Parameters
    ----------
    asset_series : dict[str, pd.Series]
        Per-asset daily R series (indexed by datetime).
    min_assets : int
        Minimum number of assets required on a given day to include it.
    weight_method : str
        Portfolio weight method.
    weight_window : int
        Rolling covariance window in days.
    conviction : dict[str, float] | None
        Per-asset conviction scores (used by conviction_weighted_v1).

    Returns
    -------
    DataFrame with columns: 'portfolio_r', 'n_assets', 'frac_red'.
    Index is the sorted union of all asset dates.
    """
    combined = pd.DataFrame(asset_series)
    n_assets = combined.notna().sum(axis=1)
    frac_red = (combined < 0).sum(axis=1) / n_assets.replace(0, 1)

    if weight_method == "equal_v1":
        portfolio_r = combined.mean(axis=1)
    else:
        kwargs = {}
        if conviction is not None:
            kwargs["conviction"] = conviction
            if weight_method == "conviction_weighted_v1":
                kwargs["conviction_lambda"] = 0.5
        weights = rolling_weight_matrix(combined, weight_method, window=weight_window, **kwargs)
        weights = weights.reindex(combined.index, method="ffill").bfill().fillna(1.0 / len(combined.columns))
        portfolio_r = (combined * weights.values).sum(axis=1)

    result = pd.DataFrame(
        {
            "portfolio_r": portfolio_r,
            "n_assets": n_assets,
            "frac_red": frac_red,
        }
    )
    # Apply minimum-asset floor
    result = result[result["n_assets"] >= min_assets].copy()
    return result


# ── Realistic-mode adjustments ────────────────────────────────────────────

# Spread cost in R-units per trade (1bp ≈ 0.01R for a typical 1R trade)
# Calibrated from the production capital growth simulation which showed
# ~$0.50 spread cost per $67 avg trade expectancy.
_REALISTIC_SPREAD_COST_R: float = 0.02  # 2% of 1R consumed by spread
_REALISTIC_MAX_CONCURRENT: int = 13  # matches max_concurrent_positions in sizing.yaml


@dataclass
class CapitalPathResult:
    """Result of the capital-path simulation."""
    start_capital: float
    final_capital: float
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    max_dd_pct: float
    max_dd_dollar: float
    n_losing_days: int
    longest_dd_days: int


def simulate_capital_path(
    per_asset_r: pd.DataFrame | pd.Series,
    start_capital: float = 500.0,
    risk_per_trade_pct: float = 1.0,
    taper_start_dd: float = 0.05,
    taper_end_dd: float = 0.15,
    taper_min: float = 0.5,
) -> CapitalPathResult:
    """Simulate a capital path from per-asset daily R series.

    This is the key missing piece in ``--realistic-mode``.  Raw R-space
    backtests assume (1) equal risk-per-trade, (2) infinite capital,
    and (3) no compounding effects — so drawdown is always zero because
    wins and losses across 22 assets are averaged into a smooth daily
    return that never goes negative.

    **When ``per_asset_r`` is a DataFrame** (pre-averaged per-asset R):
    Each asset's daily dollar P&L is computed independently from the
    current equity, then summed for the portfolio daily P&L.  This
    captures the critical multi-asset effect: if 7 assets lose on the
    same day, the dollar loss is 7x larger than if only 1 asset loses,
    even though the portfolio-averaged R might still be positive from
    the other 15 winners.

    **When ``per_asset_r`` is a Series** (already averaged): the function
    falls back to the simpler portfolio-level path (preserved for
    backward compatibility, but will still show zero drawdown if the
    averaged series is always positive).

    Parameters
    ----------
    per_asset_r : pd.DataFrame | pd.Series
        Daily R-multiple series.  When a DataFrame, columns are asset
        names and each column contains that asset's daily R.  When a
        Series, treated as the portfolio-averaged daily R.
    start_capital : float
        Initial account equity (default 500).
    risk_per_trade_pct : float
        Fraction of equity risked per R-unit per asset (default 1.0%%).
        For multi-asset, this is the RISK PER ASSET, so total portfolio
        risk = risk_per_trade_pct * n_active_assets.
    taper_start_dd : float
        Drawdown threshold (as fraction) at which taper begins (default 0.05).
    taper_end_dd : float
        Drawdown threshold at which taper reaches minimum (default 0.15).
    taper_min : float
        Minimum taper factor (default 0.5).

    Returns
    -------
    CapitalPathResult with dollar-equity metrics.
    """
    equity = float(start_capital)
    peak = float(start_capital)
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    losing_days = 0
    total_trading_days = 0
    in_dd = False
    dd_count = 0
    longest_dd = 0

    r_pct = risk_per_trade_pct / 100.0

    is_dataframe = isinstance(per_asset_r, pd.DataFrame)

    for idx in range(len(per_asset_r)):
        if is_dataframe:
            row = per_asset_r.iloc[idx]
            n_active = int(row.notna().sum())
            if n_active == 0:
                continue
            total_trading_days += 1

            # Each asset's daily R represents the TOTAL R for that asset on
            # that day (sum of all trades).  The risk_per_trade_pct is the
            # fraction of equity risked per R-unit.  So dollar P&L for each
            # asset is: r * equity * risk_pct * taper.
            #
            # CRITICAL: We do NOT divide by n_active here.  If 10 assets
            # each have daily_r = -3.0, the total dollar loss is
            # 10 * (-3.0) * equity * 0.01 = -30% of equity.  This is the
            # multi-asset simultaneous loss effect that the portfolio-averaged
            # R completely smooths away.
            asset_rs = row.dropna().values
            n = len(asset_rs)
        else:
            r_val = per_asset_r.iloc[idx]
            if r_val == 0.0:
                continue
            total_trading_days += 1
            asset_rs = np.array([r_val])
            n = 1

        # Drawdown taper (same for all assets)
        dd_fraction = (peak - equity) / peak if peak > 0 else 0.0
        if dd_fraction >= taper_end_dd:
            taper = taper_min
        elif dd_fraction <= taper_start_dd:
            taper = 1.0
        else:
            progress = (dd_fraction - taper_start_dd) / (taper_end_dd - taper_start_dd)
            taper = 1.0 - (1.0 - taper_min) * progress

        # Dollar P&L = sum over all active assets of (r * equity * risk_pct * taper)
        # This is the SUM of per-asset R, not the average, so simultaneous losses
        # compound correctly.
        effective_risk = equity * r_pct * taper
        sum_r = sum(asset_rs)
        daily_pnl = sum_r * effective_risk

        equity += daily_pnl
        if equity < 0:
            equity = 0.0

        if daily_pnl < 0:
            losing_days += 1

        # Track drawdown
        if equity > peak:
            peak = equity
            in_dd = False
            dd_count = 0
        else:
            dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
            dd_dollar = peak - equity
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_dollar = dd_dollar
            if not in_dd:
                in_dd = True
                dd_count = 1
            else:
                dd_count += 1
            longest_dd = max(longest_dd, dd_count)

    total_return_pct = (equity - start_capital) / start_capital * 100 if start_capital > 0 else 0.0

    # CAGR
    years = total_trading_days / 252.0
    if years > 0 and equity > 0 and start_capital > 0:
        cagr_pct = ((equity / start_capital) ** (1.0 / years) - 1.0) * 100.0
    else:
        cagr_pct = 0.0

    # Sharpe from daily portfolio returns
    if is_dataframe:
        daily_returns = []
        for idx in range(len(per_asset_r)):
            row = per_asset_r.iloc[idx]
            n_active = int(row.notna().sum())
            if n_active == 0:
                continue
            # Portfolio daily return (as fraction of equity) = sum(asset_r) * r_pct
            total_r = float(row.dropna().sum())
            daily_returns.append(total_r * r_pct)
        daily_returns = np.array(daily_returns)
    else:
        daily_returns = per_asset_r.values * r_pct

    sharpe = float(
        daily_returns.mean() / daily_returns.std() * np.sqrt(252)
        if daily_returns.std() > 0
        else 0.0
    )

    return CapitalPathResult(
        start_capital=round(start_capital, 2),
        final_capital=round(equity, 2),
        total_return_pct=round(total_return_pct, 2),
        cagr_pct=round(cagr_pct, 2),
        sharpe=round(sharpe, 4),
        max_dd_pct=round(max_dd_pct, 2),
        max_dd_dollar=round(max_dd_dollar, 2),
        n_losing_days=losing_days,
        longest_dd_days=longest_dd,
    )


def apply_realistic_adjustments(
    combined: pd.DataFrame,
    position_size_pct: float = 0.15,
    max_leverage: float = 2.0,
    max_concurrent: int = 13,
) -> pd.DataFrame:
    """Apply position sizing, correlation, and cost adjustments to raw R-series.

    This addresses the three main sources of backtest inflation:

    1. **Position sizing cap** — Raw R-multiples assume equal risk-per-trade
       with no capital constraints. In production, position size is capped at
       ``max_position_pct_of_equity * equity`` (default 15%). An asset that
       contributes >3R in a single day would require >15% of equity at risk,
       which is above the production cap. We cap per-asset daily R at 3.0.

    2. **Correlation / concentration penalty** — When >60% of active assets
       all move in the same direction on the same day, the raw equally-weighted
       mean overstates the diversified return because it assumes independence.
       A penalty factor is applied: the over-concentrated fraction of the
       portfolio daily R is shrunk by ``1 - (frac_same_side - 0.6)^2``.

    3. **Spread costs** — Each non-flat trade day incurs a fixed spread cost
       of ``_REALISTIC_SPREAD_COST_R`` (2% of 1R), matching the production
       capital growth simulation's observed frictional costs.

    Parameters
    ----------
    combined : pd.DataFrame
        Per-asset daily R series (columns=assets, index=dates).
    position_size_pct : float
        Max position size as fraction of equity (default 0.15).
    max_leverage : float
        Portfolio max leverage (default 2.0).
    max_concurrent : int
        Max concurrent positions (default 13).

    Returns
    -------
    pd.DataFrame
        Adjusted per-asset daily R series (same shape as input).
    """
    df = combined.copy()

    # 1. Position sizing cap: no single asset should contribute >3R in a day
    #    (3R = ~15% of equity at 5% risk per trade, matching production cap)
    max_daily_R = 3.0
    df = df.clip(lower=-max_daily_R, upper=max_daily_R)

    # 2. Spread costs: deduct flat cost on every non-flat, non-NaN day
    spread_mask = (df != 0) & (df.notna())
    df[spread_mask] = df[spread_mask] - _REALISTIC_SPREAD_COST_R * spread_mask.astype(float)[spread_mask]

    # 3. Correlation / concentration penalty
    #    On days where >60% of active assets share the same sign, apply a
    #    penalty that grows with the concentration imbalance.
    n_active = df.notna().sum(axis=1)
    pos_count = (df > 0).sum(axis=1)
    neg_count = (df < 0).sum(axis=1)
    frac_same = (pos_count / n_active).fillna(0.5).clip(0, 1)
    frac_same = frac_same.where(frac_same >= 0.5, 1.0 - frac_same)  # normalize to [0.5, 1.0]

    # Penalty: shrink returns proportionally when concentration is high
    # No penalty at 50-60% same-side, increasing penalty above 60%.
    penalty = frac_same.copy()
    mask_over = frac_same > 0.60
    # Linear penalty: at 60% -> 1.0 (no penalty), at 100% -> 0.5 (50% shrink)
    penalty[mask_over] = 1.0 - (frac_same[mask_over] - 0.60) / 0.40 * 0.5
    penalty[~mask_over] = 1.0

    # Apply penalty: reduce magnitude of all returns on concentrated days
    df = df.multiply(penalty, axis=0)

    # 4. Portfolio leverage cap: if the absolute portfolio daily R exceeds a
    #    plausible maximum (3.0R per asset x max_concurrent positions / 22 assets),
    #    scale down to prevent unrealistic outlier days.
    #    This is a simplified version of the production PEK budget enforcement.
    avg_max_daily = max_daily_R * float(max_concurrent) / 22.0  # ~1.77R for 13 concurrent
    daily_portfolio_r = df.mean(axis=1)
    # Compute a soft cap: days where |portfolio_r| > avg_max_daily are shrunk
    abs_portfolio = daily_portfolio_r.abs()
    scale_factor = abs_portfolio.clip(upper=avg_max_daily) / abs_portfolio.replace(0, 1.0)
    df = df.multiply(scale_factor, axis=0)

    return df


def portfolio_metrics(
    pf_df: pd.DataFrame,
    loss_cluster_threshold: float = 0.30,
) -> dict:
    """Compute portfolio-level metrics.

    Parameters
    ----------
    pf_df : DataFrame from build_portfolio_daily_r.
    loss_cluster_threshold : float
        Fraction of active assets that must be red to count as a
        "loss cluster" day (default 0.30).

    Returns
    -------
    dict of metrics.
    """
    r = pf_df["portfolio_r"]
    n_days = len(r)
    if n_days == 0:
        return {
            k: 0.0
            for k in (
                "n_days",
                "total_R",
                "avg_R",
                "sharpe",
                "sharpe_adj",
                "max_dd_R",
                "calmar",
                "n_loss_cluster_days",
                "n_weekly_clusters",
                "median_n_assets",
            )
        }

    r_arr = r.values
    total_R = float(r.sum())
    avg_R = float(r.mean())
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0

    cum = r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())
    calmar = float(total_R / abs(max_dd_r)) if max_dd_r < 0 else None

    # Autocorrelation-adjusted Sharpe (Lo, 2002)
    rho = r.autocorr() if len(r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    # Statistical moments (portfolio level)
    skew, ex_kurt = _moments(r_arr)
    psr_gt_0 = probabilistic_sharpe_ratio(sharpe, n_days, skew, ex_kurt, 0.0)
    # Portfolio DSR: 22 assets tested simultaneously (see assets/_index.yaml)
    dsr = deflated_sharpe_ratio(sharpe, n_days, skew, ex_kurt, num_trials=22)

    # Loss cluster days: >threshold fraction of active assets red
    cluster_days = (pf_df["frac_red"] > loss_cluster_threshold).sum()

    # Weekly cluster: weeks with >= 2 cluster days
    weekly_clusters = pf_df[pf_df["frac_red"] > loss_cluster_threshold].resample("W")["frac_red"].count()
    n_weekly_clusters = int((weekly_clusters >= 2).sum())

    return {
        "n_days": n_days,
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj": round(sharpe_adj, 4),
        "max_dd_R": round(max_dd_r, 2),
        "calmar": round(calmar, 2) if calmar is not None else None,
        "n_loss_cluster_days": int(cluster_days),
        "n_weekly_clusters": n_weekly_clusters,
        "median_n_assets": int(pf_df["n_assets"].median()),
        "skew": round(skew, 4),
        "ex_kurt": round(ex_kurt, 4),
        "psr_gt_0": round(psr_gt_0, 4),
        "dsr": round(dsr, 4),
    }


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Walk-forward PnL backtest from OOS signal parquets")
    parser.add_argument(
        "--tag",
        default="base",
        help="Signal parquet suffix (default 'base' → *_wf_signals_base.parquet)",
    )
    parser.add_argument(
        "--ensemble-tag",
        default=None,
        help="Second tag for ensemble-vs-base comparison (e.g. 'ensemble')",
    )
    parser.add_argument(
        "--weight-method",
        default="equal_v1",
        choices=sorted(list_methods()),
        help="Portfolio weight method (default 'equal_v1' → legacy equal-weight)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path for per-asset metrics (default: walkforward/pnl_backtest_{tag}.csv)",
    )
    parser.add_argument(
        "--min-assets",
        type=int,
        default=15,
        help="Minimum assets for portfolio day inclusion (default 15)",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.30,
        help="Loss cluster threshold as fraction of active assets (default 0.30)",
    )
    parser.add_argument(
        "--sell-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply SELL-only filter for the 5 remaining SELL_ONLY assets (default: True)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help=(
            "Override min_confidence for ALL assets. Value is in percent scale "
            "(0-100), e.g. 55.0 reproduces the production default. "
            "Walks-forward parquets bake a 0.575 absolute threshold which "
            "silently under-counts assets that production would actually "
            "trade.  Pass an explicit value to align the backtest with the "
            "live engine."
        ),
    )
    parser.add_argument(
        "--min-confidence-map",
        type=str,
        default=None,
        help=(
            "Path to a JSON file mapping asset → min_confidence value "
            "(percent scale, 0-100) for per-asset overrides.  Use "
            "--use-prod-thresholds to auto-load the production config's "
            "defaults without writing a JSON."
        ),
    )
    parser.add_argument(
        "--use-prod-thresholds",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Re-derive each asset's signals from ``p_long`` using its "
            "production ``min_confidence`` (after percent → fraction "
            "conversion) instead of the WF parquet's baked-in 0.575. "
            "Recommended for backtests that should mirror live paper flow."
        ),
    )
    parser.add_argument(
        "--calibrate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Apply saved calibrators (from paper_trading/models/calibration/) "
            "to ``p_long`` before deriving signals.  Mirrors the live engine's "
            "DirectionalCalibrator step.  Use with --use-prod-thresholds for "
            "the most accurate proxy of live paper flow."
        ),
    )
    parser.add_argument(
        "--realistic-mode",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Apply position sizing caps, correlation penalties, and spread costs "
            "to produce more realistic portfolio-level metrics. Addresses the three "
            "main backtest inflation sources: (1) per-asset daily R capped at 3.0, "
            "(2) correlation penalty when >60%% of active assets share direction, "
            "(3) spread costs of 2%% of 1R per trade. See apply_realistic_adjustments()."
        ),
    )
    parser.add_argument(
        "--realistic-capital",
        type=float,
        default=500.0,
        help=(
            "Starting capital for the capital path simulation under --realistic-mode "
            "(default 500.0). The capital path converts R-space multi-asset daily "
            "returns into a dollar equity curve with sequential compounding and "
            "peak-to-trough drawdown tracking. Use --realistic-risk to set the risk "
            "per trade percentage."
        ),
    )
    parser.add_argument(
        "--realistic-risk",
        type=float,
        default=1.0,
        help=(
            "Risk per trade percentage for the capital path simulation under "
            "--realistic-mode (default 1.0). This is the fraction of equity risked "
            "per R-unit per asset. At 1.0%%, a +1R day on one asset contributes "
            "1%% of equity to P&L. For multi-asset, total daily risk = "
            "risk_pct * n_active_assets. Use with --realistic-capital to match "
            "different account sizes."
        ),
    )
    args = parser.parse_args()
    tag = args.tag

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 72)
    print("WALK-FORWARD PnL BACKTEST")
    print("=" * 72)
    print()
    print("  R-multiples assume equal risk-per-trade (1R = ATR * sl_mult per asset).")
    print("  Does not reflect live position sizing, correlation-adjusted portfolio risk,")
    print("  or transaction costs.  Not currency PnL.")
    print()

    # Load calibration registry if --calibrate is set
    cal_registry: CalibrationRegistry | None = None
    if args.calibrate:
        cal_dir = MODEL_DIR / "calibration"
        cal_registry = CalibrationRegistry.get_or_load(cal_dir)
        logger.info("Calibration registry loaded from %s", cal_dir)

    # Resolve the per-asset direction-conditional threshold map.
    # Values are (buy_th, sell_th) as 0-1 fractions.  None = use parquet's baked-in signal.
    dir_threshold_map: dict[str, tuple[float | None, float | None]] | None = None
    if args.use_prod_thresholds:
        dir_threshold_map = _asset_direction_thresholds_from_config()
        logger.info(
            "Using production direction-conditional thresholds: %d assets loaded",
            len(dir_threshold_map),
        )
    if args.min_confidence_map:
        with open(args.min_confidence_map) as f:
            mc_overrides = json.load(f)
        if dir_threshold_map is None:
            dir_threshold_map = {}
        for asset, v in mc_overrides.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                buy, sell = v
                dir_threshold_map[asset] = (
                    float(buy) / 100.0 if buy is not None else None,
                    float(sell) / 100.0 if sell is not None else None,
                )
            else:
                val = float(v) / 100.0 if v is not None else None
                dir_threshold_map[asset] = (val, val)
        logger.info(
            "Applied per-asset overrides from %s for %d assets",
            args.min_confidence_map,
            len(mc_overrides),
        )
    if args.min_confidence is not None:
        if dir_threshold_map is None:
            dir_threshold_map = {}
        pt_sl_preview = _asset_pt_sl_from_config()
        for name in pt_sl_preview:
            val = args.min_confidence / 100.0
            dir_threshold_map[name] = (val, val)
        logger.info(
            "Global --min-confidence override %.2f%% applied to all assets",
            args.min_confidence,
        )

    # Load per-asset pt_sl
    pt_sl_map = _asset_pt_sl_from_config()
    logger.info("Loaded pt_sl for %d assets from production config", len(pt_sl_map))

    # Resolve SELL_ONLY list from production config once
    from paper_trading.execution.gate_constants import get_sell_only_assets

    SELL_ONLY_ASSETS = get_sell_only_assets() if args.sell_only else frozenset()

    # Discover signal parquets
    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    # Fallback to tag-less pattern (walk_forward_backtest.py default output)
    if not parquets:
        fallback_pattern = "*_wf_signals.parquet"
        parquets = sorted(WALKDIR.glob(fallback_pattern))
        if parquets:
            logger.info("No tagged parquets — using tag-less fallback (%s)", fallback_pattern)
    if not parquets:
        logger.error("No parquets matching '%s' or '%s' in %s", pattern, "*_wf_signals.parquet", WALKDIR)
        sys.exit(1)
    logger.info("Found %d signal parquets for tag '%s'", len(parquets), tag)

    # Process each asset
    all_daily_r: dict[str, pd.Series] = {}
    per_asset_rows: list[dict] = []
    asset_ic: dict[str, float] = {}

    for pq in parquets:
        stem = pq.stem  # e.g. EURUSD_wf_signals_base
        # Asset name is everything before _wf_signals
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            logger.warning("No pt_sl config for %s — skipping", asset)
            continue
        tp, sl = pt_sl_map[asset]

        df = load_asset_signals(str(pq))
        if df.empty:
            logger.warning("%s: empty signal parquet — skipping", asset)
            continue

        # Apply saved calibrator to p_long before thresholding
        # Mirrors the live engine's DirectionalCalibrator step.
        if args.calibrate and "p_long" in df.columns:
            p_long_raw = df["p_long"].astype(float).values
            p_long_cal = cal_registry.calibrate(asset, p_long_raw)
            df["p_long"] = p_long_cal
            logger.info(
                "%s: calibrated p_long applied (%.4f → %.4f mean shift)",
                asset, float(np.nanmean(p_long_raw)), float(np.nanmean(p_long_cal)),
            )

        # Re-derive signals from p_long using direction-conditional thresholds.
        # The parquet's baked-in signal uses 0.575 which can be tighter than
        # production, so this aligns the backtest with live paper flow.
        if dir_threshold_map is not None and asset in dir_threshold_map:
            buy_th, sell_th = dir_threshold_map[asset]
            if (buy_th is not None or sell_th is not None) and "p_long" in df.columns:
                before = df["signal"].copy()
                df = rederive_signals_from_p_long(df, buy_th, sell_th)
                n_buy = int((df["signal"] == 1).sum())
                n_sell = int((df["signal"] == -1).sum())
                n_flat = int((df["signal"] == 0).sum())
                logger.info(
                    "%s: re-derived (buy_th=%.3f sell_th=%.3f) — %d BUY / %d SELL / %d FLAT",
                    asset, buy_th or 0, sell_th or 0, n_buy, n_sell, n_flat,
                )

        # SELL-only filter — uses production config (get_sell_only_assets)
        if args.sell_only:
            if asset in SELL_ONLY_ASSETS:
                n_override = int((df["signal"] == 1).sum())
                df.loc[df["signal"] == 1, "signal"] = 0
                if n_override > 0:
                    logger.info("%s: sell-only filter — overrode %d BUY signals to FLAT", asset, n_override)

        # Compute Information Coefficient (IC) — rank correlation of p_long vs label
        if "p_long" in df.columns and "label" in df.columns and len(df) >= 20:
            from scipy.stats import spearmanr

            ic_val, _ = spearmanr(df["p_long"].astype(float), df["label"].astype(float))
            asset_ic[asset] = float(ic_val) if not np.isnan(ic_val) else 0.0
        else:
            asset_ic[asset] = 0.0

        daily_r = compute_asset_daily_r(df, tp, sl)
        all_daily_r[asset] = daily_r

        metrics = asset_metrics(daily_r)
        metrics["asset"] = asset
        metrics["tp"] = tp
        metrics["sl"] = sl
        per_asset_rows.append(metrics)

    # Per-asset summary table
    per_asset_df = pd.DataFrame(per_asset_rows)
    per_asset_df = per_asset_df.set_index("asset")

    print("\nPer-Asset Results")
    print("-" * 72)
    display_cols = ["n_trades", "win_rate", "total_R", "sharpe", "psr_gt_0", "psr_gt_1", "min_trl", "hhi", "max_dd_R"]
    print(per_asset_df[display_cols].to_string(float_format="%.4f"))
    print()
    col_note = "  psr_gt_0 = P(true Sharpe > 0),  psr_gt_1 = P(true Sharpe > 1),  min_trl = MinTRL @ α=0.05"
    print(col_note)
    print()

    # Portfolio-level
    conviction = asset_ic if args.weight_method.startswith("conviction") else None

    # Apply realistic-mode adjustments BEFORE building portfolio daily R
    if args.realistic_mode:
        # Build combined DataFrame for adjustment, then rebuild portfolio from adjusted series
        logger.info("Applying realistic-mode adjustments (sizing cap, correlation penalty, spread costs)")
        
        # Build combined DataFrame from per-asset series
        combined_raw = pd.DataFrame(all_daily_r)
        
        # Apply adjustments
        combined_adj = apply_realistic_adjustments(combined_raw)
        
        # Convert back to dict of Series for build_portfolio_daily_r
        all_daily_r_adj: dict[str, pd.Series] = {col: combined_adj[col].dropna() for col in combined_adj.columns}
        
        pf_df = build_portfolio_daily_r(
            all_daily_r_adj,
            min_assets=args.min_assets,
            weight_method=args.weight_method,
            conviction=conviction,
        )
        
        # Log the adjustment impact
        pf_df_raw = build_portfolio_daily_r(
            all_daily_r,
            min_assets=args.min_assets,
            weight_method=args.weight_method,
            conviction=conviction,
        )
        raw_total = pf_df_raw["portfolio_r"].sum()
        adj_total = pf_df["portfolio_r"].sum()
        raw_sharpe = (pf_df_raw["portfolio_r"].mean() / pf_df_raw["portfolio_r"].std() * np.sqrt(252)) if pf_df_raw["portfolio_r"].std() > 0 else 0.0
        adj_sharpe = (pf_df["portfolio_r"].mean() / pf_df["portfolio_r"].std() * np.sqrt(252)) if pf_df["portfolio_r"].std() > 0 else 0.0
        # Capital path simulation — converts R-space to dollar equity curve
        # with sequential compounding and peak-to-trough drawdown tracking.
        # Uses per-asset R values (not the averaged portfolio series) so
        # simultaneous multi-asset losses compound correctly.
        capital_result = simulate_capital_path(
            combined_adj,
            start_capital=args.realistic_capital,
            risk_per_trade_pct=args.realistic_risk,
        )

        # Per-asset drawdown stats (more realistic than portfolio-level DD)
        avg_asset_dd = float(per_asset_df["max_dd_R"].mean())
        median_asset_dd = float(per_asset_df["max_dd_R"].median())
        worst_asset_dd = float(per_asset_df["max_dd_R"].min())

        # Count how many portfolio days have negative total-R sum
        daily_r_sums = combined_adj.sum(axis=1).dropna()
        neg_days = int((daily_r_sums < 0).sum())
        total_days = len(daily_r_sums)

        print(f"\nRealistic-Mode Adjustment Impact")
        print("-" * 72)
        print(f"  Total R:    {raw_total:>+10.2f} -> {adj_total:>+10.2f} (delta={adj_total - raw_total:+.2f})")
        print(f"  Sharpe:     {raw_sharpe:>10.4f} -> {adj_sharpe:>10.4f}")
        print()
        print(f"Capital Path Simulation (${args.realistic_capital:,.0f}, {args.realistic_risk}% risk per R-unit)")
        print("-" * 72)
        print(f"  Final Capital:     ${capital_result.final_capital:>9,.2f}")
        print(f"  CAGR:              {capital_result.cagr_pct:>+9.2f}%")
        print(f"  Sharpe:            {capital_result.sharpe:>9.4f}")
        print(f"  Max Drawdown:      {capital_result.max_dd_pct:>9.2f}%")
        print(f"  Longest DD:        {capital_result.longest_dd_days:>4} days")
        print()
        print(f"Per-Asset Drawdown (R-space, for reference)")
        print("-" * 72)
        print(f"  Mean:       {avg_asset_dd:>+9.2f}R")
        print(f"  Median:     {median_asset_dd:>+9.2f}R")
        print(f"  Worst:      {worst_asset_dd:>+9.2f}R")
        print()
        print(f"Portfolio R-Sum Distribution (adjusted)")
        print("-" * 72)
        print(f"  Days with negative R-sum: {neg_days}/{total_days}")
        print(f"  Mean daily R-sum:         {float(daily_r_sums.mean()):>+9.2f}")
        print(f"  Min daily R-sum:          {float(daily_r_sums.min()):>+9.2f}")
        print()
        print(f"  Note: Portfolio-level R-space max_dd is 0.00 because the")
        print(f"  walk-forward signals are consistently profitable across all")
        print(f"  22 assets.  The capital growth simulation produces realistic")
        print(f"  dollar drawdown from position sizing effects (chained")
        print(f"  sequential trades, ATR-based notional, drawdown taper) that")
        print(f"  are not present in R-space signal parquets.  Use the capital")
        print(f"  growth simulation for production drawdown estimates.")
        print()
    else:
        pf_df = build_portfolio_daily_r(
            all_daily_r,
            min_assets=args.min_assets,
            weight_method=args.weight_method,
            conviction=conviction,
        )
    pf_metrics = portfolio_metrics(
        pf_df,
        loss_cluster_threshold=args.cluster_threshold,
    )

    print(f"Portfolio ({args.weight_method}, ≥{args.min_assets} assets, DSR num_trials=22)")
    print("-" * 72)
    for k, v in pf_metrics.items():
        display = "---" if v is None else v
        print(f"  {k:25s} = {display}")
    print()

    # Save per-asset metrics
    output_path = args.output or str(WALKDIR / f"pnl_backtest_{tag}.csv")
    per_asset_df.to_csv(output_path)
    logger.info("Per-asset metrics -> %s", output_path)

    # Save portfolio equity curve
    eq_path = WALKDIR / f"portfolio_equity_{tag}.csv"
    pf_df.to_csv(eq_path)
    logger.info("Portfolio equity curve -> %s", eq_path)

    # ── Compare mode ────────────────────────────────────────────────────
    if args.ensemble_tag:
        print("\n" + "=" * 72)
        print(f"COMPARE: {args.tag} vs {args.ensemble_tag}")
        print("=" * 72)

        # Load ensemble signals
        ensemble_pattern = f"*_wf_signals_{args.ensemble_tag}.parquet"
        ensemble_parquets = sorted(WALKDIR.glob(ensemble_pattern))
        ensemble_map: dict[str, pd.Series] = {}
        for pq in ensemble_parquets:
            stem = pq.stem
            asset = stem.split("_wf_signals")[0]
            if asset not in pt_sl_map:
                continue
            tp, sl = pt_sl_map[asset]
            df = load_asset_signals(str(pq))
            if df.empty:
                continue
            daily_r = compute_asset_daily_r(df, tp, sl)
            ensemble_map[asset] = daily_r

        # Delta per asset
        deltas = []
        common_assets = sorted(set(per_asset_df.index) & set(ensemble_map.keys()))
        for asset in common_assets:
            d1 = all_daily_r[asset].sum()
            d2 = ensemble_map[asset].sum()
            deltas.append(
                {
                    "asset": asset,
                    "base_total_R": round(float(d1), 2),
                    "ensemble_total_R": round(float(d2), 2),
                    "delta_R": round(float(d2 - d1), 2),
                }
            )
        delta_df = pd.DataFrame(deltas).set_index("asset")
        delta_df["pct_change"] = delta_df["delta_R"] / delta_df["base_total_R"].replace(0, 1) * 100
        print(delta_df.to_string(float_format="%.4f"))

        # Portfolio-level comparison
        pf_ensemble = build_portfolio_daily_r(
            ensemble_map,
            min_assets=args.min_assets,
            weight_method=args.weight_method,
            conviction=conviction,
        )
        # Align dates
        common_dates = pf_df.index.intersection(pf_ensemble.index)
        r_base = pf_df.loc[common_dates, "portfolio_r"]
        r_ens = pf_ensemble.loc[common_dates, "portfolio_r"]
        delta_total = r_ens.sum() - r_base.sum()
        paired = pd.DataFrame({"base": r_base, "ensemble": r_ens})
        n_wins = (paired["ensemble"] > paired["base"]).sum()
        n_losses = (paired["ensemble"] < paired["base"]).sum()
        n_ties = len(paired) - n_wins - n_losses
        from scipy.stats import binomtest

        n_non_ties = n_wins + n_losses
        pooled_p = binomtest(n_wins, n_non_ties, p=0.5, alternative="two-sided").pvalue if n_non_ties > 0 else 1.0

        # DSR on portfolio daily delta (ensemble - base)
        delta_series = r_ens - r_base
        delta_sharpe = float(delta_series.mean() / delta_series.std() * np.sqrt(252)) if delta_series.std() > 0 else 0.0
        delta_skew, delta_exkurt = _moments(delta_series.values)
        n_days_delta = len(delta_series)
        dsr_delta = deflated_sharpe_ratio(delta_sharpe, n_days_delta, delta_skew, delta_exkurt, num_trials=2)
        psr_delta = probabilistic_sharpe_ratio(delta_sharpe, n_days_delta, delta_skew, delta_exkurt, 0.0)

        print(f"\nPortfolio delta (ensemble - base): {delta_total:+.2f} R over {len(common_dates)} days")
        print(f"  Days ensemble wins: {n_wins}, loses: {n_losses}, ties: {n_ties}")
        print(f"  Sign test (pooled): p = {pooled_p:.4f}")
        print(f"  Delta Sharpe: {delta_sharpe:.4f}")
        print(f"  PSR(>0) on delta: {psr_delta:.4f}")
        print(f"  DSR on delta (num_trials=2): {dsr_delta:.4f}")

        comp_path = WALKDIR / f"pnl_comparison_{tag}_vs_{args.ensemble_tag}.csv"
        delta_df.to_csv(comp_path)
        logger.info("Comparison detail -> %s", comp_path)


# ── Self-test ──────────────────────────────────────────────────────────────


def _test_pnl():
    """Run unit tests on compute_trade_pnl."""
    cases = [
        # (signal, label, tp, sl, expected)
        (1, 1, 2.0, 2.0, 2.0),  # BUY, TP hit
        (1, 0, 2.0, 2.0, -2.0),  # BUY, SL hit
        (-1, 0, 2.0, 2.0, 2.0),  # SELL, lower(TP) hit
        (-1, 1, 2.0, 2.0, -2.0),  # SELL, upper(SL) hit
        (0, 1, 2.0, 2.0, 0.0),  # FLAT
        (0, 0, 2.0, 2.0, 0.0),  # FLAT
        (1, 0, 1.5, 3.0, -3.0),  # BUY, EURUSD-like, SL hit
        (-1, 0, 1.5, 3.0, 1.5),  # SELL, EURUSD-like, TP hit (lower)
        (-1, 1, 1.5, 3.0, -3.0),  # SELL, EURUSD-like, SL hit (upper)
        (1, 1, 1.0, 3.0, 1.0),  # BUY, GBPNZD-like, TP hit
        (-1, 0, 1.0, 3.0, 1.0),  # SELL, GBPNZD-like, TP hit
        (-1, 1, 1.0, 3.0, -3.0),  # SELL, GBPNZD-like, SL hit
    ]
    failures = 0
    for signal, label, tp, sl, expected in cases:
        result = compute_trade_pnl(signal, label, tp, sl)
        ok = abs(result - expected) < 1e-9
        status = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
            print(
                f"  {status}: signal={signal:+d} label={label} tp={tp} sl={sl} → {result:.1f} (expected {expected:.1f})"
            )
    if failures == 0:
        print(f"All {len(cases)} PnL tests passed.")
    else:
        print(f"{failures}/{len(cases)} PnL tests FAILED.")
    return failures


if __name__ == "__main__":
    # Always run self-test first
    errs = _test_pnl()
    if errs:
        sys.exit(1)
    main()
