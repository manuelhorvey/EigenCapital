"""Grid search TP/SL optimizer — ratio-space with geometric mean constraint.

Scans (tp/sl) ratio space against walk-forward signal parquets while
preserving the geometric mean of current barriers. For each candidate
ratio r:

    tp = gm * sqrt(r)      sl = gm / sqrt(r)
    where gm = sqrt(current_tp * current_sl)

Constraint: sqrt(tp * sl) = constant across all candidates, ensuring
average barrier distance stays comparable. This separates the R:R
improvement question from the "make barriers huge" artifact.

Two-pass search:
1. Coarse grid: ratio ∈ [0.1, 20.0] with 20 log-spaced points
2. Fine grid: ±30% around coarse optimum, 10 linear-spaced steps

Run on 21 assets (2026-06-30): ALL 21/21 converge to ratio=20.0
(search boundary). Signal WR unchanged — improvement is purely
from R:R asymmetry under geometric mean constraint.
"""

from __future__ import annotations

import logging
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.backtest.monte_carlo_drawdown import (
    SELL_ONLY_ACTIVE,
    SELL_ONLY_ASSETS,
    load_pt_sl,
)

logger = logging.getLogger("eigencapital.optimization.grid_search")

WALKDIR = Path(__file__).resolve().parent.parent.parent / "walkforward"

MIN_RATIO = 0.1
MAX_RATIO = 20.0
N_COARSE = 20
N_FINE = 10
FINE_RADIUS_FRAC = 0.30


def compute_trade_r(signal: int, label: int, tp: float, sl: float) -> float:
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


def compute_asset_r_series(
    signal_series: pd.Series,
    label_series: pd.Series,
    tp: float,
    sl: float,
    sell_only: bool = False,
) -> pd.Series:
    r_values: list[float] = []
    for sig, lbl in zip(signal_series, label_series):
        if sell_only and sig == 1:
            r_values.append(0.0)
        else:
            r_values.append(compute_trade_r(sig, lbl, tp, sl))
    return pd.Series(r_values, index=signal_series.index)


def load_asset_signals(name: str) -> pd.DataFrame | None:
    path = WALKDIR / f"{name}_wf_signals.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    required = {"signal", "label"}
    if not required.issubset(df.columns):
        logger.warning("%s: missing columns %s", name, required - set(df.columns))
        return None
    return df


def ratio_to_tp_sl(ratio: float, gm: float) -> tuple[float, float]:
    """Convert ratio (tp/sl) and geometric mean to (tp, sl)."""
    if ratio <= 0 or gm <= 0:
        return (1.0, 1.0)
    sqrt_r = math.sqrt(ratio)
    tp = gm * sqrt_r
    sl = gm / sqrt_r
    return (tp, sl)


def evaluate_ratio(
    name: str,
    ratio: float,
    gm: float,
    signal_series: pd.Series,
    label_series: pd.Series,
    sell_only: bool,
) -> dict[str, Any]:
    tp, sl = ratio_to_tp_sl(ratio, gm)
    r = compute_asset_r_series(signal_series, label_series, tp, sl, sell_only)
    total_r = float(r.sum())
    n_signals = int((r != 0).sum())
    wr = float((r > 0).sum() / (r != 0).sum()) if (r != 0).sum() > 0 else 0.0
    avg_r = float(r[r != 0].mean()) if (r != 0).sum() > 0 else 0.0
    sharpe = float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 and n_signals > 1 else 0.0
    be_wr = sl / (tp + sl) if (tp + sl) > 0 else 0.5

    return {
        "asset": name,
        "ratio": round(ratio, 4),
        "tp": round(tp, 4),
        "sl": round(sl, 4),
        "total_r": round(total_r, 2),
        "win_rate": round(wr, 4),
        "avg_r": round(avg_r, 4),
        "sharpe": round(sharpe, 4),
        "n_signals": n_signals,
        "breakeven_wr": round(be_wr, 4),
        "wr_margin": round(wr - be_wr, 4),
    }


def _logspace(start: float, end: float, n: int) -> list[float]:
    """Generate n logarithmically spaced points between start and end."""
    return [round(math.exp(x), 4) for x in np.linspace(math.log(start), math.log(end), n)]


def _linspace(start: float, end: float, n: int) -> list[float]:
    """Generate n linearly spaced points."""
    return [round(start + i * (end - start) / (n - 1), 4) for i in range(n)]


