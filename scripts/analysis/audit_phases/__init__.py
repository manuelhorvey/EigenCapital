"""
Phase modules for the Production Trade Lifecycle Audit (scripts/analysis/production_audit.py).

Each module exports a `run(trades_map, **kwargs) -> dict` function.
"""

from scripts.analysis.audit_phases import (
    phase_data,
    phase1_lifecycle,
    phase2_path_dependency,
    phase4_time_profitability,
    phase6_holding_period,
    phase7_exit_strategies,
    phase8_entry_quality,
    phase9_opportunity_cost,
    phase11_overlap,
    phase12_risk_of_ruin,
    phase13_sensitivity,
    phase14_regime_transition,
    phase15_edge_decay,
    phase16_clustering,
    phase17_portfolio_timing,
    phase18_recommendations,
)

__all__ = [
    "phase_data",
    "phase1_lifecycle",
    "phase2_path_dependency",
    "phase4_time_profitability",
    "phase6_holding_period",
    "phase7_exit_strategies",
    "phase8_entry_quality",
    "phase9_opportunity_cost",
    "phase11_overlap",
    "phase12_risk_of_ruin",
    "phase13_sensitivity",
    "phase14_regime_transition",
    "phase15_edge_decay",
    "phase16_clustering",
    "phase17_portfolio_timing",
    "phase18_recommendations",
]
