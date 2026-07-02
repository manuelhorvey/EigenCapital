#!/usr/bin/env python3
"""
Reads walkforward/*_wf_summary.csv files and scores each ticker
for promotion to the live dashboard.

Output: ranked table to stdout + walkforward/promotion_report.json/.csv
"""

from __future__ import annotations

import json
import os
import re
import sys

import pandas as pd

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "walkforward",
)


def load_summaries() -> pd.DataFrame:
    """Load all per-asset walk-forward summaries."""
    rows = []
    for fname in os.listdir(OUTPUT_DIR):
        m = re.match(r"(.+)_wf_summary\.csv$", fname)
        if not m:
            continue
        asset = m.group(1)
        if asset == "all_assets":
            continue
        df = pd.read_csv(os.path.join(OUTPUT_DIR, fname))
        df["asset"] = asset
        rows.append(df)

    if not rows:
        print("No summary CSV files found in walkforward/")
        sys.exit(1)

    return pd.concat(rows, ignore_index=True)


def score_ticker(group: pd.DataFrame) -> dict:
    """Compute composite score and promotion status for one ticker."""
    asset = group["asset"].iloc[0]
    mean_ic = group["directional"].mean()
    hit_rate = group["hit_rate"].mean()
    flat_rate = group["flat_rate"].mean()
    long_rate = group["long_rate"].mean()
    short_rate = group["short_rate"].mean()
    n_folds = len(group)
    pos_folds = (group["directional"] > 0).sum()

    criteria_met = (
        mean_ic > 0.03
        and hit_rate > 0.40
        and flat_rate < 0.70
        and pos_folds >= n_folds / 2
        and long_rate > 0.05
        and short_rate > 0.05
    )

    ic_score = min(mean_ic / 0.10 * 40, 40)
    hr_score = min((hit_rate - 0.40) / 0.15 * 30, 30) if hit_rate > 0.40 else 0
    cons_score = pos_folds / n_folds * 20
    bi_score = min(min(long_rate, short_rate) / 0.15 * 10, 10)

    score = round(ic_score + hr_score + cons_score + bi_score, 1)

    if score >= 60 and criteria_met and mean_ic > 0:
        status = "GREEN"
        symbol = "GREEN  \u2713 PROMOTE"
    elif score >= 40 and mean_ic > 0:
        status = "YELLOW"
        symbol = "YELLOW \u25d0 WATCH"
    else:
        status = "RED"
        symbol = "RED    \u2717 SKIP"

    return {
        "ticker": asset,
        "score": score,
        "ic": round(float(mean_ic), 4),
        "hit_rate": round(float(hit_rate), 4),
        "flat_rate": round(float(flat_rate), 4),
        "long_rate": round(float(long_rate), 4),
        "short_rate": round(float(short_rate), 4),
        "positive_ic_folds": int(pos_folds),
        "total_folds": int(n_folds),
        "criteria_met": bool(criteria_met),
        "status": status,
        "symbol": symbol,
    }


def print_table(scored: list[dict]):
    """Print ranked table to stdout."""
    header = f"{'Rank':>4}  {'Ticker':<8} {'Score':>6} {'IC':>7} {'HitRate':>8} {'FlatRate':>9} {'PosFolds':>9}  Status"
    sep = "-" * len(header)
    print(f"\n{sep}")
    print("  PROMOTION SCREENING RESULTS")
    print(sep)
    print(header)
    print(sep)
    for i, s in enumerate(scored, 1):
        print(
            f"{i:>4}  {s['ticker']:<8} {s['score']:>6.1f} {s['ic']:>7.4f} "
            f"{s['hit_rate']:>8.3f} {s['flat_rate']:>9.3f} "
            f"{s['positive_ic_folds']}/{s['total_folds']:<2}  {s['symbol']}"
        )
    print(sep)
    print()


def save_report(scored: list[dict]):
    """Save promotion report as JSON and CSV."""
    green = [s for s in scored if s["status"] == "GREEN"]
    yellow = [s for s in scored if s["status"] == "YELLOW"]
    red = [s for s in scored if s["status"] == "RED"]

    report = {
        "green": green,
        "yellow": yellow,
        "red": red,
        "summary": {
            "total": len(scored),
            "green": len(green),
            "yellow": len(yellow),
            "red": len(red),
        },
    }

    report_json = os.path.join(OUTPUT_DIR, "promotion_report.json")
    with open(report_json, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved: {report_json}")

    cols = [
        "ticker",
        "score",
        "ic",
        "hit_rate",
        "flat_rate",
        "long_rate",
        "short_rate",
        "positive_ic_folds",
        "total_folds",
        "criteria_met",
        "status",
    ]
    df = pd.DataFrame(scored)[cols]
    report_csv = os.path.join(OUTPUT_DIR, "promotion_report.csv")
    df.to_csv(report_csv, index=False)
    print(f"Saved: {report_csv}")


def main():
    combined = load_summaries()

    scored = []
    for asset, group in combined.groupby("asset"):
        scored.append(score_ticker(group))

    scored.sort(key=lambda x: x["score"], reverse=True)
    print_table(scored)
    save_report(scored)


if __name__ == "__main__":
    main()
