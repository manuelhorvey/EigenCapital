#!/usr/bin/env python3
"""
Label Optimization Framework — CLI.

Usage:
    # Stage A: Sentinel assets (rapid iteration)
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --stage A --quick
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --stage A --asset EURCHF

    # Stage B: All 17 assets
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --stage B --quick

    # Stage C: Hold-out validation
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --stage C

    # The specific experiment: symmetric labels + unchanged execution
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --symmetric-sentinel

    # Register production baselines
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --baselines

    # Report & Pareto
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --report --pareto
    PYTHONPATH=$PYTHONPATH:$PWD python scripts/research/label_optimization_cli.py --report --asset EURCHF

    # Single experiment
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py \
        --exp EURCHF__triple_barrier__1.0x1.0x20
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.label_optimization.configs import (
    ALL_ASSETS,
    HOLDOUT_ASSETS,
    STAGE_A_ASYMMETRIC_PT,
    STAGE_A_ASYMMETRIC_SL,
    STAGE_A_QUICK,
    STAGE_A_SYMMETRIC,
    STAGE_B_QUICK,
    STAGE_B_SYMMETRIC,
    STAGE_C_VALIDATION,
    SYMMETRIC_SENTINEL,
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
    get_baseline_sharpe,
    get_experiment_results,
    delete_experiment,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("label_opt.cli")


def _run_stage_a(asset: str | None, quick: bool):
    grid = STAGE_A_QUICK if quick else STAGE_A_SYMMETRIC
    assets = [asset] if asset else grid.assets
    grid = DOEGrid(
        assets=assets, pts=grid.pts, sls=grid.sls, vbs=grid.vbs,
        strategy_version=grid.strategy_version,
    )
    exps = list(grid.experiments())
    logger.info("Stage A: %d experiments (%d assets, %d PT×SL combos)",
                len(exps), len(assets), len(grid.pts) * len(grid.sls))
    run_grid(exps, tag="stage_a")

    # Also run asymmetric sweeps on sentinel assets
    if not asset:
        asym_grids = [STAGE_A_ASYMMETRIC_PT, STAGE_A_ASYMMETRIC_SL]
        for g in asym_grids:
            exps2 = list(g.experiments())
            logger.info("  + %d asymmetric experiments", len(exps2))
            run_grid(exps2, tag="stage_a_asym")


def _run_stage_b(quick: bool):
    grid = STAGE_B_QUICK if quick else STAGE_B_SYMMETRIC
    exps = list(grid.experiments())
    logger.info("Stage B: %d experiments across %d assets",
                len(exps), len(grid.assets))
    run_grid(exps, tag="stage_b")


def _run_stage_c():
    exps = list(STAGE_C_VALIDATION.experiments())
    logger.info("Stage C (hold-out): %d experiments across %d assets",
                len(exps), len(HOLDOUT_ASSETS))
    run_grid(exps, tag="stage_c")


def _run_symmetric_sentinel():
    logger.info("Symmetric PT=SL sentinel: %d experiments", len(SYMMETRIC_SENTINEL))
    for exp in SYMMETRIC_SENTINEL:
        run_experiment(exp, tag="sym_sentinel")


def _register_baselines():
    """Run production PT/SL configs and register as baselines."""
    from features.registry import ASSET_LABEL_PARAMS
    baselines = []
    for asset in ALL_ASSETS:
        prod = ASSET_LABEL_PARAMS.get(asset, {})
        pt = prod.get("pt", 2.0)
        sl = prod.get("sl", 2.0)
        exp = LabelExperiment(
            asset=asset, pt=pt, sl=sl, vb=20,
            label_strategy_version="TB_v1",
        )
        logger.info("Registering baseline: %s (PT=%.1f SL=%.1f)", asset, pt, sl)
        run_experiment(exp, tag="baseline")
        baselines.append(exp)
    return baselines


def _run_single_experiment(eid: str):
    parts = eid.split("__")
    if len(parts) != 3:
        logger.error("Invalid experiment ID: %s (expected asset__method__ptxslxvb)", eid)
        return
    asset, method = parts[0], parts[1]
    try:
        dims = parts[2].split("x")
        pt, sl, vb = float(dims[0]), float(dims[1]), int(dims[2])
    except (ValueError, IndexError):
        logger.error("Invalid dimension in %s", eid)
        return
    exp = LabelExperiment(asset=asset, label_method=method, pt=pt, sl=sl, vb=vb)
    run_experiment(exp, tag="manual")


def main():
    parser = argparse.ArgumentParser(description="Label Optimization Framework CLI")
    parser.add_argument("--stage", type=str, choices=["A", "B", "C"], default=None,
                        help="Research stage: A (sentinel), B (all 17), C (hold-out)")
    parser.add_argument("--asset", type=str, default=None)
    parser.add_argument("--quick", action="store_true", default=False)
    parser.add_argument("--symmetric-sentinel", action="store_true", default=False,
                        help="Run PT=SL symmetric labels on sentinel assets")
    parser.add_argument("--baselines", action="store_true", default=False,
                        help="Register production PT/SL configs as baselines")
    parser.add_argument("--exp", type=str, default=None,
                        help="Single experiment by ID (asset__method__ptxslxvb)")
    parser.add_argument("--report", action="store_true", default=False)
    parser.add_argument("--pareto", action="store_true", default=False)
    parser.add_argument("--save", type=str, default=None)
    parser.add_argument("--asset-filter", type=str, default=None)
    parser.add_argument("--delete", type=str, default=None,
                        help="Delete an experiment and its results")
    args = parser.parse_args()

    if args.delete:
        from research.label_optimization.schema import delete_experiment
        delete_experiment(args.delete)
        print(f"Deleted {args.delete}")
        return

    if args.exp:
        _run_single_experiment(args.exp)
        return

    if args.baselines:
        _register_baselines()
        return

    if args.symmetric_sentinel:
        _run_symmetric_sentinel()
        return

    if args.stage == "A":
        _run_stage_a(args.asset, args.quick)
    elif args.stage == "B":
        _run_stage_b(args.quick)
    elif args.stage == "C":
        _run_stage_c()
    elif not any([args.report, args.save, args.pareto]):
        parser.print_help()
        return

    if args.report or args.save or args.pareto:
        results = get_experiment_results()
        if not results:
            print("No completed experiments in DB.")
            return
        if args.report:
            df = results_dataframe(results)
            print_comparison_table(df, asset=args.asset_filter)
        if args.pareto:
            ranked = compute_pareto_rankings(results)
            print_pareto_summary(ranked)
        if args.save:
            save_report(results, args.save)


if __name__ == "__main__":
    main()
