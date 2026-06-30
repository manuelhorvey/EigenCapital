"""Portfolio balancer — correlation-aware multi-asset TP/SL barrier adjustment.

Extends per-asset optimization (Phase 4) with cluster-aware discounting.
Identifies correlated asset clusters from daily return series and applies
a cluster risk penalty to each asset's optimal ratio.

Clusters defined by quote currency / region:
  - CHF cluster:   CADCHF, NZDCHF, EURCHF, USDCHF
  - NZD cluster:   NZDUSD, NZDCHF, NZDCAD, EURNZD
  - Equity:        ^DJI, ES, NQ
  - GBP:           GBPAUD, GBPCAD, GBPCHF, GBPUSD
  - Precious:      GC (standalone)
  - EUR cross:     EURAUD, EURCAD, EURCHF, EURNZD

Cluster discount adjusts each asset's optimal ratio:

    adjusted_ratio = opt_ratio * max(0.5, 1 - cluster_penalty)
    cluster_penalty = avg_pairwise_corr * cluster_size_factor * 0.5

Where cluster_size_factor = min(1.0, n_assets_in_cluster / 3.0)
"""

from __future__ import annotations

import itertools
import logging
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd

from scripts.backtest.monte_carlo_drawdown import (
    SELL_ONLY_ACTIVE,
    SELL_ONLY_ASSETS,
    load_pt_sl,
)
from scripts.optimization.portfolio_sltp_optimizer import (
    WALKDIR,
    compute_asset_r_series,
    evaluate_ratio,
    load_asset_signals,
    ratio_to_tp_sl,
)

logger = logging.getLogger("quorrin.optimization.portfolio_balancer")

# Quote-currency clusters with their member assets
CLUSTERS: dict[str, set[str]] = {
    "CHF": {"CADCHF", "NZDCHF", "EURCHF", "USDCHF"},
    "NZD": {"NZDUSD", "NZDCHF", "NZDCAD", "EURNZD"},
    "Equity": {"^DJI", "ES", "NQ"},
    "GBP": {"GBPAUD", "GBPCAD", "GBPCHF", "GBPUSD"},
    "EUR_cross": {"EURAUD", "EURCAD", "EURCHF", "EURNZD"},
}

# GBPJPY and USDJPY share JPY quote but are not a tight cluster alone
# GC (gold) is standalone
STANDALONE_ASSETS = {"GC", "GBPJPY", "USDJPY", "USDCAD", "AUDUSD"}

CLUSTER_DISCOUNT_FLOOR = 0.50
CORRELATION_THRESHOLD = 0.20


def _compute_r_series(args: tuple[str, float, float]) -> tuple[str, pd.Series | None]:
    """Top-level helper for multiprocessing: compute a single asset's R series."""
    name, tp, sl = args
    df = load_asset_signals(name)
    if df is None:
        return name, None
    sell_only = SELL_ONLY_ACTIVE and name in SELL_ONLY_ASSETS
    r = compute_asset_r_series(df["signal"], df["label"], tp, sl, sell_only)
    return name, r


def compute_asset_r_matrix(
    asset_names: list[str],
    pt_sl: dict[str, tuple[float, float]],
    workers: int = 4,
) -> dict[str, pd.Series]:
    """Compute daily R series for all assets at their CURRENT tp/sl config."""
    r_series: dict[str, pd.Series] = {}
    pt_sl_args = [(name, *pt_sl.get(name, (2.0, 2.0))) for name in asset_names]

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_compute_r_series, args): args[0] for args in pt_sl_args}
        for future in as_completed(futures):
            name, r = future.result()
            if r is not None:
                r_series[name] = r

    return r_series


def compute_cluster_metrics(
    r_series: dict[str, pd.Series],
) -> dict[str, dict[str, Any]]:
    """Compute per-cluster pairwise correlation and penalty."""
    all_assets = list(r_series.keys())
    joint = pd.DataFrame({name: r_series[name] for name in all_assets})
    corr = joint.corr()

    cluster_metrics: dict[str, dict[str, Any]] = {}
    for cluster_name, members in CLUSTERS.items():
        present = [a for a in members if a in all_assets]
        if len(present) < 2:
            cluster_metrics[cluster_name] = {
                "assets": present,
                "avg_corr": 0.0,
                "size_factor": 0.0,
                "penalty": 0.0,
                "n_assets": len(present),
            }
            continue

        pairs = list(itertools.combinations(present, 2))
        corrs = [corr.loc[a, b] for a, b in pairs if not (pd.isna(corr.loc[a, b]))]
        avg_corr = float(np.mean(corrs)) if corrs else 0.0
        size_factor = min(1.0, len(present) / 3.0)
        penalty = avg_corr * size_factor * 0.5
        penalty = max(0.0, min(1.0, penalty))

        cluster_metrics[cluster_name] = {
            "assets": present,
            "avg_corr": round(avg_corr, 4),
            "size_factor": round(size_factor, 4),
            "penalty": round(penalty, 4),
            "n_assets": len(present),
            "pairwise_corrs": {f"{a}-{b}": round(corr.loc[a, b], 4) for a, b in pairs},
        }

    return cluster_metrics


