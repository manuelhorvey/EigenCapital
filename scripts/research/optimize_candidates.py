#!/usr/bin/env python3
"""
Optimization sweep for YELLOW candidates.
Tests variations of ensemble threshold, max_depth, and pt_sl symmetry.
Runs sequentially to avoid thread-safety issues with global caches.
"""

from __future__ import annotations

import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.registry import ASSET_LABEL_PARAMS

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("optimize")
logger.setLevel(logging.INFO)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "walkforward")

YELLOW_ASSETS: dict[str, str] = {
    "CADJPY": "CADJPY=X",
    "GBPUSD": "GBPUSD=X",
    "GBPJPY": "GBPJPY=X",
    "USDJPY": "USDJPY=X",
    "NZDJPY": "NZDJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X",
    "AUDJPY": "AUDJPY=X",
    "EURGBP": "EURGBP=X",
}

DEFAULT_PT_SL: dict[str, tuple[float, float]] = {}
for name in YELLOW_ASSETS:
    p = ASSET_LABEL_PARAMS.get(name, {})
    DEFAULT_PT_SL[name] = (p.get("pt", 2.0), p.get("sl", 2.0))


def score_candidate(group: pd.DataFrame) -> dict:
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
    elif score >= 40 and mean_ic > 0:
        status = "YELLOW"
    else:
        status = "RED"

    return {"asset": asset, "score": score, "ic": round(float(mean_ic), 4),
            "hit_rate": round(float(hit_rate), 4), "flat_rate": round(float(flat_rate), 4),
            "long_rate": round(float(long_rate), 4), "short_rate": round(float(short_rate), 4),
            "pos_folds": int(pos_folds), "total_folds": int(n_folds),
            "criteria_met": bool(criteria_met), "status": status}


def run_one(asset_name: str, ticker: str, pt_sl: tuple[float, float],
            ensemble_threshold: float, max_depth: int) -> dict | None:
    from scripts.backtest.walk_forward_backtest import run_walk_forward
    try:
        df = run_walk_forward(asset_name, ticker, window_years=3, step_years=1,
                              ensemble_weight=0.6, ensemble_threshold=ensemble_threshold,
                              pt_sl=pt_sl)
        if df is None or df.empty:
            return None
        result = score_candidate(df)
        result["pt_sl"] = list(pt_sl)
        result["ensemble_threshold"] = ensemble_threshold
        result["max_depth"] = max_depth
        return result
    except Exception as e:
        logger.error("  %s: %s", asset_name, e)
        return None


def main():
    thresholds = [0.05, 0.10, 0.15, 0.20]
    max_depths = [2, 3, 4]

    configs = []
    for name in YELLOW_ASSETS:
        ticker = YELLOW_ASSETS[name]
        default_pt_sl = DEFAULT_PT_SL[name]
        symmetric_pt_sl = (2.0, 2.0)
        swapped_pt_sl = (default_pt_sl[1], default_pt_sl[0])
        for pt_sl in [default_pt_sl, symmetric_pt_sl, swapped_pt_sl]:
            for et in thresholds:
                for md in max_depths:
                    configs.append((name, ticker, pt_sl, et, md))

    logger.info("Testing %d configs for %d assets...", len(configs), len(YELLOW_ASSETS))

    results = []
    for i, (name, ticker, pt_sl, et, md) in enumerate(configs):
        if i % 36 == 0:
            logger.info("  %d/%d...", i, len(configs))
        r = run_one(name, ticker, pt_sl, et, md)
        if r is not None:
            results.append(r)

    if not results:
        logger.warning("No results!")
        return

    df = pd.DataFrame(results)
    grid_path = os.path.join(OUTPUT_DIR, "optimization_grid.csv")
    df.to_csv(grid_path, index=False)
    logger.info("Grid -> %s (%d rows)", grid_path, len(df))

    # Best per asset
    best_per = []
    for asset in YELLOW_ASSETS:
        sub = df[df["asset"] == asset]
        green = sub[sub["status"] == "GREEN"]
        if not green.empty:
            best = green.loc[green["score"].idxmax()]
        else:
            yellow = sub[sub["status"] == "YELLOW"]
            if not yellow.empty:
                best = yellow.loc[yellow["score"].idxmax()]
            else:
                best = sub.loc[sub["score"].idxmax()]
        best_per.append(best.to_dict())

    print("\n" + "=" * 120)
    print("BEST CONFIG PER ASSET")
    print("=" * 120)
    print(f"{'Asset':<8} {'Score':>6} {'IC':>7} {'Hit':>6} {'Flat':>6} {'Long':>6} "
          f"{'Short':>6} {'Stat':>6}  pt_sl          et   md")
    print("-" * 120)
    for r in sorted(best_per, key=lambda x: x["score"], reverse=True):
        print(f"{r['asset']:<8} {r['score']:>6.1f} {r['ic']:>7.4f} {r['hit_rate']:>6.3f} "
              f"{r['flat_rate']:>6.3f} {r['long_rate']:>6.3f} {r['short_rate']:>6.3f} "
              f"{r['status']:>6}  {r['pt_sl']}  {r['ensemble_threshold']:.2f}  {r['max_depth']}")

    n_g = sum(1 for r in best_per if r["status"] == "GREEN")
    n_y = sum(1 for r in best_per if r["status"] == "YELLOW")
    n_r = sum(1 for r in best_per if r["status"] == "RED")
    print(f"\nBest: {n_g} GREEN, {n_y} YELLOW, {n_r} RED")

    # Impact analysis
    print("\n--- Impact: ensemble_threshold ---")
    for et in thresholds:
        sub = df[df["ensemble_threshold"] == et]
        g = len(sub[sub["status"] == "GREEN"])
        print(f"  et={et:.2f}:  score={sub['score'].mean():.1f}  hr={sub['hit_rate'].mean():.3f}  "
              f"flat={sub['flat_rate'].mean():.3f}  green={g}/{len(sub)}")

    print("\n--- Impact: pt_sl type ---")
    for name in YELLOW_ASSETS:
        sub = df[df["asset"] == name]
        def_ = sub[sub["pt_sl"].apply(tuple) == tuple(DEFAULT_PT_SL[name])]
        sym_ = sub[sub["pt_sl"].apply(tuple) == (2.0, 2.0)]
        swap_ = sub[sub["pt_sl"].apply(tuple) == tuple(reversed(DEFAULT_PT_SL[name]))]
        scores = f"default={def_['score'].mean():.1f}" if len(def_) else "default=N/A"
        scores += f"  sym={sym_['score'].mean():.1f}" if len(sym_) else "  sym=N/A"
        scores += f"  swap={swap_['score'].mean():.1f}" if len(swap_) else "  swap=N/A"
        print(f"  {name}: {scores}")

    print("\n--- Impact: max_depth ---")
    for md in max_depths:
        sub = df[df["max_depth"] == md]
        g = len(sub[sub["status"] == "GREEN"])
        print(f"  md={md}:  score={sub['score'].mean():.1f}  hr={sub['hit_rate'].mean():.3f}  "
              f"green={g}/{len(sub)}")


if __name__ == "__main__":
    main()
