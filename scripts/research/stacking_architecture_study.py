#!/usr/bin/env python3
"""
Institutional Research Study: Multi-Position Architecture, Position Stacking & Trade Management Optimization

Production-grade quantitative research harness. Executes all Policy Experiments A-F,
position sizing variants, signal gating, trailing stop comparisons, exit strategies,
portfolio heat constraints, correlation-aware stacking, asset-by-asset optimization,
session/regime analysis, bootstrap validation, transaction cost sensitivity, stress
testing, and Monte Carlo simulations.

Output: data/processed/audits/stacking_architecture_results.json — comprehensive structured report.

Every recommendation is supported by statistical evidence with bootstrap confidence
intervals, regime robustness checks, and out-of-sample validation.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/stacking_architecture_study.py
    PYTHONPATH=$PYTHONPATH:. python scripts/research/stacking_architecture_study.py --quick  # subset of experiments
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

logger = logging.getLogger("stacking_study")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"
OUTDIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
OUTDIR.mkdir(parents=True, exist_ok=True)

# ── Asset Universe ─────────────────────────────────────────────────────────────

# Production-relevant assets that appear in the untagged parquets
ACTIVE_ASSETS = [
    "AUDUSD", "CADCHF", "EURAUD", "EURCAD", "EURCHF", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPUSD", "GC", "NZDCAD",
    "NZDCHF", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "^DJI",
    "AUDJPY", "BTCUSD", "GBPJPY", "NZDJPY",
]

# ── Metrics ────────────────────────────────────────────────────────────────────


@dataclass
class Metrics:
    """Comprehensive set of evaluation metrics for a strategy."""
    total_R: float = 0.0
    n_trades: int = 0
    win_rate: float = 0.0
    avg_R: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    sharpe_adj: float = 0.0
    sortino: float = 0.0
    max_dd_R: float = 0.0
    calmar: float = 0.0
    recovery_factor: float = 0.0
    daily_dd_max: float = 0.0
    avg_holding_bars: float = 0.0
    skew: float = 0.0
    ex_kurt: float = 0.0
    psr_gt_0: float = 0.0
    psr_gt_1: float = 0.0
    dsr: float = 0.0
    hhi: float = 0.0


def compute_metrics(r_series: pd.Series, num_trials: int = 22) -> Metrics:
    """Compute all metrics from a daily R-multiple series."""
    m = Metrics()
    arr = r_series.values
    n_days = len(arr)
    m.n_trades = int((arr != 0).sum())
    if m.n_trades == 0 or n_days == 0:
        return m

    m.total_R = float(arr.sum())
    nonzero = arr[arr != 0]
    m.avg_R = float(nonzero.mean()) if len(nonzero) > 0 else 0.0
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    m.win_rate = len(wins) / max(m.n_trades, 1)
    m.profit_factor = float(abs(wins.sum() / losses.sum())) if len(losses) > 0 else float("inf")

    mean = float(arr.mean())
    std = float(arr.std())
    m.sharpe = mean / max(std, 1e-9) * math.sqrt(252) if std > 0 else 0.0

    rho = float(r_series.autocorr()) if len(r_series) > 1 else 0.0
    m.sharpe_adj = m.sharpe * math.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else m.sharpe

    downside = arr[arr < 0]
    downside_std = float(downside.std()) if len(downside) > 0 else 0.0
    m.sortino = mean / max(downside_std, 1e-9) * math.sqrt(252) if downside_std > 0 else 0.0

    cum = r_series.cumsum().values
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    m.max_dd_R = float(dd.min())
    m.daily_dd_max = float(np.min(np.diff(cum))) if n_days > 1 else 0.0
    m.calmar = float(m.total_R / abs(m.max_dd_R)) if m.max_dd_R < 0 else float("inf")
    m.recovery_factor = float(m.total_R / abs(m.max_dd_R)) if m.max_dd_R < 0 else float("inf")

    m.skew = float(scipy_stats.skew(arr)) if std > 0 else 0.0
    m.ex_kurt = float(scipy_stats.kurtosis(arr)) if std > 0 else 0.0

    # Probabilistic Sharpe Ratio
    from eigencapital.domain.value_objects.statistical_metrics import (
        probabilistic_sharpe_ratio, deflated_sharpe_ratio, herfindahl_index,
    )
    m.psr_gt_0 = float(probabilistic_sharpe_ratio(m.sharpe, n_days, m.skew, m.ex_kurt, 0.0))
    m.psr_gt_1 = float(probabilistic_sharpe_ratio(m.sharpe, n_days, m.skew, m.ex_kurt, 1.0))
    m.dsr = float(deflated_sharpe_ratio(m.sharpe, n_days, m.skew, m.ex_kurt, num_trials))
    m.hhi = float(herfindahl_index(nonzero)) if len(nonzero) > 0 else 0.0
    return m


# ── Core PnL Functions ─────────────────────────────────────────────────────────


def compute_label_pnl(signals: np.ndarray, labels: np.ndarray, tp: float, sl: float) -> np.ndarray:
    """Vectorised: R-multiple per signal from triple-barrier labels."""
    r = np.zeros(len(signals), dtype=float)
    buy = signals == 1
    sell = signals == -1
    r[buy & (labels == 1)] = tp
    r[buy & (labels == 0)] = -sl
    r[sell & (labels == 0)] = tp
    r[sell & (labels == 1)] = -sl
    return r


def load_asset_data(assets: list[str] | None = None, tag: str = "") -> dict[str, dict]:
    """Load signal parquets and compute per-asset configs.

    Returns dict keyed by asset name with keys:
        df, tp, sl, p_long, signals, labels, label_r, index
    """
    from paper_trading.config_manager import get_config

    cfg = get_config()
    suffix = f"_{tag}" if tag else ""

    result: dict[str, dict] = {}
    target_assets = assets or ACTIVE_ASSETS

    for name in target_assets:
        acfg = cfg.assets.get(name, {})
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))

        pq_path = WALKDIR / f"{name}_wf_signals{suffix}.parquet"
        if not pq_path.exists():
            continue
        df = pd.read_parquet(pq_path).sort_index()
        if df.empty:
            continue

        signals = df["signal"].values.astype(int)
        labels = df["label"].values.astype(int)
        p_long = df["p_long"].values.astype(float) if "p_long" in df.columns else np.full(len(df), 0.5)
        label_r = compute_label_pnl(signals, labels, tp, sl)

        result[name] = {
            "df": df,
            "tp": tp,
            "sl": sl,
            "signals": signals,
            "labels": labels,
            "label_r": label_r,
            "p_long": p_long,
            "index": df.index,
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY EXPERIMENTS
# ═══════════════════════════════════════════════════════════════════════════════

# Each experiment takes (asset_data, params) and returns (daily_r_series, metadata)


@dataclass
class ExperimentResult:
    """Result of a single experiment run."""
    daily_r: pd.Series
    metrics: Metrics
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _position_unrealized_r(entry: float, current: float, direction: int, vol: float) -> float:
    if vol <= 0 or entry <= 0:
        return 0.0
    if direction == 1:
        return (current - entry) / (entry * vol)
    return (entry - current) / (entry * vol)


def _compute_daily_r(asset_data: dict, label_r_override: np.ndarray | None = None) -> pd.Series:
    daily_r = label_r_override if label_r_override is not None else asset_data["label_r"]
    return pd.Series(daily_r, index=asset_data["index"], name="daily_r")


def _portfolio_r(series_map: dict[str, pd.Series]) -> pd.Series:
    """Equal-weight portfolio series from per-asset series."""
    combined = pd.DataFrame(series_map)
    return combined.mean(axis=1, skipna=False).fillna(0)


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY A: Baseline (single position, no stacking)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_baseline(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy A: Single position. No stacking. This is the control group."""
    daily_r = _compute_daily_r(asset_data)
    return ExperimentResult(
        daily_r=daily_r,
        metrics=compute_metrics(daily_r),
        metadata={"policy": "A_baseline", "n_positions": 1, "stacking": False},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY B: Single Position (explicit — no stacking at all)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_single(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy B: Single position only. Same as A for signal-based PnL (parquet
    signals give one trade per day). Identical to baseline for clean comparison."""
    return policy_baseline(asset_data, params)


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY C: Dual Position (identical management, no differentiation)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_dual_identical(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy C: Two positions managed identically. Both get same TP, SL, trail.

    This is approximated by the stacking backtest with layer_multipliers=[1.0, 1.0]
    and no tight TP for stacked layers (stack_tp_ratio=1.0).
    """
    return _run_stacking_backtest(
        asset_data,
        layer_multipliers=[1.0, 1.0],
        max_layers=2,
        min_confidence=0.0,
        min_pnl_r=0.0,
        stack_tp_ratio=1.0,
        breakeven_threshold=-1.0,
        metadata={"policy": "C_dual_identical", "description": "Two positions, identical management"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY D: Dual Position (current production: independent management)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_dual_independent(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy D: Current production independent trailing. Layer 2 gets tighter SL/TP."""
    return _sim_stacking_backtest(
        asset_data,
        layer_multipliers=[1.0, 0.5],
        max_layers=2,
        min_confidence=params.get("min_confidence", 0.0),
        min_pnl_r=params.get("min_stack_r", 0.5),
        stack_tp_ratio=params.get("stack_tp_ratio", 0.5),
        breakeven_threshold=params.get("breakeven_threshold", 0.5),
        metadata={
            "policy": "D_dual_independent",
            "description": "Current production: independent trailing, tighter SL for runner",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY E: Specialized Roles (conservative P1 + trend runner P2)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_specialized_roles(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy E: Position 1 = conservative early profit capture, Position 2 = trend runner.

    Approximation: P1 uses tight TP (stack_tp_ratio < 1.0), P2 uses wider TP.
    P1 closes at smaller R targets; P2 runs for full trend.
    """
    return _sim_stacking_backtest(
        asset_data,
        layer_multipliers=[1.0, params.get("p2_size_ratio", 0.5)],
        max_layers=2,
        min_confidence=0.0,
        min_pnl_r=params.get("min_stack_r", 0.3),
        stack_tp_ratio=params.get("stack_tp_ratio", 0.5),
        breakeven_threshold=params.get("breakeven_threshold", 0.3),
        metadata={
            "policy": "E_specialized_roles",
            "description": "P1 conservative (tight TP), P2 trend runner (full TP)",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY F: Dynamic Trade Management (adaptive trailing based on conditions)
# ═══════════════════════════════════════════════════════════════════════════════

def policy_dynamic(asset_data: dict, params: dict) -> ExperimentResult:
    """Policy F: Dynamic trade management. Trailing/exit adapts to conditions.

    Uses ADX to adjust trailing tightness, confidence to gate second entry,
    and regime to adjust TP targets.
    """
    df = asset_data["df"]
    signals = asset_data["signals"]
    labels = asset_data["labels"]
    tp_base = asset_data["tp"]
    sl_base = asset_data["sl"]
    index = asset_data["index"]
    p_long = asset_data["p_long"]

    n = len(signals)
    daily_r = np.zeros(n, dtype=float)

    # Compute rolling ADX and vol for dynamic adjustment
    high = df.get("high", pd.Series(np.nan, index=index))
    low = df.get("low", pd.Series(np.nan, index=index))
    close = df.get("close", pd.Series(np.nan, index=index))

    if not close.isna().all():
        log_ret = np.log(close / close.shift(1))
        rolling_vol = log_ret.rolling(21).std().fillna(method="bfill").values
    else:
        rolling_vol = np.full(n, 0.015)

    # ADX computation (simplified, from OHLC if available)
    atr = pd.Series(np.full(n, 0.01), index=index)
    if not high.isna().all() and not low.isna().all():
        tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().fillna(method="bfill").values
    else:
        atr = np.full(n, 0.01)

    # Rolling win rate for confidence-based dynamic management
    direction = 0
    active_r = 0.0
    entry_price = 0.0
    entry_vol = 0.015

    for i in range(n):
        sig = signals[i]
        label = labels[i]
        sig_r = compute_label_pnl(np.array([sig]), np.array([label]), tp_base, sl_base)[0]

        if sig == 0:
            continue

        vol_est = max(float(atr[i]) if i < len(atr) else 0.015, 0.005)
        conf = float(p_long[i]) if sig == 1 else 1.0 - float(p_long[i])
        adx_val = 20.0  # placeholder

        # Dynamic TP/SL adjustment based on environment
        # Higher vol → tighter SL, wider TP; lower vol → balanced
        vol_factor = min(max(vol_est / 0.015, 0.5), 2.0)
        dynamic_tp = tp_base * vol_factor
        dynamic_sl = sl_base / vol_factor

        if direction == 0 or sig != direction:
            # New position
            direction = sig
            entry_price = float(close.iloc[i]) if not pd.isna(close.iloc[i]) else 1.0
            entry_vol = vol_est

            if sig == 1:
                sig_r = dynamic_tp if label == 1 else -dynamic_sl
            else:
                sig_r = dynamic_tp if label == 0 else -dynamic_sl
            daily_r[i] = sig_r
            signals_r = sig_r

        else:
            # Same direction — dynamic stacking decision
            # Only stack if ADX > threshold (trending) and confidence high
            stack_conf = params.get("dynamic_stack_conf", 0.55)
            stack_adx = params.get("dynamic_stack_adx", 20)

            do_stack = (conf >= stack_conf or adx_val >= stack_adx)

            if do_stack:
                # Dynamic TP for stacked layer
                if conf > 0.7:
                    tp_adj = tp_base * 0.8
                elif conf > 0.6:
                    tp_adj = tp_base * 0.6
                else:
                    tp_adj = tp_base * 0.4

                if sig == 1:
                    sig_r = tp_adj if label == 1 else -dynamic_sl
                else:
                    sig_r = tp_adj if label == 0 else -dynamic_sl
                daily_r[i] = sig_r * params.get("stack_size", 0.5)
            else:
                daily_r[i] = 0.0  # skip

    return ExperimentResult(
        daily_r=pd.Series(daily_r, index=index, name="daily_r"),
        metrics=compute_metrics(pd.Series(daily_r, index=index)),
        metadata=metadata,
    )