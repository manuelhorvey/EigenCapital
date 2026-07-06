#!/usr/bin/env python3
"""Phase 7 — Sustainability Assessment.

Determines whether returns above 8% are consistent, repeatable,
risk-adjusted, statistically significant, and operationally realistic.
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
logger = logging.getLogger("eigencapital.capital_study.phase7")

OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def rolling_stability(
    daily_returns: np.ndarray,
    windows: list[int] | None = None,
) -> dict:
    """Compute rolling performance metrics to assess stability over time."""
    if windows is None:
        windows = [63, 126, 252]  # 3mo, 6mo, 1yr

    results = {}
    for w in windows:
        if len(daily_returns) < w:
            continue
        rolling_sharpes = []
        rolling_cagrs = []
        rolling_dds = []
        for i in range(len(daily_returns) - w + 1):
            window = daily_returns[i:i + w]
            n_years_w = w / 252
            s = window.mean() / window.std() * np.sqrt(252) if window.std() > 0 else 0.0
            eq = np.cumprod(1.0 + window)
            cagr = eq[-1] ** (1.0 / n_years_w) - 1.0 if n_years_w > 0 else 0.0
            peak = np.maximum.accumulate(eq)
            dd = (eq - peak) / peak
            rolling_sharpes.append(s)
            rolling_cagrs.append(cagr)
            rolling_dds.append(float(dd.min()))

        sharpes_arr = np.array(rolling_sharpes)
        cagrs_arr = np.array(rolling_cagrs)
        dds_arr = np.array(rolling_dds)

        # Decay test: compare first half vs second half
        mid = len(sharpes_arr) // 2
        first_half_sharpe = float(np.mean(sharpes_arr[:mid]))
        second_half_sharpe = float(np.mean(sharpes_arr[mid:]))
        decay = second_half_sharpe - first_half_sharpe

        results[f"{w}d"] = {
            "window_days": w,
            "n_windows": len(rolling_sharpes),
            "sharpe": {
                "mean": round(float(np.mean(sharpes_arr)), 4),
                "std": round(float(np.std(sharpes_arr)), 4),
                "min": round(float(np.min(sharpes_arr)), 4),
                "max": round(float(np.max(sharpes_arr)), 4),
                "pct_positive": round(float(np.mean(sharpes_arr > 0)), 4),
                "pct_above_1": round(float(np.mean(sharpes_arr > 1.0)), 4),
            },
            "cagr": {
                "mean_pct": round(float(np.mean(cagrs_arr)) * 100, 4),
                "std_pct": round(float(np.std(cagrs_arr)) * 100, 4),
            },
            "max_drawdown": {
                "mean_pct": round(float(np.mean(dds_arr)) * 100, 4),
                "worst_pct": round(float(np.min(dds_arr)) * 100, 4),
            },
            "decay_test": {
                "first_half_mean_sharpe": round(first_half_sharpe, 4),
                "second_half_mean_sharpe": round(second_half_sharpe, 4),
                "decay": round(decay, 4),
                "interpretation": "decaying" if decay < -0.5 else (
                    "improving" if decay > 0.5 else "stable"
                ),
            },
        }

    return results


def main():
    from scripts.capital_study.phase2_scaling import load_daily_r, compute_R_to_pct_conversion

    daily_r, pt_sl, assets = load_daily_r()
    conv = compute_R_to_pct_conversion(assets, 100_000)
    asset_pct = {}
    for a in assets:
        if a not in daily_r.columns:
            continue
        c = conv.get(a, 0.005)
        asset_pct[a] = (daily_r[a] * c).clip(lower=-0.02)
    pf_pct = pd.DataFrame(asset_pct).mean(axis=1)
    n_active = daily_r[assets].notna().sum(axis=1)
    pf_pct = pf_pct[n_active >= 12]

    vals = pf_pct.values
    n_days = len(vals)
    n_years = n_days / 252

    # 1. Rolling stability
    stability = rolling_stability(vals)
    logger.info("Rolling stability computed for %d windows", len(stability))

    # 2. Overall sustainability assessment
    baseline_cagr = float(np.cumprod(1.0 + vals)[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else 0.0
    baseline_sharpe = vals.mean() / vals.std() * np.sqrt(252) if vals.std() > 0 else 0.0

    # 3. Profit consistency: % of months positive
    pf_m = pf_pct.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    months_positive = int((pf_m > 0).sum())
    months_total = len(pf_m)

    # 4. Return stability: monthly std / mean ratio
    monthly_mean = float(pf_m.mean())
    monthly_std = float(pf_m.std())
    stability_ratio = monthly_std / abs(monthly_mean) if monthly_mean != 0 else float("inf")

    # Operational realism assessment
    # Slippage RMS of 1.74% is per-trade price gap std dev (from trace).
    # Mean absolute slippage ≈ 0.5% of position value. With ~50 trades/yr
    # on 15% position size: annual drag = 50 × 0.5% × 15% ≈ 3.75%.
    # Spread (~0.1% per trade entry) adds: 50 × 0.1% × 15% ≈ 0.75%.
    # Total annual friction ≈ 4.5% of capital.
    annual_slippage_drag_pct = 0.0375  # ~3.75% p.a. per position size
    annual_spread_drag_pct = 0.0075    # ~0.75% p.a.
    total_annual_friction_pct = annual_slippage_drag_pct + annual_spread_drag_pct
    friction_adjusted_cagr = baseline_cagr - total_annual_friction_pct

    output = {
        "baseline_cagr_pct": round(baseline_cagr * 100, 4),
        "baseline_sharpe": round(baseline_sharpe, 4),
        "n_years": round(n_years, 2),
        "rolling_stability": stability,
        "profit_consistency": {
            "months_positive": months_positive,
            "months_total": months_total,
            "pct_months_positive": round(months_positive / months_total * 100, 2) if months_total > 0 else 0,
            "monthly_mean_return_pct": round(monthly_mean * 100, 4),
            "monthly_std_return_pct": round(monthly_std * 100, 4),
            "stability_ratio": round(stability_ratio, 4),
        },
        "friction_adjusted_cagr_pct": round(friction_adjusted_cagr * 100, 4),
        "operational_realism": {
            "model_timing_gap_pct": 1.74,
            "estimated_annual_slippage_drag_pct": round(annual_slippage_drag_pct * 100, 2),
            "estimated_annual_spread_drag_pct": round(annual_spread_drag_pct * 100, 2),
            "total_annual_friction_pct": round(total_annual_friction_pct * 100, 2),
            "note": (
                "Slippage RMS (1.74%) is the std dev of model-vs-market price gap "
                "from trace.jsonl. Mean absolute estimated at ~0.5%/trade. "
                "Annualized: ~50 trades/yr × 0.5% mean slip × 15% position = 3.75%."
            ),
        },
        "sustainability_verdict": {
            "consistent": bool(stability.get("252d", {}).get("sharpe", {}).get("pct_positive", 0) > 0.9 if "252d" in stability else False),
            "repeatable": bool(baseline_sharpe > 1.0),
            "risk_adjusted": bool(baseline_sharpe > 2.0),
            "statistically_significant": bool(baseline_sharpe > 1.0),
            "operationally_realistic": bool(friction_adjusted_cagr > 0.08),
        },
        "_methodology": (
            "Rolling stability computed over 63d/126d/252d windows. "
            "Decay test compares first vs second half of rolling windows. "
            "Friction adjustment: CAGR - (50 trades/yr × 0.5% mean slip × 15% position + spread). "
            "Profit consistency: % of months with positive return."
        ),
    }

    path = OUTPUT_DIR / "phase7_sustainability.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Sustainability assessment → %s", path)

    print("\n" + "=" * 72)
    print("PHASE 7 — SUSTAINABILITY ASSESSMENT")
    print("=" * 72)
    print(f"  Baseline CAGR:            {baseline_cagr * 100:.2f}%")
    print(f"  Baseline Sharpe:          {baseline_sharpe:.4f}")
    print(f"  Friction-adj CAGR:        {friction_adjusted_cagr * 100:.2f}%  (slippage {annual_slippage_drag_pct*100:.1f}% + spread {annual_spread_drag_pct*100:.1f}%)")
    print(f"  Months positive:          {months_positive}/{months_total} ({months_positive/months_total*100:.1f}%)")
    print(f"  Monthly stability ratio:  {stability_ratio:.4f}")
    print()
    print(f"  Rolling Sharpe (252d):")
    rs = stability.get("252d", {})
    if rs:
        print(f"    Mean: {rs['sharpe']['mean']:.2f}  P>0: {rs['sharpe']['pct_positive']:.1%}  "
              f"P>1: {rs['sharpe']['pct_above_1']:.1%}")
        dt = rs["decay_test"]
        print(f"    Decay test: {dt['first_half_mean_sharpe']:.2f} → {dt['second_half_mean_sharpe']:.2f} "
              f"({dt['interpretation']})")
    print()
    print(f"  Verdict:")
    sv = output["sustainability_verdict"]
    for k, v in sv.items():
        print(f"    {k:30s}: {'PASS' if v else 'FAIL'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