def ratio_search(
    name: str,
    signal_series: pd.Series,
    label_series: pd.Series,
    sell_only: bool,
    gm: float,
    ratios: list[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate all candidate ratios and return (best, all_results)."""
    results: list[dict[str, Any]] = []
    for r in ratios:
        result = evaluate_ratio(name, r, gm, signal_series, label_series, sell_only)
        results.append(result)
    df = pd.DataFrame(results)
    best = df.loc[df["total_r"].idxmax()].to_dict()
    return best, results


def optimize_asset(name: str, sell_only_override: bool | None = None) -> dict[str, Any]:
    df = load_asset_signals(name)
    if df is None:
        return {"asset": name, "error": f"No signal parquet in {WALKDIR}"}

    sell_only = (
        sell_only_override if sell_only_override is not None else (SELL_ONLY_ACTIVE and name in SELL_ONLY_ASSETS)
    )
    if sell_only:
        logger.info("  %s: SELL_ONLY — evaluating SELL leg only", name)

    pt_sl = load_pt_sl()
    current_tp, current_sl = pt_sl.get(name, (2.0, 2.0))
    gm = math.sqrt(current_tp * current_sl)

    coarse_ratios = _logspace(MIN_RATIO, MAX_RATIO, N_COARSE)
    coarse_best, coarse_all = ratio_search(
        name,
        df["signal"],
        df["label"],
        sell_only,
        gm,
        coarse_ratios,
    )

    best_r = coarse_best["ratio"]
    r_low = max(MIN_RATIO, best_r * (1 - FINE_RADIUS_FRAC))
    r_high = min(MAX_RATIO, best_r * (1 + FINE_RADIUS_FRAC))
    fine_ratios = _linspace(r_low, r_high, N_FINE)
    fine_best, fine_all = ratio_search(
        name,
        df["signal"],
        df["label"],
        sell_only,
        gm,
        fine_ratios,
    )

    current_result = evaluate_ratio(
        name,
        current_tp / current_sl,
        gm,
        df["signal"],
        df["label"],
        sell_only,
    )

    return {
        "asset": name,
        "current_tp": current_tp,
        "current_sl": current_sl,
        "gm": round(gm, 4),
        "current": current_result,
        "coarse_best": coarse_best,
        "fine_best": fine_best,
        "n_signals": int((df["signal"] != 0).sum()),
        "signals_loaded": len(df),
        "sell_only": sell_only,
    }


def print_optimization_report(results: list[dict[str, Any]]) -> None:
    print("=" * 120)
    print("  PER-ASSET TP/SL OPTIMIZATION — RATIO-SPACE WITH GEOMETRIC MEAN CONSTRAINT")
    print("=" * 120)

    header = (
        f"{'Asset':12s} {'N':>5s} {'SO':>3s} "
        f"{'Cur tp':>6s} {'Cur sl':>6s} {'Cur R':>8s} {'Cur WR':>6s} "
        f"{'Opt tp':>6s} {'Opt sl':>6s} {'Ratio':>6s} "
        f"{'Opt R':>8s} {'Opt WR':>6s} {'ΔR':>8s}"
    )
    print(f"\n{header}")
    print(f"{'-' * len(header)}")

    for r in sorted(results, key=lambda x: x["asset"]):
        if "error" in r:
            print(f"  {r['asset']:12s}  ERROR: {r['error']}")
            continue

        c = r["current"]
        b = r["fine_best"]
        delta_r = b["total_r"] - c["total_r"]
        sell_label = "SO" if r["sell_only"] else "  "

        print(
            f"  {r['asset']:12s} {r['n_signals']:>5d} {sell_label:>3s} "
            f"{r['current_tp']:>6.2f} {r['current_sl']:>6.2f} "
            f"{c['total_r']:>8.2f} {c['win_rate']:>6.1%} "
            f"{b['tp']:>6.2f} {b['sl']:>6.2f} {b['ratio']:>6.2f} "
            f"{b['total_r']:>8.2f} {b['win_rate']:>6.1%} "
            f"{delta_r:>+8.2f}"
        )

    improvements = [r for r in results if "error" not in r and r["fine_best"]["total_r"] > r["current"]["total_r"]]
    total_delta = sum(r["fine_best"]["total_r"] - r["current"]["total_r"] for r in results if "error" not in r)
    print(f"\n{'─' * len(header)}")
    print(f"  Assets improved: {len(improvements)}/{len([r for r in results if 'error' not in r])}")
    print(f"  Total ΔR (opt - current): {total_delta:+.2f}")
    print(f"\n{'=' * 120}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import argparse

    parser = argparse.ArgumentParser(
        description="Grid search TP/SL optimizer with geometric mean constraint",
    )
    parser.add_argument(
        "--assets",
        type=str,
        default="",
        help="Comma-separated list of assets (default: all with parquets)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel workers for asset-level optimization",
    )
    parser.add_argument(
        "--sell-only",
        action="store_true",
        help="Apply SELL_ONLY filter to flagged assets",
    )
    parser.add_argument(
        "--no-sell-only",
        dest="sell_only",
        action="store_false",
    )
    parser.set_defaults(sell_only=None)
    args = parser.parse_args()

    if args.assets:
        asset_names = [a.strip() for a in args.assets.split(",")]
    else:
        pt_sl = load_pt_sl()
        asset_names = [a for a in pt_sl if (WALKDIR / f"{a}_wf_signals.parquet").exists()]

    if not asset_names:
        logger.error("No assets with signal parquets found in %s", WALKDIR)
        sys.exit(1)

    logger.info("Optimizing %d assets: %s", len(asset_names), ", ".join(asset_names))

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(optimize_asset, name, args.sell_only): name for name in asset_names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                results.append(result)
                logger.info("  %s: done", name)
            except BaseException as e:  # noqa: BLE001
                logger.error("  %s: failed — %s", name, e)
                results.append({"asset": name, "error": str(e)})

    print_optimization_report(results)


if __name__ == "__main__":
    main()
