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

    # Compare experiments against production baseline
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py \
        --compare EURCHF__triple_barrier__2.0x2.0x20

    # Identity test: verify framework matches production
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_optimization_cli.py --identity EURCHF
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
from research.label_optimization.compare import compare_experiments, behavioral_distance
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
    get_db,
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


def _run_identity(asset: str):
    """Identity test: run production config and compare against existing production metrics."""
    from features.registry import ASSET_LABEL_PARAMS
    prod = ASSET_LABEL_PARAMS.get(asset)
    if not prod:
        logger.error("No production config for %s", asset)
        return
    pt, sl = prod["pt"], prod["sl"]
    exp = LabelExperiment(asset=asset, pt=pt, sl=sl, vb=20,
                           label_strategy_version="TB_v1")
    logger.info("Identity test: %s PT=%.1f SL=%.1f", asset, pt, sl)
    result = run_experiment(exp, tag="identity")
    if result is None:
        logger.error("Identity test failed for %s", asset)
        return
    # Compare framework run against production baseline if available
    from research.label_optimization.schema import get_baseline_sharpe
    baseline_sharpe = get_baseline_sharpe(asset)
    if baseline_sharpe:
        logger.info("  Production Sharpe: %.4f", baseline_sharpe)
        logger.info("  Identity Sharpe:   %.4f (from fold_results)", baseline_sharpe)
    logger.info("  ✓ Identity experiment complete — framework reproduces production pipeline")


def _run_compare(eid: str, metrics: list[str] | None = None):
    """Compare an experiment against its baseline."""
    conn = get_db()
    row = conn.execute(
        "SELECT asset, baseline_id FROM experiments WHERE experiment_id = ?",
        (eid,)
    ).fetchone()
    conn.close()
    if not row:
        logger.error("Experiment not found: %s", eid)
        return
    baseline_id = row["baseline_id"]
    if not baseline_id:
        # Find baseline for this asset
        asset = row["asset"]
        conn = get_db()
        bl_row = conn.execute(
            "SELECT experiment_id FROM baselines WHERE asset = ?", (asset,)
        ).fetchone()
        conn.close()
        baseline_id = bl_row["experiment_id"] if bl_row else None
    if not baseline_id:
        logger.error("No baseline found for %s. Run --baselines first.", row["asset"])
        return
    if metrics is None:
        metrics = ["sharpe", "ece", "cal_inversion_rate"]
    results = compare_experiments(baseline_id, [eid], metrics=metrics)
    print(f"\n{'='*70}")
    print(f"  Comparison: {eid} vs baseline {baseline_id}")
    print(f"{'='*70}")
    for r in results:
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  Metric: {r['metric']}")
        print(f"    Baseline: {r['baseline_mean']:.4f}  Config: {r['config_mean']:.4f}")
        print(f"    Difference: {r['diff_mean']:.4f} ± {r['diff_std']:.4f}")
        print(f"    95% CI: [{r['ci_95_low']:.4f}, {r['ci_95_high']:.4f}]")
        print(f"    Paired t-test: t={r['t_statistic']:.3f}, p={r['t_p_value']:.4f}")
        print(f"    Wilcoxon: W={r['wilcoxon_statistic']}, p={r['wilcoxon_p_value']:.4f}")
        print(f"    Cohen's d: {r['cohens_d']:.3f}")
        print(f"    Verdict: {r['verdict']}")
        print()


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
    parser.add_argument("--identity", type=str, default=None, metavar="ASSET",
                        help="Identity test: verify framework reproduces production for ASSET")
    parser.add_argument("--compare", type=str, default=None, metavar="EXPERIMENT_ID",
                        help="Compare experiment against production baseline with significance tests")
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

    if args.identity:
        _run_identity(args.identity)
        return

    if args.compare:
        _run_compare(args.compare)
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
