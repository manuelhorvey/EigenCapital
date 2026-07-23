"""Scenario definitions for portfolio A/B simulation.

Three scenarios:

    A — Current production
    B — Asset-specific optimized labels
    C — Hybrid diagnostic (new labels, old calibration)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research.label_optimization.configs import LabelExperiment

# Live portfolio as of 2026-07-23
LIVE_ASSETS = [
    "AUDJPY", "AUDUSD", "CADCHF", "EURAUD", "EURCAD", "EURCHF",
    "GBPCAD", "GBPCHF", "GBPUSD", "GC", "NZDCAD", "NZDCHF",
    "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "DJI",
]

# Assets that KEEP production labeling — skip in switch scenarios
RETAINED_ASSETS = {"GBPUSD", "CADCHF"}


@dataclass
class Scenario:
    name: str
    description: str
    experiments: list[LabelExperiment] = field(default_factory=list)


def _production_experiments(
    assets: list[str] | None = None,
) -> list[LabelExperiment]:
    """Build experiments using production configs (triple_barrier.yaml)."""
    from configs.domain_models.triple_barrier import load_triple_barrier_params
    params = load_triple_barrier_params()
    targets = assets or LIVE_ASSETS
    exps = []
    for a in targets:
        p = params.get(a, {"pt": 2.0, "sl": 2.0})
        exps.append(LabelExperiment(
            asset=a, pt=p["pt"], sl=p["sl"], vb=20,
            label_strategy_version="TB_v1",
        ))
    return exps


def _registry_experiments(
    assets: list[str] | None = None,
) -> list[LabelExperiment]:
    """Build experiments using LabelStrategyRegistry."""
    from configs.domain_models.label_strategy import LabelStrategyRegistry
    registry = LabelStrategyRegistry()
    targets = assets or LIVE_ASSETS
    exps = []
    for a in targets:
        cfg = registry.get(a)
        if cfg is None or cfg.strategy == "TB_v1":
            # Fall back to production config
            from configs.domain_models.triple_barrier import load_triple_barrier_params
            p = load_triple_barrier_params().get(a, {"pt": 2.0, "sl": 2.0})
            exps.append(LabelExperiment(
                asset=a, pt=p["pt"], sl=p["sl"], vb=20,
                label_strategy_version="TB_v1",
            ))
        else:
            exps.append(LabelExperiment(
                asset=a, pt=cfg.pt, sl=cfg.sl, vb=20,
                label_strategy_version=cfg.strategy,
            ))
    return exps


def build_scenario_a(assets: list[str] | None = None) -> Scenario:
    """Scenario A: current production labels + current calibration."""
    return Scenario(
        name="A",
        description="Current production: TB_v1 asymmetric labels",
        experiments=_production_experiments(assets),
    )


def build_scenario_b(assets: list[str] | None = None) -> Scenario:
    """Scenario B: asset-specific optimized labels + current calibration."""
    return Scenario(
        name="B",
        description="Optimized: LabelStrategyRegistry per-asset labels",
        experiments=_registry_experiments(assets),
    )


def build_scenario_c(assets: list[str] | None = None) -> Scenario:
    """Scenario C: new labels with old calibration artifacts.

    NOTE: This scenario requires running experiments with TB_sym labels
    but using calibration models trained on TB_v1 data. The current
    framework does not support loading external calibration artifacts,
    so this scenario is approximated by comparing the TB_sym label
    distribution changes against the TB_v1 calibration baseline.
    """
    return Scenario(
        name="C",
        description="Hybrid diagnostic: new labels, old calibration (estimated)",
        experiments=_registry_experiments(assets),
    )


def build_scenarios(
    assets: list[str] | None = None,
) -> dict[str, Scenario]:
    """Build all three scenarios."""
    return {
        "A": build_scenario_a(assets),
        "B": build_scenario_b(assets),
        "C": build_scenario_c(assets),
    }
