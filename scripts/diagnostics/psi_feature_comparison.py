#!/usr/bin/env python3
"""\
PSI Feature Comparison: Old (0.10/0.20) vs New (0.30/0.60) thresholds.

Generates feature matrices for multiple assets using the production
pipeline, computes per-feature PSI between early (reference) and late
(current) data windows, then classifies each feature using both threshold
sets. Shows the distribution shift.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/psi_feature_comparison.py
"""

from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv
from features.regime_features import generate_regime_features
from monitoring.psi_monitor import PSIMonitor

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("psi_comparison")
warnings.filterwarnings("ignore")

# Assets to test — mix of high-PSI and low-PSI from the sweep
TEST_ASSETS = [
    ("EURUSD", "EURUSD=X"),   # moderate sweep PSI
    ("GC", "GC=F"),           # high sweep PSI
    ("USDJPY", "USDJPY=X"),   # moderate sweep PSI
    ("^DJI", "^DJI"),         # high sweep PSI
    ("AUDUSD", "AUDUSD=X"),   # low sweep PSI (0.0)
]

# Old thresholds (live monitor before P0 fix)
OLD = {"NO_DRIFT": 0.10, "MODERATE": 0.20}

# New thresholds (live monitor after P0 fix)
NEW = {"NO_DRIFT": 0.30, "MODERATE": 0.60}

# Feature families for grouping
MOMENTUM_PREFIXES = ("mom_", "_mom_")
CARRY_PREFIXES = ("carry_", "_carry_")
REGIME_PREFIXES = ("hurst", "kaufman", "adx", "compression", "session", "bb_", "ema_")
CROSS_ASSET = ("dxy_mom_", "vix_mom_", "spx_mom_", "WTI_mom_")


def classify(psi: float, no_drift: float, moderate: float) -> str:
    if psi < no_drift:
        return "NO_DRIFT"
    elif psi < moderate:
        return "MODERATE"
    return "SEVERE"


def feature_family(col: str) -> str:
    """Classify a feature column into a family group."""
    if any(c in col for c in MOMENTUM_PREFIXES):
        return "Momentum"
    if any(c in col for c in CARRY_PREFIXES):
        return "Carry"
    if col.endswith("zscore_20"):
        return "MeanRev"
    if col.endswith("vol_ratio"):
        return "Volatility"
    if col.endswith("dow_signal"):
        return "DOW"
    if col.endswith("_adx"):
        return "Regime"
    if col.endswith("_hurst"):
        return "Regime"
    if col.endswith("midpoint") or col.endswith("slope"):
        return "Structure"
    if col.startswith("dxy_") or col.startswith("vix_") or col.startswith("spx_") or col.startswith("WTI_"):
        return "CrossAsset"
    if any(c in col for c in REGIME_PREFIXES):
        return "Regime"
    if col.endswith("_k") or col.endswith("_d"):
        return "Momentum"
    if col.endswith("_pct_b"):
        return "Volatility"
    return "Other"


