#!/usr/bin/env python3
"""
Label Optimization Framework — CLI.

Runs Design of Experiments (DOE) sweeps over labeling parameters to
find the optimal configuration that maximizes trading performance
without injecting directional bias.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --phase 1 --asset EURCHF
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --phase 1 --quick
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --phase 1 --all
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --report
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --pareto
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --exp EURCHF__triple_barrier__2.0x2.0x20
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.label_optimization.configs import (
    PHASE1_ASYMMETRIC_PT,
    PHASE1_ASYMMETRIC_SL,
    PHASE1_SYMMETRIC,
    DOEGrid,
    LabelExperiment,
)
from research.label_optimization.runner import run_experiment, run_grid
from research.label_optimization.pareto import compute_pareto_rankings
from research.label_optimization.reporting import (
    print_comparison_table,
    print_pareto_summary,
    results_dataframe,
    save_report,
)
from research.label_optimization.schema import (
    get_all_experiments,
    get_experiment_results,
    get_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("label_opt.cli")


def _run_phase1(asset: str | None, quick: bool, all_assets: bool):
    if all_assets:
        assets = PHASE1_SYMMETRIC.assets
    elif asset:
        assets = [asset]
    else:
        assets = PHASE1_SYMMETRIC.assets

    if quick:
        pts = [1.0, 2.0, 3.0, 4.0]
        sls = [1.0, 2.0, 3.0, 4.0]
    else:
        pts = PHASE1_SYMMETRIC.pts
        sls = PHASE1_SYMMETRIC.sls

    grid = DOEGrid(assets=assets, pts=pts, sls=sls, vbs=[20])
    exps = list(grid.experiments())
    logger.info("Starting Phase 1 (PT/SL sweep): %d experiments (%d assets, %d PT×SL combos)",
                len(exps), len(assets), len(pts) * len(sls))
    results = run_grid(exps, tag="phase1")
    logger.info("Phase 1 complete: %d/%d succeeded", len(results), len(exps))
    return results


def _run_single_experiment(eid: str):
    parts = eid.split("__")
    if len(parts) != 3:
        logger.error("Invalid experiment ID format: %s (expected asset__method__ptxslxvb)", eid)
        return
    asset = parts[0]
    method = parts[1]
    try:
        dims = parts[2].split("x")
        pt = float(dims[0])
        sl = float(dims[1])
        vb = int(dims[2])
    except (ValueError, IndexError):
        logger.error("Invalid dimension format in %s (expected ptxslxvb)", eid)
        return
    exp = LabelExperiment(asset=asset, label_method=method, pt=pt, sl=sl, vb=vb)
    run_experiment(exp, tag="manual")


def main():
    parser = argparse.ArgumentParser(description="Label Optimization Framework CLI")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], default=None,
                        help="Run a specific phase of the DOE")
    parser.add_argument("--asset", type=str, default=None,
                        help="Single asset to run (default: phase assets)")
    parser.add_argument("--quick", action="store_true", default=False,
                        help="Reduced grid for faster runs")
    parser.add_argument("--all", dest="all_assets", action="store_true", default=False,
                        help="Run across all phase assets")
    parser.add_argument("--exp", type=str, default=None,
                        help="Run a single experiment by ID (asset__method__ptxslxvb)")
    parser.add_argument("--report", action="store_true", default=False,
                        help="Print comparison report from DB")
    parser.add_argument("--pareto", action="store_true", default=False,
                        help="Compute and print Pareto frontiers")
    parser.add_argument("--save", type=str, default=None,
                        help="Save report to CSV path")
    parser.add_argument("--asset-filter", type=str, default=None,
                        help="Filter report to single asset")
    args = parser.parse_args()

    if args.exp:
        _run_single_experiment(args.exp)
        return

    if args.phase == 1:
        _run_phase1(args.asset, args.quick, args.all_assets)
    elif args.phase:
        logger.info("Phase %d not yet implemented", args.phase)
        return

    if args.report or args.save or args.pareto:
        results = get_experiment_results()
        if not results:
            print("No completed experiments found in database.")
            print("  DB: data/processed/label_optimization.db")
            conn = get_db()
            rows = conn.execute("SELECT experiment_id, status FROM experiments").fetchall()
            conn.close()
            if rows:
                print(f"  Found {len(rows)} total entries:")
                for r in rows:
                    print(f"    {r['experiment_id']} — {r['status']}")
            return
        df = results_dataframe(results)
        if args.report:
            print_comparison_table(df, asset=args.asset_filter)
        if args.pareto:
            objectives = {
                "sharpe": "maximize",
                "profit_factor": "maximize",
                "total_r": "maximize",
                "ece": "minimize",
                "cal_inversion_rate": "minimize",
            }
            ranked = compute_pareto_rankings(results, objectives)
            print_pareto_summary(ranked)
        if args.save:
            save_report(results, args.save)


if __name__ == "__main__":
    main()
