"""Shared pytest fixtures for EigenCapital domain model tests.

Clears all class-level registries before each test to prevent
duplicate ID collisions across test functions.
"""

import pytest


@pytest.fixture(autouse=True)
def clear_all_registries():
    """Clear all class-level registries before every test."""
    from eigencapital.core.models.instrument import Instrument
    from eigencapital.core.models.bar import Bar
    from eigencapital.core.models.market_snapshot import MarketSnapshot
    from eigencapital.core.models.strategy_intent import StrategyIntent
    from eigencapital.core.models.position import Position
    from eigencapital.core.models.fill import Fill
    from eigencapital.core.models.risk_check_result import RiskCheckResult
    from eigencapital.core.models.risk_decision import RiskDecision
    from eigencapital.core.models.portfolio_target import PortfolioTarget
    from eigencapital.core.models.approved_target import ApprovedTarget
    from eigencapital.core.models.order_plan import OrderPlan
    from eigencapital.core.models.order_lifecycle import OrderLifecycle
    from eigencapital.core.models.decision_snapshot import DecisionSnapshot
    from eigencapital.core.models.experiment import Experiment

    for cls in (
        Instrument,
        Bar,
        MarketSnapshot,
        StrategyIntent,
        Position,
        Fill,
        RiskCheckResult,
        RiskDecision,
        PortfolioTarget,
        ApprovedTarget,
        OrderPlan,
        OrderLifecycle,
        DecisionSnapshot,
        Experiment,
    ):
        if hasattr(cls, "_registry") and isinstance(cls._registry, dict):
            cls._registry.clear()

    yield

    for cls in (
        Instrument,
        Bar,
        MarketSnapshot,
        StrategyIntent,
        Position,
        Fill,
        RiskCheckResult,
        RiskDecision,
        PortfolioTarget,
        ApprovedTarget,
        OrderPlan,
        OrderLifecycle,
        DecisionSnapshot,
        Experiment,
    ):
        if hasattr(cls, "_registry") and isinstance(cls._registry, dict):
            cls._registry.clear()
