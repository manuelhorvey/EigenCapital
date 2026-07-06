#!/usr/bin/env python3
"""Phase 1 — Baseline Performance Assessment.

Reads walk-forward signal parquets, applies adaptive exit simulation,
computes comprehensive baseline metrics in both R-space and %-space.
Output: data/processed/phase1_baseline.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eigencapital.capital_study.phase1")

WALKDIR = ROOT / "scripts" / "walkforward"
OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SELL_ONLY: frozenset[str] = frozenset({"CADCHF", "NZDCHF", "EURAUD"})

# Adaptive exit defaults (from production config)
BE_LOCK_R = 0.5
TRAIL_ACTIVATION_R = 0.8
TRAIL_RETRACE_PCT = 0.33
MAX_HOLD_CANDLES = 40
TIME_DECAY_START = 20


def apply_adaptive_exit(orig_r: float, mfe_r: float, exit_reason: str) -> float:
    """Apply retracement trail to a trade's R-multiple.

    Matches production AdaptiveExitEngine logic:
    - Winners (orig_r >= 0) pass through unchanged.
    - Losers with MFE >= 0.5R get the trail applied.
    - Trail exit at (1 - retrace_pct) * peak_MFE.
    """
    if orig_r >= 0:
        return orig_r
    if mfe_r < BE_LOCK_R or exit_reason == "tp":
        return orig_r
    captured = mfe_r * (1.0 - TRAIL_RETRACE_PCT)
    return max(captured, 0.0)


def atr_pct_from_ohlcv(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR as % of close price."""
    high = ohlcv["high"]
    low = ohlcv["low"]
    close = ohlcv["close"]
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    return (atr / close).fillna(0.0).clip(0, 0.5)


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config
    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def compute_baseline() -> dict:
    from scripts.backtest.backtest_pnl import compute_asset_daily_r, compute_trade_pnl

    pt_sl_map = load_pt_sl()
    logger.info("Loaded pt_sl for %d assets", len(pt_sl_map))

    parquets = sorted(WALKDIR.glob("*_wf_signals.parquet"))

    # ── Phase 1a: Fixed-barrier baseline ──
    all_daily_r: dict[str, pd.Series] = {}
    per_asset_rows: list[dict] = []

    for pq in parquets:
        stem = pq.stem
        name = stem.split("_wf_signals")[0]
        if name not in pt_sl_map:
            continue
        tp, sl = pt_sl_map[name]

        df = pd.read_parquet(pq)
        if name in SELL_ONLY:
            df.loc[df["signal"] == 1, "signal"] = 0

        r = compute_asset_daily_r(df, tp, sl)
        all_daily_r[name] = r

        n_trades = int((r != 0).sum())
        wins = r[r > 0]
        losses = r[r < 0]
        total_r = float(r.sum())
        avg_r = float(r[r != 0].mean()) if n_trades > 0 else 0.0
        win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
        pf = abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float("inf")
        sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
        rho = r.autocorr() if len(r) > 1 else 0.0
        sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

        cum = r.cumsum()
        dd = cum - cum.expanding().max()
        max_dd = float(dd.min())
        calmar = float(total_r / abs(max_dd)) if max_dd < 0 else float("inf")

        per_asset_rows.append({
            "asset": name,
            "n_trades": n_trades,
            "win_rate": round(win_rate, 4),
            "total_R": round(total_r, 2),
            "avg_R": round(avg_r, 4),
            "profit_factor": round(pf, 4),
            "sharpe": round(sharpe, 4),
            "sharpe_adj": round(sharpe_adj, 4),
            "max_dd_R": round(max_dd, 2),
            "calmar": round(calmar, 2),
            "tp": tp,
            "sl": sl,
        })

    # Portfolio aggregation (equal weight)
    combined = pd.DataFrame(all_daily_r)
    n_assets = combined.notna().sum(axis=1)
    pf_r = combined.mean(axis=1)
    pf_r = pf_r[n_assets >= 12]

    # Portfolio metrics
    total_r = float(pf_r.sum())
    avg_r = float(pf_r.mean())
    std_r = float(pf_r.std())
    sharpe = avg_r / std_r * np.sqrt(252) if std_r > 0 else 0.0
    rho = float(pf_r.autocorr()) if len(pf_r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe
    cum = pf_r.cumsum()
    dd = cum - cum.expanding().max()
    max_dd_r = float(dd.min())
    calmar = float(total_r / abs(max_dd_r)) if max_dd_r < 0 else float("inf")

    # Sortino
    downside = pf_r[pf_r < 0]
    downside_std = float(downside.std()) if len(downside) > 0 else 0.0
    sortino = avg_r / downside_std * np.sqrt(252) if downside_std > 0 else 0.0

    # Recovery factor
    recovery = total_r / abs(max_dd_r) if max_dd_r < 0 else float("inf")

    # CAGR
    n_days = len(pf_r)
    n_years = n_days / 252
    cum_growth = 1.0 + pf_r.values
    equity = np.cumprod(cum_growth)
    cagr = float(equity[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else 0.0

    # Expectancy
    expectancy = float(pf_r[pf_r != 0].mean()) if (pf_r != 0).sum() > 0 else 0.0

    # Ulcer index
    dd_series = dd.values
    ulcer = float(np.sqrt(np.mean(dd_series**2)))

    # Monthly stats
    pf_m = pf_r.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly_mean = float(pf_m.mean())
    monthly_std = float(pf_m.std())
    monthly_skew = float(pf_m.skew())
    monthly_kurt = float(pf_m.kurtosis())

    # Rolling 6-month Sharpe
    roll_sharpe = pf_r.rolling(126).apply(
        lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0.0
    )
    roll_sharpe_adj = roll_sharpe.dropna()

    # Bootstrap confidence (1000 draws)
    rng = np.random.default_rng(42)
    boot_sharpes: list[float] = []
    boot_cagrs: list[float] = []
    boot_dds: list[float] = []
    boot_8pct: list[bool] = []
    vals = pf_r.values
    for _ in range(1000):
        idx = rng.integers(0, len(vals), len(vals))
        b = vals[idx]
        b_sharpe = b.mean() / b.std() * np.sqrt(252) if b.std() > 0 else 0.0
        boot_sharpes.append(b_sharpe)
        b_equity = np.cumprod(1.0 + b)
        b_cagr = b_equity[-1] ** (1.0 / n_years) - 1.0 if n_years > 0 else 0.0
        boot_cagrs.append(b_cagr)
        b_peak = np.maximum.accumulate(b_equity)
        b_dd = (b_equity - b_peak) / b_peak
        boot_dds.append(float(b_dd.min()))
        boot_8pct.append(b_cagr > 0.08)

    baseline = {
        "portfolio": {
            "n_days": n_days,
            "n_years": round(n_years, 2),
            "total_R": round(total_r, 2),
            "avg_daily_R": round(avg_r, 6),
            "std_daily_R": round(std_r, 6),
            "sharpe": round(sharpe, 4),
            "sharpe_adj_lo": round(sharpe_adj, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 2),
            "cagr": round(cagr, 6),
            "cagr_pct": round(cagr * 100, 2),
            "max_dd_R": round(max_dd_r, 2),
            "max_dd_pct": round(max_dd_r * 100, 4),
            "recovery_factor": round(recovery, 2),
            "ulcer_index": round(ulcer, 6),
            "expectancy": round(expectancy, 6),
            "win_day_rate": round((pf_r > 0).mean(), 4),
            "profit_factor": round(abs(pf_r[pf_r > 0].sum() / pf_r[pf_r < 0].sum()), 4)
                if (pf_r < 0).sum() > 0 else float("inf"),
            "monthly_return_mean": round(monthly_mean * 100, 4),
            "monthly_return_std": round(monthly_std * 100, 4),
            "monthly_skew": round(monthly_skew, 4),
            "monthly_kurt": round(monthly_kurt, 4),
        },
        "bootstrap_ci": {
            "sharpe_95ci": [round(float(np.percentile(boot_sharpes, 2.5)), 4),
                            round(float(np.percentile(boot_sharpes, 97.5)), 4)],
            "cagr_95ci": [round(float(np.percentile(boot_cagrs, 2.5)) * 100, 2),
                          round(float(np.percentile(boot_cagrs, 97.5)) * 100, 2)],
            "max_dd_95ci": [round(float(np.percentile(boot_dds, 2.5)) * 100, 2),
                            round(float(np.percentile(boot_dds, 97.5)) * 100, 2)],
            "p_return_gt_8pct": round(float(np.mean(boot_8pct)), 4),
        },
        "rolling_sharpe": {
            "n_windows": int(roll_sharpe_adj.notna().sum()),
            "mean": round(float(roll_sharpe_adj.mean()), 4),
            "std": round(float(roll_sharpe_adj.std()), 4),
            "min": round(float(roll_sharpe_adj.min()), 4),
            "p25": round(float(roll_sharpe_adj.quantile(0.25)), 4),
            "p50": round(float(roll_sharpe_adj.quantile(0.50)), 4),
            "p75": round(float(roll_sharpe_adj.quantile(0.75)), 4),
            "max": round(float(roll_sharpe_adj.max()), 4),
            "pct_positive": round(float((roll_sharpe_adj > 0).mean()), 4),
        },
        "per_asset": per_asset_rows,
        "assets_profitable": sum(1 for a in per_asset_rows if a["total_R"] > 0),
        "assets_negative": sum(1 for a in per_asset_rows if a["total_R"] < 0),
        "assets_flat": sum(1 for a in per_asset_rows if a["total_R"] == 0),
        "total_assets": len(per_asset_rows),
        "_methodology": "Fixed-barrier R-multiples from walk-forward signal parquets. "
                        "Equal-weighted portfolio. SELL_ONLY filter applied. "
                        "R-space metrics (not % of capital). "
                        "Bootstrap: 1000 iterations with replacement.",
    }
    return baseline


def main():
    result = compute_baseline()
    path = OUTPUT_DIR / "phase1_baseline.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Baseline results → %s", path)

    p = result["portfolio"]
    print("\n" + "=" * 72)
    print("PHASE 1 — BASELINE PERFORMANCE")
    print("=" * 72)
    print(f"  Total R:           {p['total_R']:>10.2f}")
    print(f"  Sharpe (Lo-adj):   {p['sharpe_adj_lo']:>10.4f}")
    print(f"  Sortino:           {p['sortino']:>10.4f}")
    print(f"  CAGR:              {p['cagr_pct']:>10.2f}%")
    print(f"  Max DD (R):        {p['max_dd_R']:>10.2f}")
    print(f"  Calmar:            {p['calmar']:>10.2f}")
    print(f"  Win day rate:      {p['win_day_rate']:>10.2%}")
    print(f"  Recovery factor:   {p['recovery_factor']:>10.2f}")
    print(f"  Ulcer index:       {p['ulcer_index']:>10.6f}")
    print(f"  Days:              {p['n_days']:>10d}")
    print(f"  Profitable assets: {result['assets_profitable']}/{result['total_assets']}")
    print(f"  Negative assets:   {result['assets_negative']}")
    print()
    print("  Bootstrap CI (95%):")
    print(f"    Sharpe:          {result['bootstrap_ci']['sharpe_95ci']}")
    print(f"    CAGR %%:          {result['bootstrap_ci']['cagr_95ci']}")
    print(f"    Max DD %%:        {result['bootstrap_ci']['max_dd_95ci']}")
    print(f"    P(CAGR > 8%%):    {result['bootstrap_ci']['p_return_gt_8pct']:.2%}")
    print()
    print("  Rolling 126d Sharpe:")
    rs = result["rolling_sharpe"]
    print(f"    Mean: {rs['mean']:>8.4f}  Min: {rs['min']:>8.4f}  "
          f"P50: {rs['p50']:>8.4f}  Max: {rs['max']:>8.4f}")
    print(f"    Pct positive windows: {rs['pct_positive']:.1%}")
    print("=" * 72)


if __name__ == "__main__":
    main()
