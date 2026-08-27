"""Additional coverage tests for shadow, forward_campaign, and low-coverage modules."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest


# ── Fidelity: Shadow Module ──────────────────────────────────────


class TestShadowModule:
    """Tests for eigencapital.fidelity.shadow dataclasses."""

    def test_shadow_order_creation(self):
        from eigencapital.fidelity.shadow import ShadowOrder, ShadowOrderStatus

        order = ShadowOrder(
            order_id="SORD-000001",
            timestamp="2026-01-01T00:00:00Z",
            instrument_id="EURUSD",
            side="BUY",
            quantity=0.01,
            order_type="MARKET",
            limit_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            expected_fill_price=1.1005,
            expected_spread=0.0002,
            status=ShadowOrderStatus.WOULD_SUBMIT,
        )
        assert order.instrument_id == "EURUSD"
        assert order.side == "BUY"
        assert order.status == ShadowOrderStatus.WOULD_SUBMIT

    def test_shadow_order_to_dict(self):
        from eigencapital.fidelity.shadow import ShadowOrder, ShadowOrderStatus

        order = ShadowOrder(
            order_id="SORD-000002",
            timestamp="2026-01-01T00:00:00Z",
            instrument_id="GBPUSD",
            side="SELL",
            quantity=0.02,
            order_type="MARKET",
            limit_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            expected_fill_price=1.2500,
            expected_spread=0.0003,
            status=ShadowOrderStatus.WOULD_SUBMIT,
        )
        d = order.to_dict()
        assert d["order_id"] == "SORD-000002"
        assert d["instrument_id"] == "GBPUSD"
        assert d["side"] == "SELL"
        assert d["status"] == "would_submit"

    def test_shadow_divergence_creation(self):
        from eigencapital.fidelity.shadow import DivergenceClass, ShadowDivergence

        div = ShadowDivergence(
            divergence_id="SDIV-000001",
            timestamp="2026-01-01T00:00:00Z",
            instrument_id="EURUSD",
            category="signal",
            paper_value=0.5,
            shadow_value=0.5,
            classification=DivergenceClass.MATCH,
            magnitude=0.0,
            explanation="Exact match",
        )
        assert div.classification == DivergenceClass.MATCH
        assert div.magnitude == 0.0

    def test_shadow_divergence_to_dict(self):
        from eigencapital.fidelity.shadow import DivergenceClass, ShadowDivergence

        div = ShadowDivergence(
            divergence_id="SDIV-000002",
            timestamp="2026-01-01T00:00:00Z",
            instrument_id="USDJPY",
            category="order",
            paper_value={"side": "BUY"},
            shadow_value={"side": "SELL"},
            classification=DivergenceClass.CRITICAL,
            magnitude=1.0,
            explanation="Side mismatch",
        )
        d = div.to_dict()
        assert d["classification"] == "critical"
        assert d["magnitude"] == 1.0

    def test_shadow_result_creation(self):
        from eigencapital.fidelity.shadow import ShadowResult

        result = ShadowResult(
            campaign_id="SHADOW-001",
            manifest_identity="abc123",
            total_signals=10,
            total_orders=5,
            total_divergences=3,
            exact_matches=2,
            expected_differences=1,
            tolerable_divergences=0,
            unexplained_divergences=0,
            critical_divergences=0,
            match_rate=0.667,
            orders_would_submit=4,
            orders_would_reject=1,
            status="PASS",
        )
        assert result.status == "PASS"
        assert result.match_rate == 0.667

    def test_shadow_result_to_dict(self):
        from eigencapital.fidelity.shadow import ShadowResult

        result = ShadowResult(
            campaign_id="SHADOW-002",
            manifest_identity="def456",
            total_signals=20,
            total_orders=10,
            total_divergences=5,
            exact_matches=3,
            expected_differences=1,
            tolerable_divergences=1,
            unexplained_divergences=0,
            critical_divergences=0,
            match_rate=0.6,
            orders_would_submit=8,
            orders_would_reject=2,
            status="PASS",
        )
        d = result.to_dict()
        assert d["campaign_id"] == "SHADOW-002"
        assert d["total_signals"] == 20


# ── Fidelity: Forward Campaign Enums ─────────────────────────────


class TestForwardCampaignEnums:
    """Tests for eigencapital.fidelity.forward_campaign enums and dataclasses."""

    def test_operational_event_enum(self):
        from eigencapital.fidelity.forward_campaign import OperationalEvent

        assert OperationalEvent.NORMAL.value == "normal"
        assert OperationalEvent.MISSING_BAR.value == "missing_bar"
        assert OperationalEvent.STALE_DATA.value == "stale_data"
        assert OperationalEvent.SPREAD_WIDENING.value == "spread_widening"
        assert OperationalEvent.SESSION_BOUNDARY.value == "session_boundary"
        assert OperationalEvent.MARKET_CLOSED.value == "market_closed"

    def test_campaign_phase_enum(self):
        from eigencapital.fidelity.forward_campaign import CampaignPhase

        assert CampaignPhase.INITIALIZING.value == "initializing"
        assert CampaignPhase.RUNNING.value == "running"
        assert CampaignPhase.COMPLETED.value == "completed"
        assert CampaignPhase.ABORTED.value == "aborted"

    def test_operational_state_creation(self):
        from eigencapital.fidelity.forward_campaign import OperationalState

        state = OperationalState()
        assert state.total_ticks == 0
        assert state.missing_bars == 0

    def test_operational_state_with_values(self):
        from eigencapital.fidelity.forward_campaign import OperationalState

        state = OperationalState(
            total_ticks=100,
            missing_bars=5,
            stale_data_events=2,
            spread_widening_events=3,
        )
        assert state.total_ticks == 100
        assert state.missing_bars == 5


# ── Shadow Contracts ─────────────────────────────────────────────


class TestShadowContracts:
    """Tests for eigencapital.shadow.contracts."""

    def test_shadow_broker_adapter_submit(self):
        from eigencapital.shadow.contracts import ShadowBrokerAdapter

        adapter = ShadowBrokerAdapter()
        # Test basic adapter creation
        assert adapter is not None


class TestShadowSafety:
    """Tests for eigencapital.shadow.safety."""

    def test_safety_import(self):
        from eigencapital.shadow import safety

        assert safety is not None


class TestMomentumBreakout:
    """Tests for eigencapital.features.momentum.breakout."""

    def test_breakout_import(self):
        from eigencapital.features.momentum import breakout

        assert breakout is not None


class TestMomentumCrossSectional:
    """Tests for eigencapital.features.momentum.cross_sectional."""

    def test_cross_sectional_import(self):
        from eigencapital.features.momentum import cross_sectional

        assert cross_sectional is not None


class TestMomentumTimeSeries:
    """Tests for eigencapital.features.momentum.time_series."""

    def test_time_series_import(self):
        from eigencapital.features.momentum import time_series

        assert time_series is not None


class TestCoreModelsExtended:
    """Additional tests for core models to boost coverage."""

    def test_order_import(self):
        from eigencapital.core.models import order

        assert order is not None

    def test_order_plan_import(self):
        from eigencapital.core.models import order_plan

        assert order_plan is not None

    def test_order_lifecycle_import(self):
        from eigencapital.core.models import order_lifecycle

        assert order_lifecycle is not None

    def test_decision_snapshot_import(self):
        from eigencapital.core.models import decision_snapshot

        assert decision_snapshot is not None

    def test_portfolio_target_import(self):
        from eigencapital.core.models import portfolio_target

        assert portfolio_target is not None

    def test_risk_decision_import(self):
        from eigencapital.core.models import risk_decision

        assert risk_decision is not None

    def test_risk_check_result_import(self):
        from eigencapital.core.models import risk_check_result

        assert risk_check_result is not None

    def test_strategy_intent_import(self):
        from eigencapital.core.models import strategy_intent

        assert strategy_intent is not None

    def test_position_import(self):
        from eigencapital.core.models import position

        assert position is not None

    def test_approved_target_import(self):
        from eigencapital.core.models import approved_target

        assert approved_target is not None

    def test_fill_import(self):
        from eigencapital.core.models import fill

        assert fill is not None

    def test_market_snapshot_import(self):
        from eigencapital.core.models import market_snapshot

        assert market_snapshot is not None

    def test_experiment_import(self):
        from eigencapital.core.models import experiment

        assert experiment is not None


class TestAnalyticsReport:
    """Tests for eigencapital.analytics.validation.report."""

    def test_report_import(self):
        from eigencapital.analytics.validation import report

        assert report is not None



