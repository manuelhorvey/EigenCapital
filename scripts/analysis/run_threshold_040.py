"""
Proper threshold comparison using the canonical walk_forward_one() pipeline.
Runs BOTH 0.45 and 0.40 fresh with the same (fixed) code path, so the
comparison is apples-to-apples.

Usage: PYTHONPATH=$PYTHONPATH:. python scripts/analysis/run_threshold_040.py
"""

import logging
import re
import sys

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from scripts.backtest.walk_forward_all import load_macro, walk_forward_one
from scripts.training.train_all_assets import fetch_history
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DASHBOARD_TICKERS = [
    "GC=F",
    "USDCHF=X",
    "USDCAD=X",
    "ES=F",
    "NQ=F",
    "GBPCAD=X",
    "NZDCAD=X",
    "^DJI",
    "NZDUSD=X",
    "GBPAUD=X",
    "NZDCHF=X",
    "CADCHF=X",
    "AUDUSD=X",
    "EURCHF=X",
    "EURCAD=X",
    "EURNZD=X",
    "GBPCHF=X",
    "GBPUSD=X",
    "EURAUD=X",
    "USDJPY=X",
    "GBPJPY=X",
]


def normalize(t):
    t = t.strip()
    t = re.sub(r"=F$", "", t)
    t = re.sub(r"=X$", "", t)
    t = re.sub(r"^\^", "", t)
    return t


def run_threshold(ticker, macro, ref, threshold, label):
    name = normalize(ticker)
    print(f"  {name} @ {threshold}...", end=" ", flush=True)
    result = walk_forward_one(ticker, macro, ref, conf_threshold=threshold)
    if result is None:
        print("SKIPPED")
        return None
    df_w, summary = result
    df_w["ticker_norm"] = normalize(ticker)
    total_trades = int(df_w["n_trades"].sum())
    total_r = float(df_w["total_return"].sum())
    print(f"✓ {total_trades} trades, {total_r:+.4f}R total")
    return df_w


def aggregate(df):
    agg = {}
    for ticker_norm in df["ticker_norm"].unique():
        sub = df[df["ticker_norm"] == ticker_norm]
        t = int(sub["n_trades"].sum())
        wr = float(sub["win_rate"].mean())
        pf_vals = sub["profit_factor"].replace(0, np.nan)
        pf_med = float(pf_vals.median()) if pf_vals.notna().any() else 0.0
        sh = float(sub["sharpe"].mean())
        tr = float(sub["total_return"].sum())
        n_w = len(sub)
        min_t = int(sub["n_trades"].min())
        agg[ticker_norm] = {
            "trades": t,
            "wr": wr,
            "pf": pf_med,
            "sharp": sh,
            "ret": tr,
            "n_windows": n_w,
            "min_tpf": min_t,
        }
    return agg


