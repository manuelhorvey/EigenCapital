#!/usr/bin/env python3
"""
Research: Per-asset XGBoost max_depth and regularization sweep.

Runs walk-forward backtests for multiple (asset, depth, reg_bundle) combos
without modifying any production code. Uses mock.patch to inject custom
XGBoost parameters into the existing run_walk_forward function.

Output: data/research/depth_optimization/results.json + per-combo CSV/parquet.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/optimization/depth_optimizer.py \\
        --assets GC,AUDUSD,GBPUSD --depths 2 3 4 5 --parallel 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("depth_optimizer")

# ── Research output directory ────────────────────────────────────────────────
RESEARCH_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "research" / "depth_optimization"
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

# ── Regularization bundles (higher depth = stronger regularization) ──────────
# These override XGBoost defaults inside run_walk_forward's XGBClassifier.
# max_depth is handled separately via run_walk_forward's existing parameter.
REGULARIZATION_BUNDLES = {
    2: {"subsample": 1.0, "colsample_bytree": 1.0, "min_child_weight": 1,
        "reg_lambda": 1, "reg_alpha": 0},
    3: {"subsample": 0.9, "colsample_bytree": 1.0, "min_child_weight": 2,
        "reg_lambda": 1, "reg_alpha": 0},
    4: {"subsample": 0.8, "colsample_bytree": 0.9, "min_child_weight": 3,
        "reg_lambda": 2, "reg_alpha": 0},
    5: {"subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 5,
        "reg_lambda": 4, "reg_alpha": 0.1},
    6: {"subsample": 0.7, "colsample_bytree": 0.7, "min_child_weight": 7,
        "reg_lambda": 6, "reg_alpha": 0.5, "learning_rate": 0.015},
}

# ── Target assets with PT/SL from production config ──────────────────────────
# Kept in-sync manually for research isolation; no production config dependency.
ASSET_LIST: list[tuple[str, str, tuple[float, float]]] = [
    ("AUDJPY", "AUDJPY=X", (2.01, 0.52)),
    ("AUDUSD", "AUDUSD=X", (4.24, 1.41)),
    ("BTCUSD", "BTC-USD", (1.51, 0.58)),
    ("CADCHF", "CADCHF=X", (4.0, 1.0)),
    ("EURAUD", "EURAUD=X", (1.77, 0.54)),
    ("EURCAD", "EURCAD=X", (2.12, 0.71)),
    ("EURCHF", "EURCHF=X", (3.0, 1.0)),
    ("EURNZD", "EURNZD=X", (3.36, 1.12)),
    ("GBPAUD", "GBPAUD=X", (3.0, 1.0)),
    ("GBPCHF", "GBPCHF=X", (2.45, 0.82)),
    ("GBPJPY", "GBPJPY=X", (2.22, 0.5)),
    ("GBPUSD", "GBPUSD=X", (1.97, 0.52)),
    ("GC", "GC=F", (2.5, 1.0)),  # gold uses separate pt_sl
    ("GBPCAD", "GBPCAD=X", (2.5, 1.0)),
    ("NZDJPY", "NZDJPY=X", (2.02, 0.51)),
    ("NZDCHF", "NZDCHF=X", (4.0, 1.0)),
    ("NZDUSD", "NZDUSD=X", (3.87, 1.29)),
    ("NZDCAD", "NZDCAD=X", (2.5, 1.0)),
    ("USDCHF", "USDCHF=X", (3.0, 0.85)),
    ("USDCAD", "USDCAD=X", (3.9, 1.3)),
    ("USDJPY", "USDJPY=X", (1.97, 0.52)),
    ("^DJI", "^DJI", (4.0, 0.5)),
]


def _compute_ece(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error (matching shared.calibration.ece_tracker)."""
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n_total = len(probs)
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        in_bin = (probs >= lo) & (probs < hi)
        if i == n_bins - 1:
            in_bin |= probs == 1.0
        n_bin = in_bin.sum()
        if n_bin > 0:
            bin_acc = outcomes[in_bin].mean()
            bin_conf = probs[in_bin].mean()
            ece += (n_bin / n_total) * abs(bin_acc - bin_conf)
    return float(ece)


