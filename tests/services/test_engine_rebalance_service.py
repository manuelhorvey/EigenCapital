"""Tests for engine rebalance service."""
import pytest

from paper_trading.services.engine_rebalance_service import EngineRebalanceService


class TestEngineRebalanceService:
    def test_crisis_regime_detection(self):
        svc = EngineRebalanceService()
        statuses = {"EURUSD": "CRISIS", "GBPUSD": "NORMAL"}
        assert svc._detect_crisis_regime(statuses) is True

    def test_all_healthy_no_crisis(self):
        svc = EngineRebalanceService()
        statuses = {"EURUSD": "NORMAL", "GBPUSD": "HEALTHY"}
        assert svc._detect_crisis_regime(statuses) is False

    def test_empty_returns_no_crisis(self):
        svc = EngineRebalanceService()
        assert svc._detect_crisis_regime({}) is False