def run():
    logging.getLogger("walkforward").setLevel(logging.WARNING)

    print("=" * 100)
    print("THRESHOLD COMPARISON: conf=0.45 vs conf=0.40 (both fresh, same code)")
    print("21 dashboard assets")
    print("=" * 100)

    macro = load_macro()
    ref = fetch_history("SPY", years=10)

    # ── Run both thresholds for all 21 dashboard assets ──
    windows_045 = []
    windows_040 = []
    failed = []

    for ticker in DASHBOARD_TICKERS:
        name = normalize(ticker)
        print(f"\n{name} ({ticker}):")

        df_045 = run_threshold(ticker, macro, ref, 0.45, "0.45")
        df_040 = run_threshold(ticker, macro, ref, 0.40, "0.40")

        if df_045 is None and df_040 is None:
            print("  → SKIPPED (insufficient data at both thresholds)")
            failed.append((ticker, "insufficient data"))
            continue

        if df_045 is not None:
            windows_045.append(df_045)
        if df_040 is not None:
            windows_040.append(df_040)

    if not windows_045 and not windows_040:
        print("\nNo assets succeeded. Exiting.")
        return

    df_all_045 = pd.concat(windows_045, ignore_index=True) if windows_045 else pd.DataFrame()
    df_all_040 = pd.concat(windows_040, ignore_index=True) if windows_040 else pd.DataFrame()

    print(
        f"\n0.45 data: {len(df_all_045)} rows, {df_all_045['ticker_norm'].nunique() if not df_all_045.empty else 0} assets"  # noqa: E501
    )  # noqa: E501
    print(
        f"0.40 data: {len(df_all_040)} rows, {df_all_040['ticker_norm'].nunique() if not df_all_040.empty else 0} assets"  # noqa: E501
    )  # noqa: E501

    # ── Aggregate and compare ──
    agg_045 = aggregate(df_all_045)
    agg_040 = aggregate(df_all_040)

    all_tickers = sorted(set(list(agg_045.keys()) + list(agg_040.keys())))

    print("\n" + "=" * 130)
    print("PER-ASSET COMPARISON: 0.45 vs 0.40 (both fresh, fixed signal encoding)")
    print("=" * 130)
    print(
        f"{'Asset':>10s}  {'T045':>6s}  {'T040':>6s}  {'ΔT':>5s}  {'WR045':>7s}  {'WR040':>7s}  {'PF045':>6s}  {'PF040':>6s}  {'Sh045':>7s}  {'Sh040':>7s}  {'R045':>9s}  {'R040':>9s}  {'ΔR':>10s}  {'MinT':>4s}"  # noqa: E501
    )  # noqa: E501
    print("-" * 120)

    results_list = []
    for ticker_norm in sorted(all_tickers):
        a45 = agg_045.get(ticker_norm, {})
        a40 = agg_040.get(ticker_norm, {})

        t45 = a45.get("trades", 0)
        t40 = a40.get("trades", 0)
        wr45 = a45.get("wr", 0)
        wr40 = a40.get("wr", 0)
        pf45 = a45.get("pf", 0)
        pf40 = a40.get("pf", 0)
        sh45 = a45.get("sharp", 0)
        sh40 = a40.get("sharp", 0)
        r45 = a45.get("ret", 0)
        r40 = a40.get("ret", 0)
        min_t = a40.get("min_tpf", 0)

        dt = t40 - t45
        dr = r40 - r45

        results_list.append(
            {
                "ticker": ticker_norm,
                "t045": t45,
                "t040": t40,
                "dt": dt,
                "wr045": wr45,
                "wr040": wr40,
                "pf045": pf45,
                "pf040": pf40,
                "sh045": sh45,
                "sh040": sh40,
                "r045": r45,
                "r040": r40,
                "dr": dr,
                "min_tpf_040": min_t,
            }
        )

        print(
            f"{ticker_norm:>10s}  {t45:>6d}  {t40:>6d}  {dt:+5d}  {wr45:>6.1%}  {wr40:>6.1%}  {pf45:>5.2f}  {pf40:>5.2f}  {sh45:>+6.3f}  {sh40:>+6.3f}  {r45:>+8.4f}  {r40:>+8.4f}  {dr:>+9.4f}  {min_t:>3d}"  # noqa: E501
        )  # noqa: E501

    # ── Portfolio totals ──
    print("\n" + "=" * 130)
    print("PORTFOLIO-LEVEL TOTALS (21 dashboard assets)")
    print("=" * 130)

    if results_list:
        p_t45 = sum(r["t045"] for r in results_list)
        p_t40 = sum(r["t040"] for r in results_list)
        p_r45 = sum(r["r045"] for r in results_list)
        p_r40 = sum(r["r040"] for r in results_list)

        print(
            f"\n  Total trades:       {p_t45:,} → {p_t40:,} ({p_t40 - p_t45:+d}, {(p_t40 - p_t45) / max(p_t45, 1) * 100:+.1f}%)"  # noqa: E501
        )  # noqa: E501
        print(f"  Portfolio return:   {p_r45:+.4f}R → {p_r40:+.4f}R ({p_r40 - p_r45:+.4f}R)")

        avg_sh45 = np.mean([r["sh045"] for r in results_list if abs(r["sh045"]) < 100])
        avg_sh40 = np.mean([r["sh040"] for r in results_list if abs(r["sh040"]) < 100])
        print(f"  Avg Sharpe:         {avg_sh45:+.4f} → {avg_sh40:+.4f}")
        print(
            f"  Assets +return:     {sum(1 for r in results_list if r['r045'] > 0)}/{len(results_list)} → {sum(1 for r in results_list if r['r040'] > 0)}/{len(results_list)}"  # noqa: E501
        )  # noqa: E501
        print(
            f"  Assets +Sharpe:     {sum(1 for r in results_list if r['sh045'] > 0)}/{len(results_list)} → {sum(1 for r in results_list if r['sh040'] > 0)}/{len(results_list)}"  # noqa: E501
        )  # noqa: E501

        degraded = [r for r in results_list if r["dr"] < -0.01]
        improved = [r for r in results_list if r["dr"] > 0.01]
        print(f"\n  Degraded (ΔR < -0.01): {len(degraded)}")
        for r in sorted(degraded, key=lambda x: x["dr"]):
            print(f"    {r['ticker']}: {r['r045']:+.4f}R → {r['r040']:+.4f}R (Δ{r['dr']:+.4f})")
        print(f"  Improved (ΔR > +0.01): {len(improved)}")
        for r in sorted(improved, key=lambda x: x["dr"], reverse=True):
            print(f"    {r['ticker']}: {r['r045']:+.4f}R → {r['r040']:+.4f}R (Δ{r['dr']:+.4f})")

        btest = sum(1 for r in results_list if r["min_tpf_040"] >= 5)
        print(f"  Backtestable (min trades/fold >= 5): {btest}/{len(results_list)}")

        # ── Recommendations ──
        ADOPT_R_THRESH = 0.05
        KEEP_R_THRESH = -0.05
        MIN_TRADES = 20

        print("\n" + "=" * 130)
        print("RECOMMENDATIONS (21 dashboard assets)")
        print("=" * 130)
        print(
            f"  Criteria: ΔR > +{ADOPT_R_THRESH} & T040>={MIN_TRADES} → ADOPT  |  "
            f"ΔR < {KEEP_R_THRESH} & T040>={MIN_TRADES} → KEEP  |  else → MIXED"
        )
        adopt, keep, mixed = [], [], []
        for r in results_list:
            if r["dr"] > ADOPT_R_THRESH and r["t040"] >= MIN_TRADES:
                adopt.append(r)
            elif r["dr"] < KEEP_R_THRESH and r["t040"] >= MIN_TRADES:
                keep.append(r)
            else:
                mixed.append(r)

        print(f"\n  ✅ ADOPT 0.40 ({len(adopt)}): {', '.join(sorted(r['ticker'] for r in adopt)) or '(none)'}")
        print(f"  ⚠️ KEEP 0.45  ({len(keep)}): {', '.join(sorted(r['ticker'] for r in keep)) or '(none)'}")
        print(f"  ⚠️ MIXED      ({len(mixed)}): {', '.join(sorted(r['ticker'] for r in mixed))}")
        if mixed:
            print("    Breakdown:")
            no_data = [r for r in mixed if r["t040"] < MIN_TRADES]
            marginal = [r for r in mixed if r["t040"] >= MIN_TRADES]
            if no_data:
                print(
                    f"      • Insufficient trades (T040 < {MIN_TRADES}): {', '.join(sorted(r['ticker'] for r in no_data))}"  # noqa: E501
                )  # noqa: E501
            if marginal:
                print(
                    f"      • Marginal/neutral (|ΔR| <= {ADOPT_R_THRESH}): {', '.join(sorted(r['ticker'] for r in marginal))}"  # noqa: E501
                )  # noqa: E501
    else:
        print("\n  No dashboard assets produced results.")

    if failed:
        print(f"\n  Failed/skipped assets ({len(failed)}):")
        for t, reason in failed:
            print(f"    {t}: {reason}")

    out_path = Path(PROJECT_ROOT) / "data" / "processed" / "threshold_040_comparison.csv"
    pd.DataFrame(results_list).to_csv(out_path, index=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    run()
