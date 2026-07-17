"""Tests for engine rebalance service."""

from unittest.mock import MagicMock

import pytest

from paper_trading.services.engine_rebalance_service import EngineRebalanceService


@pytest.fixture
def engine_two_assets():
    e = MagicMock()
    asset1 = MagicMock()
    asset1.validity_sm.current_state = "NORMAL"
    asset2 = MagicMock()
    asset2.validity_sm.current_state = "NORMAL"
    e.assets = {"EURUSD": asset1, "GBPUSD": asset2}
    return e


class TestEngineRebalanceService:
    def test_crisis_regime_detection(self):
        e = MagicMock()
        asset1 = MagicMock()
        asset1.validity_sm.current_state = "CRISIS_HIGH_VOL"
        asset2 = MagicMock()
        asset2.validity_sm.current_state = "NORMAL"
        e.assets = {"EURUSD": asset1, "GBPUSD": asset2}
        svc = EngineRebalanceService(e)
        assert svc.detect_crisis_regime() is True

    def test_all_healthy_no_crisis(self, engine_two_assets):
        svc = EngineRebalanceService(engine_two_assets)
        assert svc.detect_crisis_regime() is False

    def test_empty_returns_no_crisis(self):
        e = MagicMock()
        e.assets = {}
        svc = EngineRebalanceService(e)
        assert svc.detect_crisis_regime() is False

    def test_should_rebalance_runs(self):
        e = MagicMock()
        e._rebalance_dow = 6  # Sunday — never matches weekday()
        e._rebalance_last_day = None
        svc = EngineRebalanceService(e)
        # Should not raise
        result = svc.should_rebalance()
        assert isinstance(result, bool)
