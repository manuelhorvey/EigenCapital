"""Portfolio simulation runner — executes scenarios and collects results.

Loads existing experiment data from the label_optimization DB when
available, or runs new experiments when needed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import math

import numpy as np

from research.label_optimization.schema import get_db
from research.label_optimization.runner import run_grid, run_experiment
from research.portfolio_validation.scenarios import Scenario, LIVE_ASSETS
from research.portfolio_validation.metrics import compute_portfolio_metrics

logger = logging.getLogger("portfolio_validation.runner")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_existing_fold_data(
    asset: str,
    pt: float,
    sl: float,
    strategy_version: str,
) -> list[dict[str, Any]] | None:
    """Load per-fold results from the label_optimization DB if they exist."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT e.id, e.experiment_id FROM experiments e
               WHERE e.asset = ? AND ABS(e.pt - ?) < 0.01
               AND ABS(e.sl - ?) < 0.01
               AND e.label_strategy_version = ?
               AND e.status = 'done'
               ORDER BY e.timestamp DESC LIMIT 1""",
            (asset, pt, sl, strategy_version),
        ).fetchone()
        if row is None:
            return None

        eid = row["experiment_id"]
        folds = conn.execute(
            """SELECT * FROM fold_results WHERE experiment_id = ?""",
            (eid,),
        ).fetchall()
        if not folds:
            return None

        return [dict(f) for f in folds]
    finally:
        conn.close()


def _aggregate_folds(fold_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Average fold-level metrics into a single per-asset summary."""
    keys = [
        "sharpe", "ece", "brier", "cal_inversion_rate",
        "imbalance_ratio", "profit_factor", "total_return_pct",
        "max_drawdown_pct", "directional", "spearman_ic", "flat_rate",
        "buy_pct", "sell_pct", "entropy",
    ]
    agg: dict[str, Any] = {"n_folds": len(fold_data)}
    for k in keys:
        values = [f.get(k, float("nan")) for f in fold_data]
        valid = [v for v in values if not (isinstance(v, float) and math.isnan(v))]
        agg[k] = float(np.mean(valid)) if valid else 0.0
    return agg


def _experiment_id(
    asset: str,
    pt: float,
    sl: float,
    strategy: str,
) -> str:
    """Build a matching experiment ID string."""
    safe_name = asset.replace("^", "")
    return f"{safe_name}__triple_barrier__{pt:.2f}x{sl:.2f}x20"


def run_scenario(
    scenario: Scenario,
    force_rerun: bool = False,
) -> dict[str, Any]:
    """Run or load a scenario and return portfolio-level results.

    Args:
        scenario: The scenario definition.
        force_rerun: If True, re-run experiments even if cached.

    Returns:
        Dict with keys: 'scenario_name', 'portfolio_metrics', 'asset_results'
    """
    asset_results = []
    new_experiments = []

    for exp in scenario.experiments:
        if exp.asset not in LIVE_ASSETS:
            continue

        if not force_rerun:
            existing = _load_existing_fold_data(
                exp.asset, exp.pt, exp.sl, exp.label_strategy_version,
            )
            if existing is not None:
                agg = _aggregate_folds(existing)
                agg["asset"] = exp.asset
                agg["pt"] = exp.pt
                agg["sl"] = exp.sl
                agg["strategy"] = exp.label_strategy_version
                agg["source"] = "cache"
                asset_results.append(agg)
                logger.info(
                    "  %s: loaded from cache (%d folds)", exp.asset, len(existing),
                )
                continue

        new_experiments.append(exp)

    if new_experiments:
        logger.info(
            "Running %d new experiments for scenario %s...",
            len(new_experiments), scenario.name,
        )
        results = run_grid(new_experiments, tag=f"portfolio_{scenario.name}")
        for exp, result in zip(new_experiments, results):
            if result is None:
                logger.warning("  %s: experiment failed, skipping", exp.asset)
                continue
            existing = _load_existing_fold_data(
                exp.asset, exp.pt, exp.sl, exp.label_strategy_version,
            )
            if existing is not None:
                agg = _aggregate_folds(existing)
                agg["asset"] = exp.asset
                agg["pt"] = exp.pt
                agg["sl"] = exp.sl
                agg["strategy"] = exp.label_strategy_version
                agg["source"] = "new"
                asset_results.append(agg)

    if not asset_results:
        logger.warning("Scenario %s: no asset results collected", scenario.name)
        return {
            "scenario_name": scenario.name,
            "scenario_description": scenario.description,
            "portfolio_metrics": {},
            "asset_results": [],
        }

    portfolio = compute_portfolio_metrics(asset_results)
    portfolio["n_assets_loaded"] = len(asset_results)

    return {
        "scenario_name": scenario.name,
        "scenario_description": scenario.description,
        "portfolio_metrics": portfolio,
        "asset_results": asset_results,
    }


def run_portfolio_simulation(
    scenarios: dict[str, Scenario],
    force_rerun: bool = False,
) -> dict[str, dict[str, Any]]:
    """Run all scenarios and return results keyed by scenario name.

    Args:
        scenarios: Dict of scenario name -> Scenario.
        force_rerun: If True, re-run experiments.

    Returns:
        Dict of scenario name -> scenario results.
    """
    results = {}
    for name, scenario in scenarios.items():
        logger.info("Running Scenario %s: %s", name, scenario.description)
        results[name] = run_scenario(scenario, force_rerun=force_rerun)
    return results
