#!/usr/bin/env python3
"""
MFE Stationarity & Walk-Forward Retrace Stability Test.

Validates whether the trailing stop improvement is robust to:
  1. MFE distribution drift across time periods
  2. Walk-forward retrace optimization (period A → period B)
  3. Regime transition effects (trending vs ranging)

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/mfe_stationarity.py
"""

import json
from pathlib import Path

import numpy as np


def simulate_trailing(trades: list[dict], retrace_pct: float = 0.50):
    total = 0.0
    for t in trades:
        orig = t["r_multiple"]
        if retrace_pct <= 0:
            total += orig
            continue
        mfe_r = t.get("mfe_r", 0.0)
        if orig >= 0 or mfe_r < 0.5 or t.get("exit_reason") == "tp":
            total += orig
        else:
            captured = mfe_r * (1.0 - retrace_pct)
            total += max(captured, 0)
    return total


def portfolio_r(all_trades: dict, retrace_pct: float = 0.50):
    return sum(simulate_trailing(ts, retrace_pct) for ts in all_trades.values())


# ─────────────────────────────────────────────────────────────
# 1. MFE STATIONARITY TEST
# ─────────────────────────────────────────────────────────────
def mfe_stationarity(all_trades: dict) -> dict:
    """Compare MFE distributions between early and late halves."""
    flat = []
    for asset, ts in all_trades.items():
        for t in ts:
            flat.append({**t, "asset": asset})
    flat.sort(key=lambda x: x["entry_date"])

    mid = len(flat) // 2
    early = flat[:mid]
    late = flat[mid:]

    def mfe_stats(trades):
        mfes = np.array([t.get("mfe_r", 0) for t in trades])
        return {
            "n": len(mfes),
            "mean_mfe": float(mfes.mean()),
            "median_mfe": float(np.median(mfes)),
            "p25_mfe": float(np.percentile(mfes, 25)),
            "p75_mfe": float(np.percentile(mfes, 75)),
            "p95_mfe": float(np.percentile(mfes, 95)),
            "std_mfe": float(mfes.std()),
        }

    early_stats = mfe_stats(early)
    late_stats = mfe_stats(late)

    # KS test for distribution shift
    from scipy.stats import ks_2samp

    ks_stat, ks_p = ks_2samp(
        [t.get("mfe_r", 0) for t in early],
        [t.get("mfe_r", 0) for t in late],
    )

    # Trailing benefit in each half
    def half_pf(trades):
        by_asset: dict[str, list] = {}
        for t in trades:
            by_asset.setdefault(t["asset"], []).append(t)
        return {
            "fixed": round(sum(sum(t2["r_multiple"] for t2 in ts) for ts in by_asset.values()), 1),
            "trail_50": round(portfolio_r(by_asset, 0.50), 1),
        }

    early_pf = half_pf(early)
    late_pf = half_pf(late)

    return {
        "n_early": early_stats["n"],
        "n_late": late_stats["n"],
        "early_mfe_mean": early_stats["mean_mfe"],
        "late_mfe_mean": late_stats["mean_mfe"],
        "early_mfe_median": early_stats["median_mfe"],
        "late_mfe_median": late_stats["median_mfe"],
        "early_mfe_p95": early_stats["p95_mfe"],
        "late_mfe_p95": late_stats["p95_mfe"],
        "early_mfe_std": early_stats["std_mfe"],
        "late_mfe_std": late_stats["std_mfe"],
        "ks_statistic": round(ks_stat, 4),
        "ks_pvalue": round(ks_p, 4),
        "ks_passed": ks_p > 0.05,
        "early_fixed": early_pf["fixed"],
        "early_trail": early_pf["trail_50"],
        "late_fixed": late_pf["fixed"],
        "late_trail": late_pf["trail_50"],
    }