def compute_asset_cluster(name: str, cluster_metrics: dict[str, dict[str, Any]]) -> str | None:
    """Return the cluster name for an asset, or None if standalone."""
    for cluster_name, members in CLUSTERS.items():
        if name in members:
            return cluster_name
    return None


def balance_portfolio(
    asset_names: list[str],
    opt_results: dict[str, dict[str, Any]],
    cluster_metrics: dict[str, dict[str, Any]],
    pt_sl: dict[str, tuple[float, float]],
    signal_data: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Apply cluster-aware discount to each asset's optimal ratio."""
    recommendations: list[dict[str, Any]] = []

    for name in asset_names:
        if name not in opt_results:
            continue

        opt = opt_results[name]
        opt_ratio = opt["fine_best"]["ratio"]
        cluster_name = compute_asset_cluster(name, cluster_metrics)

        if cluster_name and cluster_metrics[cluster_name]["n_assets"] >= 2:
            penalty = cluster_metrics[cluster_name]["penalty"]
            cluster_corr = cluster_metrics[cluster_name]["avg_corr"]
        else:
            penalty = 0.0
            cluster_corr = 0.0

        adjusted_ratio = opt_ratio * max(CLUSTER_DISCOUNT_FLOOR, 1.0 - penalty)

        current_tp, current_sl = pt_sl.get(name, (2.0, 2.0))
        gm = math.sqrt(current_tp * current_sl)

        opt_tp, opt_sl = ratio_to_tp_sl(opt_ratio, gm)
        adj_tp, adj_sl = ratio_to_tp_sl(adjusted_ratio, gm)

        df = signal_data[name]
        sell_only = SELL_ONLY_ACTIVE and name in SELL_ONLY_ASSETS

        # Recompute current R for reference
        current_res = evaluate_ratio(
            name,
            current_tp / current_sl,
            gm,
            df["signal"],
            df["label"],
            sell_only,
        )
        opt_res = evaluate_ratio(
            name,
            opt_ratio,
            gm,
            df["signal"],
            df["label"],
            sell_only,
        )
        adj_res = evaluate_ratio(
            name,
            adjusted_ratio,
            gm,
            df["signal"],
            df["label"],
            sell_only,
        )

        recommendations.append(
            {
                "asset": name,
                "cluster": cluster_name or "standalone",
                "cluster_corr": cluster_corr,
                "cluster_penalty": round(penalty, 4),
                "current_tp": current_tp,
                "current_sl": current_sl,
                "current_total_r": current_res["total_r"],
                "opt_ratio": round(opt_ratio, 4),
                "opt_tp": round(opt_tp, 4),
                "opt_sl": round(opt_sl, 4),
                "opt_total_r": opt_res["total_r"],
                "adj_ratio": round(adjusted_ratio, 4),
                "adj_tp": round(adj_tp, 4),
                "adj_sl": round(adj_sl, 4),
                "adj_total_r": adj_res["total_r"],
                "sell_only": sell_only,
            }
        )

    return recommendations


def compute_portfolio_metrics(
    asset_names: list[str],
    recommendations: list[dict[str, Any]],
    signal_data: dict[str, pd.DataFrame],
    pt_sl: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Compute portfolio-level total_R for current vs balanced config."""
    current_portfolio_r: list[pd.Series] = []
    balanced_portfolio_r: list[pd.Series] = []

    rec_map = {r["asset"]: r for r in recommendations}

    for name in asset_names:
        if name not in signal_data or name not in rec_map:
            continue
        df = signal_data[name]
        sell_only = SELL_ONLY_ACTIVE and name in SELL_ONLY_ASSETS
        rec = rec_map[name]

        tp, sl = pt_sl.get(name, (2.0, 2.0))
        cur_r = compute_asset_r_series(df["signal"], df["label"], tp, sl, sell_only)
        current_portfolio_r.append(cur_r)

        bal_r = compute_asset_r_series(
            df["signal"],
            df["label"],
            rec["adj_tp"],
            rec["adj_sl"],
            sell_only,
        )
        balanced_portfolio_r.append(bal_r)

    if not current_portfolio_r:
        return {"current_total_R": 0.0, "balanced_total_R": 0.0, "delta_R": 0.0}

    joint_cur = pd.concat(current_portfolio_r, axis=1, join="inner").mean(axis=1)
    joint_bal = pd.concat(balanced_portfolio_r, axis=1, join="inner").mean(axis=1)

    return {
        "current_total_R": round(float(joint_cur.sum()), 2),
        "balanced_total_R": round(float(joint_bal.sum()), 2),
        "delta_R": round(float(joint_bal.sum() - joint_cur.sum()), 2),
    }


def print_report(
    recommendations: list[dict[str, Any]],
    cluster_metrics: dict[str, dict[str, Any]],
    portfolio: dict[str, float],
) -> None:
    """Print the portfolio balance report."""
    print("=" * 130)
    print("  PORTFOLIO TP/SL BALANCE REPORT — CLUSTER-AWARE ADJUSTMENT")
    print("=" * 130)

    # Cluster summary
    print("\n  ── Cluster Correlation Summary ──")
    for cname, cdata in sorted(cluster_metrics.items()):
        if cdata["n_assets"] < 2:
            continue
        corr_str = f"{cdata['avg_corr']:.2%}"
        pen_str = f"{cdata['penalty']:.2%}"
        print(f"  {cname:12s}  n={cdata['n_assets']}  avg_corr={corr_str:>6s}  penalty={pen_str:>6s}")

    # Per-asset recommendations
    header = (
        f"{'Asset':12s} {'Cluster':12s} {'Corr':>5s} {'Pen':>5s} "
        f"{'CurR':>7s} {'Cur tp/sl':>11s} "
        f"{'OptR':>7s} {'Opt tp/sl':>11s} "
        f"{'AdjR':>7s} {'Adj tp/sl':>11s}"
    )
    print(f"\n  {header}")
    print(f"  {'─' * len(header)}")

    for r in sorted(recommendations, key=lambda x: x["asset"]):
        sell_label = "[SO]" if r["sell_only"] else "    "
        print(
            f"  {r['asset']:12s} {r['cluster']:12s} "
            f"{r['cluster_corr']:>5.2f} {r['cluster_penalty']:>5.2f} "
            f"{r['current_total_r']:>7.2f} "
            f"{r['current_tp']:>5.2f}/{r['current_sl']:<5.2f} "
            f"{r['opt_total_r']:>7.2f} "
            f"{r['opt_tp']:>5.2f}/{r['opt_sl']:<5.2f} "
            f"{r['adj_total_r']:>7.2f} "
            f"{r['adj_tp']:>5.2f}/{r['adj_sl']:<5.2f} "
            f"{sell_label}"
        )

    print(f"\n  {'─' * len(header)}")
    print(f"  Portfolio current total_R: {portfolio['current_total_R']:>8.2f}")
    print(f"  Portfolio balanced total_R: {portfolio['balanced_total_R']:>8.2f}")
    print(f"  ΔR (balanced - current):   {portfolio['delta_R']:>+8.2f}")
    print(f"\n{'=' * 130}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import argparse

    parser = argparse.ArgumentParser(
        description="Correlation-aware portfolio TP/SL balancer",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel workers",
    )
    args = parser.parse_args()

    pt_sl = load_pt_sl()
    asset_names = [a for a in pt_sl if (WALKDIR / f"{a}_wf_signals.parquet").exists()]

    if not asset_names:
        logger.error("No assets with signal parquets found in %s", WALKDIR)
        sys.exit(1)

    logger.info("Loading signal data for %d assets", len(asset_names))
    signal_data: dict[str, pd.DataFrame] = {}
    for name in asset_names:
        df = load_asset_signals(name)
        if df is not None:
            signal_data[name] = df

    if not signal_data:
        logger.error("No signal data loaded")
        sys.exit(1)

    logger.info("Computing R series and correlation matrix")
    r_series = compute_asset_r_matrix(list(signal_data.keys()), pt_sl, args.workers)
    cluster_metrics = compute_cluster_metrics(r_series)

    logger.info("Running per-asset optimization")
    from scripts.optimization.portfolio_sltp_optimizer import optimize_asset

    opt_results: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(optimize_asset, name): name for name in signal_data}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if "error" not in result:
                    opt_results[name] = result
                    logger.info("  %s: optimized", name)
                else:
                    logger.warning("  %s: %s", name, result["error"])
            except BaseException as e:  # noqa: BLE001
                logger.error("  %s: failed — %s", name, e)

    logger.info("Balancing portfolio across clusters")
    recommendations = balance_portfolio(
        list(signal_data.keys()),
        opt_results,
        cluster_metrics,
        pt_sl,
        signal_data,
    )
    portfolio = compute_portfolio_metrics(
        list(signal_data.keys()),
        recommendations,
        signal_data,
        pt_sl,
    )

    print_report(recommendations, cluster_metrics, portfolio)


if __name__ == "__main__":
    main()
