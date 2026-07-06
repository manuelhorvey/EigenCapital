#!/usr/bin/env python3
"""Phase 4 — Risk Analysis.

Evaluates whether returns above 8% are achieved without unacceptable
risk increases. Compares risk metrics across all capital scenarios.
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
logger = logging.getLogger("eigencapital.capital_study.phase4")

OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CAPITAL_SCENARIOS = [100_000, 125_000, 150_000, 200_000, 300_000, 600_000, 1_000_000]
LABELS = ["baseline", "plus_25pct", "plus_50pct", "plus_100pct", "plus_200pct", "plus_500pct", "plus_1000pct"]


def compute_risk_metrics(pf_pct: pd.Series) -> dict:
    """Compute comprehensive risk metrics from daily %-return series."""
    vals = pf_pct.values
    n_days = len(vals)
    if n_days == 0:
        return {}

    # Compound growth
    cum_growth = np.cumprod(1.0 + vals)
    peak = np.maximum.accumulate(cum_growth)
    dd_pct = (cum_growth - peak) / peak

    # Drawdown metrics
    max_dd = float(dd_pct.min())
    avg_dd = float(dd_pct.mean())
    dd_duration = []
    current_dd_length = 0
    for d in dd_pct:
        if d < 0:
            current_dd_length += 1
        else:
            if current_dd_length > 0:
                dd_duration.append(current_dd_length)
            current_dd_length = 0
    if current_dd_length > 0:
        dd_duration.append(current_dd_length)
    avg_recovery_days = float(np.mean(dd_duration)) if dd_duration else 0.0
    max_recovery_days = float(np.max(dd_duration)) if dd_duration else 0.0

    # VaR / CVaR
    sorted_vals = np.sort(vals)
    var_95 = float(sorted_vals[int(len(sorted_vals) * 0.05)])
    var_99 = float(sorted_vals[int(len(sorted_vals) * 0.01)])
    n_var_95 = max(int(len(sorted_vals) * 0.05), 1)
    n_var_99 = max(int(len(sorted_vals) * 0.01), 1)
    cvar_95 = float(np.mean(sorted_vals[:n_var_95]))
    cvar_99 = float(np.mean(sorted_vals[:n_var_99]))

    # Volatility
    daily_vol = float(vals.std())
    annualized_vol = daily_vol * np.sqrt(252)

    # Tail risk
    skewness = float(pd.Series(vals).skew())
    kurtosis = float(pd.Series(vals).kurtosis())

    # Consecutive losses
    losses = vals < 0
    max_consec_losses = 0
    current_streak = 0
    for l in losses:
        if l:
            current_streak += 1
            max_consec_losses = max(max_consec_losses, current_streak)
        else:
            current_streak = 0

    # Loss rate
    loss_days = int(np.sum(losses))
    loss_rate = loss_days / n_days if n_days > 0 else 0.0

    # Ulcer index
    ulcer_index = float(np.sqrt(np.mean(dd_pct ** 2)))

    return {
        "max_drawdown_pct": round(max_dd * 100, 4),
        "avg_drawdown_pct": round(avg_dd * 100, 4),
        "avg_recovery_days": round(avg_recovery_days, 1),
        "max_recovery_days": round(max_recovery_days, 1),
        "daily_volatility_pct": round(daily_vol * 100, 4),
        "annualized_volatility_pct": round(annualized_vol * 100, 4),
        "var_95_daily_pct": round(var_95 * 100, 4),
        "var_99_daily_pct": round(var_99 * 100, 4),
        "cvar_95_daily_pct": round(cvar_95 * 100, 4),
        "cvar_99_daily_pct": round(cvar_99 * 100, 4),
        "skewness": round(skewness, 4),
        "excess_kurtosis": round(kurtosis, 4),
        "max_consecutive_losses": max_consec_losses,
        "loss_days": loss_days,
        "loss_rate": round(loss_rate, 4),
        "ulcer_index": round(ulcer_index * 100, 4),
    }


def main():
    from scripts.capital_study.phase2_scaling import load_daily_r, compute_R_to_pct_conversion

    daily_r, pt_sl, assets = load_daily_r()
    logger.info("Loaded %d assets, %d days for risk analysis", len(assets), len(daily_r))

    results = {}
    for capital, label in zip(CAPITAL_SCENARIOS, LABELS):
        conv = compute_R_to_pct_conversion(assets, capital)
        asset_pct = {}
        for a in assets:
            if a not in daily_r.columns:
                continue
            c = conv.get(a, 0.005)
            pct = daily_r[a] * c
            asset_pct[a] = pct.clip(lower=-0.02)
        pf_pct = pd.DataFrame(asset_pct).mean(axis=1)
        n_active = daily_r[assets].notna().sum(axis=1)
        pf_pct = pf_pct[n_active >= min(12, len(assets))]

        risk_metrics = compute_risk_metrics(pf_pct)
        risk_metrics["scenario"] = label
        risk_metrics["capital"] = capital
        results[label] = risk_metrics
        logger.info(
            "  %s: max_dd=%.2f%% VaR95=%.4f%% CVaR95=%.4f%% max_consec=%d",
            label,
            risk_metrics["max_drawdown_pct"],
            risk_metrics["var_95_daily_pct"],
            risk_metrics["cvar_95_daily_pct"],
            risk_metrics["max_consecutive_losses"],
        )

    # Summary comparison: risk ratios vs baseline
    baseline = results.get("baseline", {})
    comparison = {}
    for label, metrics in results.items():
        if label == "baseline":
            continue
        if baseline:
            comparison[label] = {
                "dd_ratio": round(
                    metrics["max_drawdown_pct"] / baseline.get("max_drawdown_pct", 1.0)
                    if baseline.get("max_drawdown_pct", 0) != 0 else 0, 2
                ),
                "vol_ratio": round(
                    metrics["annualized_volatility_pct"] / baseline.get("annualized_volatility_pct", 1.0)
                    if baseline.get("annualized_volatility_pct", 0) != 0 else 0, 2
                ),
                "var95_ratio": round(
                    metrics["var_95_daily_pct"] / baseline.get("var_95_daily_pct", 1.0)
                    if baseline.get("var_95_daily_pct", 0) != 0 else 0, 2
                ),
            }

    output = {
        "per_scenario": results,
        "risk_comparison_vs_baseline": comparison,
        "baseline_summary": {"scenario": "baseline", **baseline} if baseline else {},
        "_methodology": (
            "Daily %-returns from ATR_pct-converted R-multiples. "
            "Risk metrics computed in %-space for capital-meaningful comparison. "
            "VaR and CVaR are daily. Drawdown is peak-to-trough of compounded equity."
        ),
    }

    path = OUTPUT_DIR / "phase4_risk.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Risk analysis → %s", path)

    print("\n" + "=" * 72)
    print("PHASE 4 — RISK ANALYSIS")
    print("=" * 72)
    header = f"{'Scenario':<15s} {'Max DD%':>8s} {'Ann Vol%':>8s} {'VaR95%':>8s} {'CVaR95%':>8s} {'Max Cons':>8s} {'Loss Rt':>8s}"
    print(header)
    print("-" * 72)
    for label in LABELS:
        m = results.get(label, {})
        print(f"{label:<15s} {m.get('max_drawdown_pct', 0):>7.2f}% {m.get('annualized_volatility_pct', 0):>7.2f}% "
              f"{m.get('var_95_daily_pct', 0):>7.4f}% {m.get('cvar_95_daily_pct', 0):>7.4f}% "
              f"{m.get('max_consecutive_losses', 0):>8d} {m.get('loss_rate', 0):>7.2%}")
    print("=" * 72)

    if comparison:
        print(f"\n  Risk ratios (vs baseline):")
        for scenario, ratios in comparison.items():
            print(f"    {scenario:<15s}: DD={ratios['dd_ratio']:.2f}x Vol={ratios['vol_ratio']:.2f}x VaR95={ratios['var95_ratio']:.2f}x")


if __name__ == "__main__":
    main()
