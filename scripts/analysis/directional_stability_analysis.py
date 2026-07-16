#!/usr/bin/env python3
"""
Rolling-Window Directional Stability Analysis.

Evaluates whether per-asset directional classifications (BUY-strong, SELL-strong,
bidirectional) are temporally stable by computing performance across sliding
windows and tracking classification persistence.

Reconstructs trades from trade_lifecycle_results.json, splits them into
rolling windows (default: 365-day window, 182-day step), computes BUY and
SELL performance per window, and classifies each asset's directional strength.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/directional_stability_analysis.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT))

TRADE_PATH = PROJECT / "data" / "processed" / "trade_lifecycle_results.json"

# ── Configuration ───────────────────────────────────────────────────────
WINDOW_DAYS = 365       # 1-year rolling window
STEP_DAYS = 182         # ~6-month step
MIN_TRADES = 10         # Minimum trades per direction to classify
MIN_WINDOW_TRADES = 20  # Minimum total trades in a window

# ── Load data ────────────────────────────────────────────────────────────
def load_all_trades() -> list[dict]:
    """Load all trades from trade lifecycle JSON."""
    with open(TRADE_PATH) as f:
        data = json.load(f)

    trade_map = data.get("_trades", {})
    all_trades = []
    for asset, ts in trade_map.items():
        for t in ts:
            t["asset"] = asset
            # Parse dates
            entry = t.get("entry_date", "")
            exit_d = t.get("exit_date", "")
            if isinstance(entry, str):
                t["_entry"] = datetime.fromisoformat(entry.replace("Z", "+00:00").split("+")[0])
            if isinstance(exit_d, str):
                t["_exit"] = datetime.fromisoformat(exit_d.replace("Z", "+00:00").split("+")[0])
            all_trades.append(t)
    return all_trades


def compute_directional_metrics(
    trades: list[dict],
) -> dict:
    """Compute BUY and SELL performance metrics for a set of trades."""
    buy_trades = [t for t in trades if t.get("side") == "BUY"]
    sell_trades = [t for t in trades if t.get("side") == "SELL"]

    def _metrics(ts: list[dict], label: str) -> dict:
        if len(ts) < MIN_TRADES:
            return {"label": label, "n": len(ts), "valid": False}

        rs = [t.get("r_multiple", 0.0) for t in ts]
        r_arr = np.array(rs)
        total_r = float(np.sum(r_arr))
        wins = int(np.sum(r_arr > 0))
        losses = int(np.sum(r_arr < 0))
        wr = wins / len(r_arr) * 100 if len(r_arr) > 0 else 0.0
        avg_r = float(np.mean(r_arr))
        std_r = float(np.std(r_arr)) if len(r_arr) > 1 else 1.0

        gross_profit = float(np.sum(r_arr[r_arr > 0])) if any(r_arr > 0) else 0.0
        gross_loss = abs(float(np.sum(r_arr[r_arr < 0]))) if any(r_arr < 0) else 0.001
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe in R-space
        sharpe = (float(np.mean(r_arr)) / float(np.std(r_arr))) * math.sqrt(252) if float(np.std(r_arr)) > 0 else 0.0

        # Bootstrap confidence: probability of positive expectancy
        n_boot = 1000
        rng = np.random.default_rng(42)
        boot_means = np.array([float(np.mean(rng.choice(r_arr, size=len(r_arr), replace=True))) for _ in range(n_boot)])
        p_positive = float(np.mean(boot_means > 0))

        # Median
        median_r = float(np.median(r_arr))

        return {
            "label": label,
            "n": len(ts),
            "valid": True,
            "total_r": round(total_r, 2),
            "win_rate": round(wr, 1),
            "avg_r": round(avg_r, 4),
            "median_r": round(median_r, 4),
            "profit_factor": round(pf, 2),
            "sharpe": round(sharpe, 4),
            "std_r": round(std_r, 4),
            "p_positive": round(p_positive, 3),
            "max_win": round(float(np.max(r_arr)), 2),
            "max_loss": round(float(np.min(r_arr)), 2),
        }

    buy_m = _metrics(buy_trades, "BUY")
    sell_m = _metrics(sell_trades, "SELL")
    combined_rs = [t.get("r_multiple", 0.0) for t in trades]
    total_r = sum(combined_rs)
    n = len(combined_rs)

    return {
        "total_trades": n,
        "buy_pct": round(len(buy_trades) / n * 100, 1) if n > 0 else 0,
        "total_r": round(total_r, 2),
        "buy": buy_m,
        "sell": sell_m,
    }


def classify_direction(metrics: dict, buy_weight: float = 0.5) -> str:
    """Classify an asset's directional strength based on metrics.

    buy_weight controls how much to weigh BUY vs SELL bias.
    0.5 = neutral, >0.5 = favors BUY side for BUY-strong classification.
    """
    buy = metrics.get("buy", {})
    sell = metrics.get("sell", {})

    buy_ok = buy.get("valid", False) and buy.get("n", 0) >= MIN_TRADES
    sell_ok = sell.get("valid", False) and sell.get("n", 0) >= MIN_TRADES

    # Score: positive expectancy with statistical confidence
    def _score(m: dict) -> float:
        if not m.get("valid", False):
            return 0.0
        avg_r = m.get("avg_r", 0.0)
        p_pos = m.get("p_positive", 0.0)
        sh = m.get("sharpe", 0.0)
        # Combine: expectancy * confidence * Sharpe contribution
        return float(avg_r * p_pos * max(sh, 0.01))

    buy_score = _score(buy)
    sell_score = _score(sell)

    # Minimum threshold for directional strength
    MIN_SCORE = 0.001

    if buy_score >= MIN_SCORE and sell_score >= MIN_SCORE:
        # Both profitable — bidirectional
        if buy_score > sell_score * 2:
            return "BUY_DOMINANT"
        elif sell_score > buy_score * 2:
            return "SELL_DOMINANT"
        else:
            return "BIDIRECTIONAL"
    elif buy_score >= MIN_SCORE and sell_score < MIN_SCORE:
        return "BUY_STRONG"
    elif sell_score >= MIN_SCORE and buy_score < MIN_SCORE:
        return "SELL_STRONG"
    else:
        return "NEUTRAL"


def format_class(s: str) -> str:
    """Color-code classification for display."""
    if "BUY" in s:
        return s  # green in ANSI would be added by terminal
    if "SELL" in s:
        return s
    return s


def main():
    print("=" * 80)
    print("  DIRECTIONAL STABILITY ANALYSIS — Rolling Windows")
    print("  Window: {} days, Step: {} days".format(WINDOW_DAYS, STEP_DAYS))
    print("  Min trades per direction: {}".format(MIN_TRADES))
    print("=" * 80)

    trades = load_all_trades()
    print("\n  Loaded {} total trades across {} assets".format(
        len(trades), len(set(t["asset"] for t in trades))))

    # Determine date range
    dates = sorted(set(t["_entry"] for t in trades if "_entry" in t))
    start_date = dates[0]
    end_date = dates[-1]
    print("  Date range: {} to {} ({:.0f} days)".format(
        start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"),
        (end_date - start_date).days))

    # Build rolling windows
    windows = []
    cursor = start_date
    while cursor + timedelta(days=WINDOW_DAYS) <= end_date:
        w_start = cursor
        w_end = cursor + timedelta(days=WINDOW_DAYS)
        windows.append((w_start, w_end))
        cursor += timedelta(days=STEP_DAYS)

    # Also add a final window that ends at end_date (so we include the latest data)
    if windows and windows[-1][1] < end_date - timedelta(days=30):
        windows.append((end_date - timedelta(days=WINDOW_DAYS), end_date))

    print("  Generated {} rolling windows\n".format(len(windows)))

    # Get all unique assets
    assets = sorted(set(t["asset"] for t in trades))

    # ── Window-by-window analysis ──────────────────────────────────────
    # Track per-asset: window -> classification
    asset_window_class: dict[str, dict[str, str]] = defaultdict(dict)
    asset_window_metrics: dict[str, dict[str, dict]] = defaultdict(dict)

    for idx, (w_start, w_end) in enumerate(windows):
        w_label = "{}-{}".format(w_start.strftime("%Y-%m"), w_end.strftime("%Y-%m"))

        for asset in assets:
            asset_trades = [
                t for t in trades
                if t["asset"] == asset
                and "_entry" in t
                and w_start <= t["_entry"] < w_end
            ]

            if len(asset_trades) < MIN_WINDOW_TRADES:
                continue

            metrics = compute_directional_metrics(asset_trades)
            classification = classify_direction(metrics)

            asset_window_class[asset][w_label] = classification
            asset_window_metrics[asset][w_label] = metrics

    # ── Stability report ──────────────────────────────────────────────
    print("-" * 80)
    print("  FULL ASSET STABILITY TABLE")
    print("-" * 80)

    # Compute stability for each asset
    stability_rows = []
    for asset in assets:
        windows_active = asset_window_class.get(asset, {})
        if not windows_active:
            continue

        classifications = list(windows_active.values())
        n_windows = len(classifications)

        # Most common classification
        counter = Counter(classifications)
        dominant, dominant_count = counter.most_common(1)[0]
        stability_pct = dominant_count / n_windows * 100

        # Check for flip-flops (BUY->SELL or SELL->BUY transitions)
        flips = 0
        for i in range(1, len(classifications)):
            prev = classifications[i - 1]
            curr = classifications[i]
            if ("BUY" in prev and "SELL" in curr) or ("SELL" in prev and "BUY" in curr):
                flips += 1

        # Total R across all windows
        total_r = sum(
            m.get("total_r", 0.0)
            for m in asset_window_metrics[asset].values()
        )

        stability_rows.append({
            "asset": asset,
            "n_windows": n_windows,
            "dominant": dominant,
            "stability_pct": stability_pct,
            "flips": flips,
            "total_r": total_r,
        })

    # Sort by stability (ascending) to show volatile assets first
    stability_rows.sort(key=lambda r: r["stability_pct"])

    print()
    header = "{:10s} {:>10s} {:>20s} {:>10s} {:>6s} {:>10s}".format(
        "Asset", "Windows", "Dominant Class", "Stability", "Flips", "Total R")
    print("  " + header)
    print("  " + "-" * len(header))
    for r in stability_rows:
        print("  {:10s} {:>10d} {:>20s} {:>9.0f}% {:>6d} {:>+10.2f}".format(
            r["asset"], r["n_windows"], r["dominant"],
            r["stability_pct"], r["flips"], r["total_r"]))

    # ── Per-window detail for GBPJPY and NZDCAD ────────────────────────
    print()
    print("=" * 80)
    print("  DETAILED: GBPJPY — Window-by-Window")
    print("=" * 80)

    for asset in ["GBPJPY", "NZDCAD"]:
        print("\n" + "-" * 80)
        print("  ASSET: {}".format(asset))
        print("-" * 80)

        windows_sorted = sorted(asset_window_class.get(asset, {}).keys())
        if not windows_sorted:
            print("  No windows with sufficient trades.")
            continue

        print("\n  {:20s} {:>12s} {:>8s} {:>8s} {:>8s} {:>8s} {:>10s} {:>12s}".format(
            "Window", "Classification", "N(BUY)", "N(SELL)", "R(BUY)", "R(SELL)", "Buy AvgR", "Sell AvgR"))
        print("  " + "-" * 90)
        for w in windows_sorted:
            cls = asset_window_class[asset].get(w, "N/A")
            metrics = asset_window_metrics[asset].get(w, {})
            buy = metrics.get("buy", {})
            sell = metrics.get("sell", {})
            n_buy = buy.get("n", 0)
            n_sell = sell.get("n", 0)
            r_buy = buy.get("total_r", 0.0)
            r_sell = sell.get("total_r", 0.0)
            buy_avg = buy.get("avg_r", 0.0)
            sell_avg = sell.get("avg_r", 0.0)

            print("  {:20s} {:>12s} {:>8d} {:>8d} {:>+8.1f} {:>+8.1f} {:>+9.3f} {:>+9.3f}".format(
                w, cls, n_buy, n_sell, r_buy, r_sell, buy_avg, sell_avg))

    # ── Classification transition map ──────────────────────────────────
    print()
    print("=" * 80)
    print("  CLASSIFICATION TRANSITION MAP")
    print("  (shows how each asset's classification evolves across windows)")
    print("=" * 80)

    # Show assets ordered by stability (volatile first)
    for r in stability_rows:
        asset = r["asset"]
        windows_sorted = sorted(asset_window_class.get(asset, {}).keys())
        if not windows_sorted:
            continue

        classes = [asset_window_class[asset][w] for w in windows_sorted]

        # Abbreviate: B=BUY_STRONG, Bd=BUY_DOM, Bi=BIDIRECTIONAL, S=SELL_STRONG, Sd=SELL_DOM, N=NEUTRAL
        def abbr(c):
            m = {"BUY_STRONG": "B!", "SELL_STRONG": "S!", "BIDIRECTIONAL": "Bi",
                 "BUY_DOMINANT": "Bd", "SELL_DOMINANT": "Sd", "NEUTRAL": "N"}
            return m.get(c, c[:3])

        trans = " -> ".join(abbr(c) for c in classes)
        print("  {:10s}: st={:3.0f}% flips={:2d} | {}".format(
            asset, r["stability_pct"], r["flips"], trans))

    # ── Overall stability summary ──────────────────────────────────────
    print()
    print("=" * 80)
    print("  STABILITY SUMMARY")
    print("=" * 80)

    stable = [r for r in stability_rows if r["stability_pct"] >= 80]
    moderate = [r for r in stability_rows if 60 <= r["stability_pct"] < 80]
    volatile = [r for r in stability_rows if r["stability_pct"] < 60]

    print("\n  STABLE (>=80% same classification):")
    if stable:
        for r in sorted(stable, key=lambda x: -x["stability_pct"]):
            print("    {:10s}: {:3.0f}% stability, dominant={:15s}, flips={}".format(
                r["asset"], r["stability_pct"], r["dominant"], r["flips"]))
    else:
        print("    (none)")

    print("\n  MODERATE (60-79%):")
    if moderate:
        for r in sorted(moderate, key=lambda x: -x["stability_pct"]):
            print("    {:10s}: {:3.0f}% stability, dominant={:15s}, flips={}".format(
                r["asset"], r["stability_pct"], r["dominant"], r["flips"]))
    else:
        print("    (none)")

    print("\n  VOLATILE (<60% — flips between BUY/SELL):")
    if volatile:
        for r in sorted(volatile, key=lambda x: x["stability_pct"]):
            print("    {:10s}: {:3.0f}% stability, dominant={:15s}, flips={}".format(
                r["asset"], r["stability_pct"], r["dominant"], r["flips"]))
    else:
        print("    (none)")

    # ── Specific answer for user's question ────────────────────────────
    print()
    print("=" * 80)
    print("  TARGET ASSET VERDICT")
    print("=" * 80)

    for asset in ["GBPJPY", "NZDCAD"]:
        windows_data = asset_window_class.get(asset, {})
        if not windows_data:
            print("\n  {}: INSUFFICIENT DATA".format(asset))
            continue

        windows_sorted = sorted(windows_data.keys())
        classes = [windows_data[w] for w in windows_sorted]
        counter = Counter(classes)
        dominant, dom_count = counter.most_common(1)[0]
        stability = dom_count / len(classes) * 100
        flips = 0
        for i in range(1, len(classes)):
            prev = classes[i-1]
            curr = classes[i]
            if ("BUY" in prev and "SELL" in curr) or ("SELL" in prev and "BUY" in curr):
                flips += 1

        print("\n  {} — Stability: {:.0f}% ({}/{}) windows".format(
            asset, stability, dom_count, len(classes)))
        print("  Dominant classification: {}".format(dominant))
        print("  Full transition: {} -> ...".format(
            " -> ".join(classes)))
        print("  Direction flips: {}".format(flips))

        if stability >= 80:
            print("  ✅ Classification is STABLE — can rely on direction gate")
        elif stability >= 60:
            print("  ⚠️ Classification is MODERATE — use with caution")
        else:
            print("  ❌ Classification is VOLATILE — direction gate may be harmful")

    print("\n  Done.")


if __name__ == "__main__":
    main()