# ─────────────────────────────────────────────────────────────
# 2. WALK-FORWARD RETRACE STABILITY
# ─────────────────────────────────────────────────────────────
def wf_retrace_stability(all_trades: dict) -> dict:
    """Optimize retrace on period A, test on period B (2-fold split)."""
    flat = []
    for asset, ts in all_trades.items():
        for t in ts:
            flat.append({**t, "asset": asset})
    flat.sort(key=lambda x: x["entry_date"])

    mid = len(flat) // 2
    period_a = flat[:mid]
    period_b = flat[mid:]

    def by_asset(trades):
        d: dict[str, list] = {}
        for t in trades:
            d.setdefault(t["asset"], []).append(t)
        return d

    assets_a = by_asset(period_a)
    assets_b = by_asset(period_b)

    # Find optimal retrace on period A
    results = []
    for rp in [0.25, 0.33, 0.40, 0.50, 0.60, 0.67, 0.75]:
        pf_a = portfolio_r(assets_a, rp)
        pf_b = portfolio_r(assets_b, rp)
        results.append({"retrace": rp, "pf_a": round(pf_a, 1), "pf_b": round(pf_b, 1)})

    # Find best retrace for each period
    best_a = max(results, key=lambda x: x["pf_a"])
    best_b = max(results, key=lambda x: x["pf_b"])

    # How much does the optimal retrace vary?
    pfs_for_best_a = [r["pf_b"] for r in results if r["retrace"] == best_a["retrace"]]
    best_a_on_b = pfs_for_best_a[0] if pfs_for_best_a else 0

    return {
        "period_a_n": len(period_a),
        "period_b_n": len(period_b),
        "best_retrace_a": best_a["retrace"],
        "best_pf_a": best_a["pf_a"],
        "best_retrace_b": best_b["retrace"],
        "best_pf_b": best_b["pf_b"],
        "best_a_on_b_pf": best_a_on_b,
        "fixed_a": round(portfolio_r(assets_a, 0.0), 1),
        "fixed_b": round(portfolio_r(assets_b, 0.0), 1),
        "sweep": results,
    }


