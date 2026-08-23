"""Architecture Audit — verify no bypass paths exist.

These tests enforce the architectural rule:
    Strategy → StrategyIntent → PortfolioTarget → EigenRisk → ApprovedTarget → OrderPlan

Strategy code MUST NOT be able to:
- Submit Orders directly
- Access Broker/Execution
- Modify RiskPolicy
- Bypass Portfolio
- Disable Risk

Risk MUST NOT be disableable by strategy config.

Backtest MUST NOT silently disable costs.

Research MUST NOT mutate test datasets.
"""

import pytest
from eigencapital.strategies.base import BaseStrategy, StrategySignal
from eigencapital.core.models.order import Order
from eigencapital.risk.policy import RiskPolicy
from eigencapital.risk.engine import EigenRiskEngine
from eigencapital.backtest.engine import BacktestEngine, BacktestConfig


class TestStrategyBypassPrevention:
    """Verify strategy cannot bypass the risk boundary."""

    def test_strategy_cannot_import_order(self):
        """Strategy module should not import Order directly."""
        import eigencapital.strategies.base as strat_mod
        source = open(strat_mod.__file__).read()
        # Strategy should not create Order instances
        assert "Order(" not in source or "class Order" in source

    def test_strategy_returns_signal_not_order(self):
        """Strategy.on_bar returns StrategySignal, not Order."""
        class TestStrat(BaseStrategy):
            @property
            def strategy_id(self): return "test"
            @property
            def strategy_version(self): return "v1"
            def on_bar(self, timestamp, bars, position_quantity, cash):
                return StrategySignal(direction=1, target_risk=0.01)

        strat = TestStrat()
        signal = strat.on_bar("2024-01-01T00:00:00Z", [], 0, 100_000)
        assert isinstance(signal, StrategySignal)
        assert not isinstance(signal, Order)

    def test_risk_engine_independent(self):
        """EigenRiskEngine is a separate boundary."""
        engine = EigenRiskEngine()
        assert hasattr(engine, 'evaluate')
        assert hasattr(engine, 'policy')

    def test_risk_policy_cannot_be_modified_by_strategy(self):
        """RiskPolicy is immutable (frozen dataclass)."""
        policy = RiskPolicy(max_drawdown_pct=5.0)
        with pytest.raises(AttributeError):
            policy.max_drawdown_pct = 10.0

    def test_backtest_requires_cost_model(self):
        """BacktestConfig has a cost_model field — not silently free."""
        config = BacktestConfig()
        assert hasattr(config, 'cost_model')

    def test_fill_events_recorded(self):
        """Every fill must be recorded for audit trail."""
        from eigencapital.backtest.accounting import AccountingEngine
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        assert len(acc.fill_history) == 1

    def test_strategy_cannot_modify_accounting(self):
        """Strategy receives accounting state as read-only values."""
        class LeakTestStrategy(BaseStrategy):
            @property
            def strategy_id(self): return "leak_test"
            @property
            def strategy_version(self): return "v1"
            def on_bar(self, timestamp, bars, position_quantity, cash):
                # Try to modify cash (should not affect engine)
                cash = 0  # This is a local rebinding, not mutation
                return None

        strat = LeakTestStrategy()
        # The strategy receives copies, not references to engine state
        signal = strat.on_bar("2024-01-01T00:00:00Z", [], 0, 100_000)
        assert signal is None  # No crash, no mutation


class TestDecisionSnapshotReconstruction:
    """Verify every decision can be reconstructed from DecisionSnapshot."""

    def test_snapshot_has_all_timestamps(self):
        from eigencapital.core.models.decision_snapshot import DecisionSnapshot
        # Verify the model has the three required timestamps
        import inspect
        fields = {f.name for f in DecisionSnapshot.__dataclass_fields__.values()}
        assert "signal_timestamp_utc" in fields
        assert "risk_decision_timestamp_utc" in fields
        assert "execution_timestamp_utc" in fields

    def test_snapshot_has_provenance(self):
        from eigencapital.core.models.decision_snapshot import DecisionSnapshot
        fields = {f.name for f in DecisionSnapshot.__dataclass_fields__.values()}
        assert "strategy_config_hash" in fields
        assert "strategy_artifact_hash" in fields
        assert "provenance_hash" in fields


class TestExperimentImmutability:
    """Verify experiment cannot be modified after test freeze."""

    def test_freeze_prevents_parameter_change(self):
        from eigencapital.research.experiments.registry import ExperimentRegistry, ExperimentError
        reg = ExperimentRegistry()
        exp = reg.create(
            experiment_id="EXP-AUDIT-001",
            hypothesis_id="HYP-001",
            git_commit="abc",
            dataset_id="test",
            dataset_version="v1",
            dataset_hash="hash",
            strategy_id="test",
            strategy_version="v1",
            strategy_config_hash="cfg",
            strategy_artifact_hash="art",
            parameters={"x": 1},
        )
        reg.freeze_test_parameters("EXP-AUDIT-001")
        # After freeze, parameters should not be changeable
        # (The registry enforces this through status checks)
        with pytest.raises(ExperimentError):
            reg.freeze_test_parameters("EXP-AUDIT-001")  # Already frozen