def main():
    all_results: list[dict] = []

    for asset_name, ticker in TEST_ASSETS:
        print(f"\n{'=' * 85}")
        print(f"  {asset_name} ({ticker})")
        print(f"{'=' * 85}")

        try:
            prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
            if prices.empty or len(prices) < 200:
                print(f"  ⚠️  Insufficient data ({len(prices) if not prices.empty else 0} rows) — skipping")
                continue

            ohlcv = fetch_asset_ohlcv(ticker)

            alpha_df = build_alpha_features(
                prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities,
            )

            if not ohlcv.empty:
                regime_df = generate_regime_features(ohlcv)
                prefix = asset_name.upper()
                regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
                full_df = alpha_df.join(regime_renamed, how="left").ffill().dropna()
            else:
                full_df = alpha_df.copy()

            if len(full_df) < 100:
                print(f"  ⚠️  Only {len(full_df)} rows after dropna — skipping")
                continue

        except Exception as e:
            print(f"  ❌ Error generating features: {e}")
            continue

        # Split into reference (first 40%) and current (last 40%) with gap
        n = len(full_df)
        ref_end = int(n * 0.40)
        cur_start = int(n * 0.60)
        X_ref = full_df.iloc[:ref_end]
        X_cur = full_df.iloc[cur_start:]
        gap_days = (full_df.index[cur_start] - full_df.index[ref_end - 1]).days if hasattr(full_df.index, '__getitem__') else 0

        print(f"    Reference: {len(X_ref)} rows → {X_ref.index[0].date()}..{X_ref.index[-1].date()}")
        print(f"    Current:   {len(X_cur)} rows → {X_cur.index[0].date()}..{X_cur.index[-1].date()}")
        print()

        # Compute per-feature PSI using PSIMonitor's compute_psi (same function as live system)
        per_feature = []
        for col in X_ref.columns:
            if col not in X_cur.columns:
                continue
            ref_s = X_ref[col]
            cur_s = X_cur[col]
            psi = PSIMonitor.compute_psi(ref_s, cur_s)
            per_feature.append((col, psi))

        # Sort by PSI descending
        per_feature.sort(key=lambda x: -x[1])

        # Count by threshold set
        old_counts = {"NO_DRIFT": 0, "MODERATE": 0, "SEVERE": 0, "TOTAL": len(per_feature)}
        new_counts = {"NO_DRIFT": 0, "MODERATE": 0, "SEVERE": 0, "TOTAL": len(per_feature)}
        family_counts_old: dict[str, dict] = {}
        family_counts_new: dict[str, dict] = {}

        for col, psi in per_feature:
            old_cls = classify(psi, OLD["NO_DRIFT"], OLD["MODERATE"])
            new_cls = classify(psi, NEW["NO_DRIFT"], NEW["MODERATE"])
            old_counts[old_cls] += 1
            new_counts[new_cls] += 1

            fam = feature_family(col)
            if fam not in family_counts_old:
                family_counts_old[fam] = {"NO_DRIFT": 0, "MODERATE": 0, "SEVERE": 0}
                family_counts_new[fam] = {"NO_DRIFT": 0, "MODERATE": 0, "SEVERE": 0}
            family_counts_old[fam][old_cls] += 1
            family_counts_new[fam][new_cls] += 1

        # Print top-10 features with both classifications
        print(f"    {'Feature':<40} {'PSI':>8} {'Old(0.10/0.20)':<16} {'New(0.30/0.60)':<16} {'Family':<12}")
        print(f"    {'-'*40} {'-'*8} {'-'*16} {'-'*16} {'-'*12}")
        for col, psi in per_feature[:10]:
            old_cls = classify(psi, OLD["NO_DRIFT"], OLD["MODERATE"])
            new_cls = classify(psi, NEW["NO_DRIFT"], NEW["MODERATE"])
            fam = feature_family(col)
            print(f"    {col:<40} {psi:>8.4f} {old_cls:<16} {new_cls:<16} {fam:<12}")
        if len(per_feature) > 10:
            print(f"    ... and {len(per_feature) - 10} more features")

        print()

        # Summary
        print(f"    {'Metric':<30} {'Old (0.10/0.20)':<20} {'New (0.30/0.60)':<20}")
        print(f"    {'-'*30} {'-'*20} {'-'*20}")
        print(f"    {'Total features':<30} {old_counts['TOTAL']:<20} {new_counts['TOTAL']:<20}")
        print(f"    {'→ NO_DRIFT':<30} {old_counts['NO_DRIFT']:<20} {new_counts['NO_DRIFT']:<20}")
        print(f"    {'→ MODERATE':<30} {old_counts['MODERATE']:<20} {new_counts['MODERATE']:<20}")
        print(f"    {'→ SEVERE':<30} {old_counts['SEVERE']:<20} {new_counts['SEVERE']:<20}")

        severe_delta = new_counts["SEVERE"] - old_counts["SEVERE"]
        print(f"    {'→ SEVERE reduction':<30} {'':<20} {'-' if severe_delta >= 0 else '+':>1}{severe_delta:<+19}")
        print()

        # Feature family breakdown
        print(f"    {'Family':<15} {'Old SEVERE':<12} {'New SEVERE':<12} {'Δ':<8} {'Old MOD':<12} {'New MOD':<12}")
        print(f"    {'-'*15} {'-'*12} {'-'*12} {'-'*8} {'-'*12} {'-'*12}")
        for fam in sorted(family_counts_old.keys()):
            o_sev = family_counts_old[fam].get("SEVERE", 0)
            n_sev = family_counts_new[fam].get("SEVERE", 0)
            o_mod = family_counts_old[fam].get("MODERATE", 0)
            n_mod = family_counts_new[fam].get("MODERATE", 0)
            delta = n_sev - o_sev
            d_str = f"{'-' if delta >= 0 else '+':>1}{delta:+d}" if abs(delta) > 0 else "  —"
            print(f"    {fam:<15} {o_sev:<12} {n_sev:<12} {d_str:<8} {o_mod:<12} {n_mod:<12}")

        print()

        # Track aggregate
        all_results.append({
            "asset": asset_name,
            "n_features": len(per_feature),
            "old_severe": old_counts["SEVERE"],
            "new_severe": new_counts["SEVERE"],
            "old_moderate": old_counts["MODERATE"],
            "new_moderate": new_counts["MODERATE"],
            "old_no_drift": old_counts["NO_DRIFT"],
            "new_no_drift": new_counts["NO_DRIFT"],
            "top_feature": per_feature[0][0] if per_feature else "",
            "top_feature_psi": round(per_feature[0][1], 4) if per_feature else 0,
        })

    # Portfolio-wide summary
    print(f"\n{'=' * 85}")
    print(f"  PORTFOLIO-WIDE PSI THRESHOLD COMPARISON")
    print(f"{'=' * 85}")
    print(f"{'Asset':<10} {'Features':<10} {'Old SEVERE':<12} {'New SEVERE':<12} {'Δ':<8} {'Old MOD':<10} {'New MOD':<10}")
    print(f"{'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*8} {'-'*10} {'-'*10}")
    total_old_sev = 0
    total_new_sev = 0
    for r in all_results:
        delta = r["new_severe"] - r["old_severe"]
        d_str = f"{'+' if abs(delta) > 0 else ' ':>1}{delta:+d}" if abs(delta) > 0 else "  —"
        print(f"{r['asset']:<10} {r['n_features']:<10} {r['old_severe']:<12} {r['new_severe']:<12} {d_str:<8} {r['old_moderate']:<10} {r['new_moderate']:<10}")
        total_old_sev += r["old_severe"]
        total_new_sev += r["new_severe"]

    print()
    total_delta = total_new_sev - total_old_sev
    print(f"  Total SEVERE features across all assets:")
    print(f"    Old thresholds (0.10/0.20): {total_old_sev}")
    print(f"    New thresholds (0.30/0.60): {total_new_sev}")
    print(f"    Reduction:                  {abs(total_delta)} ({abs(total_delta)/max(total_old_sev,1)*100:.1f}%)")
    print(f"    Crisis signal (≥3 assets with SEVERE): "
          f"{'🚨 YES (old)' if sum(1 for r in all_results if r['old_severe'] >= 3) >= 3 else '✅ NO (old)'}"
          f" → "
          f"{'🚨 YES (new)' if sum(1 for r in all_results if r['new_severe'] >= 3) >= 3 else '✅ NO (new)'}")
    print()
    print(f"  NOTE: This uses the PSIMonitor's compute_psi() on FEATURE distributions")
    print(f"  (not p_long), directly replicating the live monitoring pipeline.")


if __name__ == "__main__":
    main()