def _compute_asset_r(df: pd.DataFrame, tp: float, sl: float) -> pd.Series:
    """R-multiple series from signal parquet (matches backtest_pnl.py semantics).
    
    BUY  (signal=1):  label=1 -> +tp, label=0 -> -sl
    SELL (signal=-1): label=0 -> +tp, label=1 -> -sl
    """
    r = np.zeros(len(df), dtype=float)
    signals = df["signal"].values
    labels = df["label"].values
    buy_mask = signals == 1
    sell_mask = signals == -1
    r[buy_mask & (labels == 1)] = tp
    r[buy_mask & (labels == 0)] = -sl
    r[sell_mask & (labels == 0)] = tp
    r[sell_mask & (labels == 1)] = -sl
    return pd.Series(r, index=df.index, name="daily_r")


def _asset_metrics(daily_r: pd.Series) -> dict:
    """Per-asset metrics (R-multiple based, matches backtest_pnl.py)."""
    n_trades = int((daily_r != 0).sum())
    if n_trades == 0:
        return {"n_trades": 0, "win_rate": 0.0, "total_R": 0.0, "avg_R": 0.0,
                "profit_factor": 0.0, "sharpe": 0.0, "max_dd_R": 0.0, "calmar": 0.0,
                "skew": 0.0, "ex_kurt": 0.0, "psr_gt_0": 0.0}

    wins = daily_r[daily_r > 0]
    losses = daily_r[daily_r < 0]
    total_R = float(daily_r.sum())
    avg_R = float(daily_r[daily_r != 0].mean())
    win_rate = len(wins) / n_trades
    profit_factor = abs(wins.sum() / losses.sum()) if len(losses) > 0 else float("inf")

    sharp = float(daily_r.mean() / daily_r.std() * np.sqrt(252)) if daily_r.std() > 0 else 0.0

    cum = daily_r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())
    calmar = float(total_R / abs(max_dd_r)) if max_dd_r < 0 else float("inf")

    r_arr = daily_r.values
    n = len(r_arr)
    std = float(np.std(r_arr, ddof=1))
    if std > 1e-12 and n > 2:
        demeaned = r_arr - np.mean(r_arr)
        skew = float(np.mean(demeaned ** 3) / (std ** 3) * np.sqrt(n * (n - 1)) / (n - 2))
        m4 = np.mean(demeaned ** 4)
        ex_kurt = float(m4 / (std ** 4) - 3.0)
    else:
        skew, ex_kurt = 0.0, 0.0

    from scipy.stats import norm
    var_sharpe = (1.0 + ex_kurt * sharp ** 2 / 4.0 - skew * sharp) / (n - 1) if n > 1 else 1.0
    psr = float(norm.cdf(sharp / np.sqrt(max(var_sharpe, 1e-12)))) if var_sharpe > 0 else 0.5

    return {
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharp, 4),
        "max_dd_R": round(max_dd_r, 2),
        "calmar": round(calmar, 2),
        "skew": round(skew, 4),
        "ex_kurt": round(ex_kurt, 4),
        "psr_gt_0": round(psr, 4),
    }