# ─────────────────────────────────────────────────────────────
# 3. REGIME TRANSITION TEST
# ─────────────────────────────────────────────────────────────
def regime_transition_test(all_trades: dict) -> dict:
    """Compare trailing benefit on losers-with-MFE across assets.

    Tests whether the reversal pattern (MFE >= 1.0R on losers) is
    distributed across time or concentrated in specific regimes."""
    flat = []
    for asset, ts in all_trades.items():
        for t in ts:
            flat.append({**t, "asset": asset})
    flat.sort(key=lambda x: x["entry_date"])

    # Split into quartiles and track MFE pattern per quartile
    n = len(flat)
    quartiles = []
    for i in range(4):
        q = flat[i * n // 4 : (i + 1) * n // 4] if i < 3 else flat[3 * n // 4 :]
        losers = [t for t in q if t["r_multiple"] <= 0]
        losers_with_mfe = [t for t in losers if t.get("mfe_r", 0) >= 1.0]

        def pf(ts):
            by_a: dict = {}
            for t in ts:
                by_a.setdefault(t["asset"], []).append(t)
            return {
                "fixed": round(sum(sum(t2["r_multiple"] for t2 in v) for v in by_a.values()), 1),
                "trail_50": round(portfolio_r(by_a, 0.50), 1),
            }

        start_date = q[0]["entry_date"] if q else "?"
        end_date = q[-1]["entry_date"] if q else "?"
        quartiles.append(
            {
                "period": f"Q{i + 1} ({start_date[:7]} → {end_date[:7]})",
                "n_trades": len(q),
                "n_losers": len(losers),
                "losers_with_mfe_gt1": len(losers_with_mfe),
                "pct_losers_with_mfe": round(len(losers_with_mfe) / max(len(losers), 1) * 100, 1),
            }
        )

    return {"quartiles": quartiles}


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
CAVEAT = (
    "\n*** CAVEAT: MFE stationarity walk-forward uses realized (post-hoc) MFE.\n"
    "*** Live trading has no access to the ultimate MFE when setting the trail.\n"
    "*** The retrace stability test still validates the relative ordering across\n"
    "*** regimes — a stable ordering is necessary (not sufficient) for live edge.\n"
    "*** See audit finding C8/H9 in AGENTS.md.\n"
)


def main():
    print(CAVEAT)
    path = Path("data/processed/trade_lifecycle_results.json")
    if not path.exists():
        print(f"File not found: {path}")
        return

    with open(path) as f:
        data = json.load(f)
    all_trades = data["_trades"]

    print("=" * 72)
    print("MFE STATIONARITY & RETRACE STABILITY TEST")
    print("=" * 72)

    # 1. MFE stationarity
    print("\n[1/3] MFE STATIONARITY (early vs late half)")
    s = mfe_stationarity(all_trades)
    print(
        f"  Early half:  N={s['n_early']:>5d}  mean MFE={s['early_mfe_mean']:>6.2f}R  "
        f"median={s['early_mfe_median']:>5.2f}R  p95={s['early_mfe_p95']:>5.2f}R  "
        f"std={s['early_mfe_std']:>5.2f}"
    )
    print(
        f"  Late half:   N={s['n_late']:>5d}  mean MFE={s['late_mfe_mean']:>6.2f}R  "
        f"median={s['late_mfe_median']:>5.2f}R  p95={s['late_mfe_p95']:>5.2f}R  "
        f"std={s['late_mfe_std']:>5.2f}"
    )
    print(
        f"  KS test:     statistic={s['ks_statistic']:.4f}  p={s['ks_pvalue']:.4f}  "
        f"{'PASS' if s['ks_passed'] else 'FAIL'} (H0: same distribution)"
    )
    print("")
    print(
        f"  Early:  fixed={s['early_fixed']:>+8.1f}R  trailing={s['early_trail']:>+8.1f}R  "
        f"Δ={s['early_trail'] - s['early_fixed']:+>+8.1f}"
    )
    print(
        f"  Late:   fixed={s['late_fixed']:>+8.1f}R  trailing={s['late_trail']:>+8.1f}R  "
        f"Δ={s['late_trail'] - s['late_fixed']:+>+8.1f}"
    )

    # 2. Walk-forward retrace stability
    print("\n[2/3] WALK-FORWARD RETRACE STABILITY (optimize period A → test period B)")
    wf = wf_retrace_stability(all_trades)
    print(f"  Period A: N={wf['period_a_n']}, fixed={wf['fixed_a']:+>+7.1f}R")
    print(f"  Period B: N={wf['period_b_n']}, fixed={wf['fixed_b']:+>+7.1f}R")
    print("")
    print(
        f"  Best retrace on A: {wf['best_retrace_a'] * 100:.0f}% → "
        f"{wf['best_pf_a']:+>+7.1f}R (B result: {wf['best_a_on_b_pf']:+>+7.1f}R)"
    )
    print(f"  Best retrace on B: {wf['best_retrace_b'] * 100:.0f}% → {wf['best_pf_b']:+>+7.1f}R")
    print("")
    print("  Retrace sweep:")
    print(f"  {'Retrace':<10} {'PF_A':>10} {'PF_B':>10}")
    print(f"  {'-' * 30}")
    for r in wf["sweep"]:
        print(f"  {r['retrace'] * 100:.0f}%{'':7s} {r['pf_a']:>+10.1f} {r['pf_b']:>+10.1f}")

    # 3. Regime transition
    print("\n[3/3] REGIME TRANSITION — reversal pattern by quartile")
    rt = regime_transition_test(all_trades)
    print(f"  {'Period':<30} {'N':>5} {'Losers':>7} {'MFE>1R':>8} {'%':>5}")
    print(f"  {'-' * 55}")
    for q in rt["quartiles"]:
        print(
            f"  {q['period']:<30} {q['n_trades']:>5d} {q['n_losers']:>7d} "
            f"{q['losers_with_mfe_gt1']:>7d} {q['pct_losers_with_mfe']:>4.1f}%"
        )

    print("\n" + "=" * 72)
    print("DONE")
    print("=" * 72)


if __name__ == "__main__":
    main()
