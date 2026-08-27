"""Unit tests for CostModel."""

import pytest

from eigencapital.research.costs.model import (
    MODERATE_COST,
    STRESS_COST,
    ZERO_COST,
    CostModel,
)


class TestCostModel:
    def test_creation(self):
        cm = CostModel(model_id="test_v1", commission_per_contract=2.50)
        assert cm.model_id == "test_v1"
        assert cm.commission_per_contract == 2.50

    def test_required_fields(self):
        with pytest.raises(ValueError, match="model_id"):
            CostModel(model_id="")

    def test_negative_costs_rejected(self):
        with pytest.raises(ValueError, match="commission_per_contract"):
            CostModel(model_id="test", commission_per_contract=-1.0)
        with pytest.raises(ValueError, match="slippage_ticks"):
            CostModel(model_id="test", slippage_ticks=-0.5)

    def test_cost_per_contract(self):
        cm = CostModel(
            model_id="test",
            commission_per_contract=2.50,
            spread_ticks=2,
            slippage_ticks=1,
        )
        # cost = commission + fees + spread*0.5*tick + slippage*tick
        # = 2.50 + 0 + 2*0.5*1.0 + 1*1.0 = 2.50 + 1.0 + 1.0 = 4.50
        assert cm.cost_per_contract(tick_value=1.0) == 4.50

    def test_to_from_dict(self):
        cm = CostModel(model_id="test", commission_per_contract=2.50)
        d = cm.to_dict()
        assert d["model_id"] == "test"
        cm2 = CostModel.from_dict(d)
        assert cm2.model_id == cm.model_id

    def test_predefined_models(self):
        assert ZERO_COST.model_id == "zero"
        assert MODERATE_COST.commission_per_contract == 2.50
        assert STRESS_COST.slippage_ticks == 1.0