def run_single(asset_name: str, ticker: str, pt_sl: tuple[float, float],
               depth: int, reg_bundle: dict, tag: str) -> dict | None:
    """Run walk-forward for one (asset, depth) combo with patched XGBoost params."""
    import xgboost as xgb

    # Must import inside worker process for pickling
    from scripts.backtest.walk_forward_backtest import run_walk_forward

    depth_tag = f"{tag}_d{depth}"
    output_tag = f"{depth_tag}_{asset_name}"
    tp, sl = pt_sl

    # Monkey-patch: inject regularization params into XGBClassifier constructor
    original_init = xgb.XGBClassifier.__init__

    def _patched_init(self, **kwargs):
        merged = {**kwargs, **reg_bundle}
        # Don't duplicate max_depth — it's already passed by run_walk_forward
        original_init(self, **merged)

    try:
        with patch.object(xgb.XGBClassifier, "__init__", _patched_init):
            summary = run_walk_forward(
                asset_name, ticker,
                window_years=3, step_years=1, n_folds=3,
                max_depth=depth,
                ensemble_weight=1.0,   # no ensemble blending (matches prod)
                tag=output_tag,
                window_type="expanding",
                label_type="standard",
                invert_labels=False,
                sample_weight_flag=False,
                calibrate_flag=True,
                no_scale_pos_weight=False,
                expanded_data_dir="auto",
            )
    except Exception as e:
        logger.error("FAIL: %s depth=%d — %s", asset_name, depth, e)
        return None

    if summary is None:
        return None

    # Load signal parquet (written by run_walk_forward to walkforward dir)
    from scripts.backtest.walk_forward_backtest import OUTPUT_DIR as WF_DIR
    signal_path = Path(WF_DIR) / f"{asset_name}_wf_signals_{output_tag}.parquet"
    if not Path(signal_path).exists():
        logger.warning("%s depth=%d: no signal parquet at %s", asset_name, depth, signal_path)
        return None

    df = pd.read_parquet(signal_path)

    # Compute R-multiple PnL
    daily_r = _compute_asset_r(df, tp, sl)
    metrics = _asset_metrics(daily_r)

    # Walk-forward IC
    mean_ic = float(summary["spearman_ic"].mean())
    positive_ic_pct = float((summary["spearman_ic"] > 0).mean())
    mean_hr = float(summary["hit_rate"].mean())
    mean_directional = float(summary["directional"].mean())

    # OOS calibration ECE (raw p_long vs label)
    ece = _compute_ece(df["p_long"].values, df["label"].values)

    result = {
        "asset": asset_name,
        "ticker": ticker,
        "depth": depth,
        "total_R": metrics["total_R"],
        "sharpe": metrics["sharpe"],
        "max_dd_R": metrics["max_dd_R"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "avg_R": metrics["avg_R"],
        "calmar": metrics["calmar"],
        "n_trades": metrics["n_trades"],
        "skew": metrics["skew"],
        "ex_kurt": metrics["ex_kurt"],
        "psr_gt_0": metrics["psr_gt_0"],
        "mean_ic": round(mean_ic, 6),
        "positive_ic_pct": round(positive_ic_pct, 4),
        "mean_hit_rate": round(mean_hr, 4),
        "mean_directional": round(mean_directional, 4),
        "ece": round(ece, 4),
        "subsample": reg_bundle.get("subsample", 1.0),
        "colsample_bytree": reg_bundle.get("colsample_bytree", 1.0),
        "min_child_weight": reg_bundle.get("min_child_weight", 1),
        "reg_lambda": reg_bundle.get("reg_lambda", 1),
        "reg_alpha": reg_bundle.get("reg_alpha", 0),
    }

    logger.info(
        "OK: %s depth=%d total_R=%.1f sharpe=%.2f IC=%.4f ECE=%.4f trades=%d",
        asset_name, depth, result["total_R"], result["sharpe"],
        result["mean_ic"], result["ece"], result["n_trades"],
    )
    return result


def rank_assets(results_df: pd.DataFrame, baseline_depth: int = 2) -> pd.DataFrame:
    """Composite score ranking (higher = better depth for this asset)."""
    scores = []
    for asset in results_df["asset"].unique():
        asset_df = results_df[results_df["asset"] == asset]
        baseline = asset_df[asset_df["depth"] == baseline_depth]
        if len(baseline) == 0:
            # No baseline at depth 2 — use depth 3 as fallback
            baseline = asset_df[asset_df["depth"] == asset_df["depth"].min()]
        if len(baseline) == 0:
            continue
        base_r = baseline["total_R"].values[0]
        base_dd = abs(baseline["max_dd_R"].values[0]) or 1
        sharpe_max = max(results_df["sharpe"].max(), 0.01)

        for _, row in asset_df.iterrows():
            delta_r = (row["total_R"] - base_r) / max(abs(base_r), 1)
            dd_score = max(0, 1 - abs(row["max_dd_R"]) / base_dd) if base_dd > 0 else 0
            score = (0.40 * delta_r + 0.20 * dd_score +
                     0.15 * row["sharpe"] / sharpe_max +
                     0.15 * max(0, 1 - row["ece"] / 0.15) +
                     0.10 * row["psr_gt_0"])
            scores.append({**row.to_dict(), "composite_score": score})

    return pd.DataFrame(scores).sort_values("composite_score", ascending=False)


def generate_recommendations(ranked: pd.DataFrame) -> dict:
    """Per-asset best-depth config blocks."""
    recommendations = {}
    for asset in ranked["asset"].unique():
        best = ranked[ranked["asset"] == asset].iloc[0]
        recommendations[asset] = {
            "max_depth": int(best["depth"]),
            "composite_score": round(float(best["composite_score"]), 4),
            "total_R": round(float(best["total_R"]), 2),
            "sharpe": round(float(best["sharpe"]), 4),
            "max_dd_R": round(float(best["max_dd_R"]), 2),
            "win_rate": round(float(best["win_rate"]), 4),
            "mean_ic": round(float(best["mean_ic"]), 6),
            "ece": round(float(best["ece"]), 4),
            "n_trades": int(best["n_trades"]),
            "subsample": float(best["subsample"]),
            "colsample_bytree": float(best["colsample_bytree"]),
            "min_child_weight": int(best["min_child_weight"]),
            "reg_lambda": float(best["reg_lambda"]),
        }
    return recommendations


def main():
    parser = argparse.ArgumentParser(description="Per-asset XGBoost depth optimization sweep")
    parser.add_argument("--assets", nargs="*", default=None,
                        help="Asset names to sweep (default: all)")
    parser.add_argument("--depths", nargs="*", type=int, default=[2, 3, 4, 5],
                        help="Depth values to test (default: 2 3 4 5)")
    parser.add_argument("--tag", default="research_depth",
                        help="Output tag suffix")
    parser.add_argument("--parallel", type=int, default=4,
                        help="Parallel workers (default: 4)")
    parser.add_argument("--output", default=str(RESEARCH_DIR / "results.json"),
                        help="Output JSON path")
    args = parser.parse_args()

    # Filter assets
    asset_list = ASSET_LIST
    if args.assets:
        asset_names = set(args.assets)
        asset_list = [(n, t, p) for n, t, p in ASSET_LIST if n in asset_names]

    logger.info("Sweeping %d assets × %d depths = %d combos (parallel=%d)",
                len(asset_list), len(args.depths), len(asset_list) * len(args.depths),
                args.parallel)

    # Build run matrix
    runs = []
    for name, ticker, pt_sl in asset_list:
        for depth in args.depths:
            reg = REGULARIZATION_BUNDLES.get(depth, REGULARIZATION_BUNDLES[2])
            runs.append((name, ticker, pt_sl, depth, reg, args.tag))

    # Execute in parallel
    t0 = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=args.parallel) as executor:
        futures = {executor.submit(run_single, *r): r for r in runs}
        for future in as_completed(futures):
            r = futures[future]
            result = future.result()
            if result is not None:
                results.append(result)

    elapsed = time.perf_counter() - t0
    logger.info("Completed %d/%d combos in %.1fs", len(results), len(runs), elapsed)

    if not results:
        logger.error("No results produced — aborting.")
        sys.exit(1)

    # Rank
    df = pd.DataFrame(results)
    ranked = rank_assets(df)
    recommendations = generate_recommendations(ranked)

    # Output
    output = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "elapsed_s": round(elapsed, 1),
        "n_assets": len(recommendations),
        "n_combos_run": len(results),
        "recommendations": recommendations,
        "full_results": df.to_dict(orient="records"),
    }
    output_path = args.output
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str, cls=None)
    logger.info("Results -> %s", output_path)

    # Also save CSV for analysis
    csv_path = output_path.replace(".json", ".csv")
    df.to_csv(csv_path, index=False)
    logger.info("Full results -> %s", csv_path)

    # Print summary
    print("\n" + "=" * 72)
    print("DEPTH OPTIMIZATION RESULTS")
    print("=" * 72)
    for _, row in ranked.iterrows():
        marker = "★" if row["depth"] != 2 and row["composite_score"] > 0 else " "
        print(f" {marker} {row['asset']:<10s} depth={int(row['depth'])}  "
              f"score={row['composite_score']:.4f}  "
              f"ΔR={row['total_R']:+.1f}  "
              f"IC={row['mean_ic']:.4f}  "
              f"ECE={row['ece']:.4f}  "
              f"trades={int(row['n_trades'])}")

    print("\n--- Recommended Config Changes ---\n")
    for asset, rec in sorted(recommendations.items(),
                             key=lambda x: x[1]["composite_score"], reverse=True):
        print(f"# {asset}: score={rec['composite_score']:.4f}, "
              f"R={rec['total_R']:+.1f}, IC={rec['mean_ic']:.4f}, ECE={rec['ece']:.4f}")
        print(f"max_depth: {rec['max_depth']}")
        print()


if __name__ == "__main__":
    main()
