#!/usr/bin/env python3
"""
Reads walkforward/promotion_report.json and writes
walkforward/PROMOTION_REPORT.md with full breakdown.
"""

from __future__ import annotations

import json
import os

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "walkforward",
)


def load_report() -> dict:
    path = os.path.join(OUTPUT_DIR, "promotion_report.json")
    with open(path) as f:
        return json.load(f)

def load_ticker_map() -> dict:
    path = os.path.join(OUTPUT_DIR, "ticker_map.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def note_reason(s: dict) -> str:
    """Generate a one-line note on what's holding a YELLOW/Red ticker back."""
    reasons = []
    if s["ic"] <= 0.03:
        reasons.append(f"IC={s['ic']:.4f} below 0.03 threshold")
    if s["hit_rate"] <= 0.40:
        reasons.append(f"hit rate {s['hit_rate']:.1%} below 40%")
    if s["flat_rate"] >= 0.70:
        reasons.append(f"FLAT rate {s['flat_rate']:.1%} >= 70% (model rarely fires)")
    if s["positive_ic_folds"] < s["total_folds"] / 2:
        reasons.append(f"positive IC in only {s['positive_ic_folds']}/{s['total_folds']} folds")
    if s["long_rate"] <= 0.05:
        reasons.append(f"long rate {s['long_rate']:.1%} <= 5%")
    if s["short_rate"] <= 0.05:
        reasons.append(f"short rate {s['short_rate']:.1%} <= 5%")
    if s["ic"] <= 0:
        reasons.append("IC <= 0 (negative edge)")
    if not reasons:
        reasons.append("multiple criteria missed")
    return "; ".join(reasons)


def generate(report: dict) -> str:
    lines = []
    a = lines.append

    summary = report["summary"]
    green = report["green"]
    yellow = report["yellow"]
    red = report["red"]

    a("# Promotion Report — Walk-Forward Screening")
    a("")
    a(f"*Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    a("")

    # Section 1: Executive Summary
    a("## 1. Executive Summary")
    a("")
    a(f"- **Total tickers screened:** {summary['total']}")
    a(f"- **GREEN (promote):** {summary['green']}")
    a(f"- **YELLOW (watch):**  {summary['yellow']}")
    a(f"- **RED (skip):**      {summary['red']}")
    a("")

    if green:
        top3 = green[:3]
        a("**Top 3 tickers:**")
        for i, s in enumerate(top3, 1):
            a(f"  {i}. **{s['ticker']}** — score {s['score']}/100, IC {s['ic']:.4f}, "
              f"hit rate {s['hit_rate']:.1%}, {s['positive_ic_folds']}/{s['total_folds']} positive folds")
        a("")

    # Section 2: GREEN
    a("## 2. GREEN — Promote to Live Dashboard")
    a("")
    for s in green:
        a(f"### {s['ticker']}")
        a("")
        a(f"**Score:** {s['score']}/100  |  **IC:** {s['ic']:.4f}  |  "
          f"**Hit Rate:** {s['hit_rate']:.1%}  |  **Flat Rate:** {s['flat_rate']:.1%}")
        a(f"**Positive IC folds:** {s['positive_ic_folds']}/{s['total_folds']}  |  "
          f"**Long:** {s['long_rate']:.1%}  |  **Short:** {s['short_rate']:.1%}")
        a(f"**Recommendation:** PROMOTE — consistent edge across {s['positive_ic_folds']}/{s['total_folds']} folds, "
          f"bidirectional signal (long {s['long_rate']:.1%}, short {s['short_rate']:.1%})")
        a("")

    # Section 3: YELLOW
    a("## 3. YELLOW — Watch List")
    a("")
    for s in yellow:
        a(f"### {s['ticker']}")
        a("")
        a(f"**Score:** {s['score']}/100  |  **IC:** {s['ic']:.4f}  |  "
          f"**Hit Rate:** {s['hit_rate']:.1%}  |  **Flat Rate:** {s['flat_rate']:.1%}")
        a(f"**Positive IC folds:** {s['positive_ic_folds']}/{s['total_folds']}")
        a(f"**Note:** {note_reason(s)}")
        a("")

    # Section 4: RED
    a("## 4. RED — Do Not Promote")
    a("")
    for s in red:
        reason = note_reason(s)
        if s["ic"] <= 0:
            reason = "IC <= 0 (negative edge)"
        elif s["flat_rate"] >= 0.70:
            reason = f"FLAT rate {s['flat_rate']:.1%} > 70%"
        elif s["hit_rate"] <= 0.40:
            reason = f"hit rate {s['hit_rate']:.1%} <= 40%"
        a(f"- **{s['ticker']}** (score {s['score']}/100, IC {s['ic']:.4f}) — {reason}")
    a("")

    # Section 5: Configuration block
    ticker_map = report.get("_ticker_map", {})
    a("## 5. Paper Trading Configuration Block")
    a("")
    a("Paste this into `configs/paper_trading.yaml`:")
    a("")
    a("```yaml")
    if green:
        n = len(green)
        alloc = round(1.0 / n, 3)
        a("assets:")
        for s in green:
            orig_ticker = next((v for k, v in ticker_map.items() if k == s["ticker"]), s["ticker"])
            a(f"  - ticker: {orig_ticker}")
            a(f"    slug: {s['ticker']}")
            a(f"    allocation: {alloc:.3f}   # equal weight across {n} GREEN assets")
    else:
        a("# No GREEN tickers — no assets to promote")
    a("```")
    a("")

    return "\n".join(lines)


def main():
    report = load_report()
    ticker_map = load_ticker_map()
    # Attach ticker_map for config block generation
    report["_ticker_map"] = ticker_map
    md = generate(report)

    out_path = os.path.join(OUTPUT_DIR, "PROMOTION_REPORT.md")
    with open(out_path, "w") as f:
        f.write(md)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
