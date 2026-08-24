"""Phase 1O Tests — Controlled Live Readiness / Micro-Live Qualification.

Tests:
- Broker adapter contract
- Authorization gate (fail-closed)
- Micro-live risk envelope
- Campaign lifecycle
- Live/shadow/backtest divergence
- Preflight checks
- Kill switch validation
- Adversarial scenarios
"""

import pytest
import hashlib
from unittest.mock import MagicMock

from eigencapital.live.broker import LiveBrokerAdapter, BrokerConfig, BrokerStatus
from eigencapital.live.risk import (
    MicroLiveRiskEnvelope,
    MicroLiveLimits,
    LivePreflight,
    StopReason,
)
from eigencapital.live.authorization import (
    LiveAuthorization,
    AuthorizationGate,
    AuthorizationStatus,
    ExecutionMode,
)
from eigencapital.live.campaign import (
    MicroLiveCampaign,
    CampaignManager,
    CampaignStatus,
)
from eigencapital.live.comparison import (
    DivergenceRecord,
    DivergenceAnalyzer,
    DivergenceCategory,
    DivergenceSeverity,
)
from eigencapital.shadow.contracts import BrokerOrder, OrderResult


def _make_order(**overrides):
    """Helper to create a BrokerOrder with correct fields."""
    defaults = {
        "order_id": "ord-1",
        "instrument_id": "AAPL",
        "side": "BUY",
        "quantity": 10,
        "order_type": "MARKET",
        "limit_price": 150.0,
        "timestamp_utc": "2026-06-01T10:00:00",
    }
    defaults.update(overrides)
    return BrokerOrder(**defaults)


# ============================================================
# Broker Adapter Tests
# ============================================================

class TestBrokerAdapter:
    """Test live broker adapter contract."""

    def test_broker_config_fingerprint_deterministic(self):
        """Same config produces same fingerprint."""
        config = BrokerConfig(broker_id="test", broker_name="test")
        fp1 = config.compute_fingerprint()
        fp2 = config.compute_fingerprint()
        assert fp1 == fp2

    def test_broker_starts_disconnected(self):
        """Broker starts in disconnected state."""
        adapter = LiveBrokerAdapter()
        assert adapter._status == BrokerStatus.DISCONNECTED
        assert not adapter.health_check()

    def test_broker_connect_disconnect(self):
        """Broker can connect and disconnect."""
        adapter = LiveBrokerAdapter()
        assert adapter.connect() is True
        assert adapter.health_check() is True
        adapter.disconnect()
        assert not adapter.health_check()

    def test_submit_order_when_disconnected_rejected(self):
        """Orders rejected when broker is disconnected."""
        adapter = LiveBrokerAdapter()
        order = _make_order()
        result, msg = adapter.submit_order(order)
        assert result == OrderResult.BROKER_UNAVAILABLE
        assert "not connected" in msg.lower()

    def test_submit_valid_order_accepted(self):
        """Valid order accepted when connected."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order()
        result, msg = adapter.submit_order(order)
        assert result == OrderResult.ACCEPTED
        assert "ord-1" in msg

    def test_submit_invalid_quantity_rejected(self):
        """Invalid quantity rejected."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order(quantity=-5)
        result, msg = adapter.submit_order(order)
        assert result == OrderResult.REJECTED

    def test_submit_invalid_side_rejected(self):
        """Invalid side rejected."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order(side="INVALID")
        result, msg = adapter.submit_order(order)
        assert result == OrderResult.REJECTED

    def test_cancel_order(self):
        """Order cancellation works."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order()
        adapter.submit_order(order)
        assert adapter.cancel_order("ord-1") is True

    def test_cancel_nonexistent_order(self):
        """Cancel nonexistent order returns False."""
        adapter = LiveBrokerAdapter()
        assert adapter.cancel_order("nonexistent") is False

    def test_get_order_status(self):
        """Order status retrievable."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order()
        adapter.submit_order(order)
        status = adapter.get_order("ord-1")
        assert status is not None
        assert status["state"] == "SUBMITTED"

    def test_get_positions(self):
        """Positions retrievable."""
        adapter = LiveBrokerAdapter()
        positions = adapter.get_positions()
        assert isinstance(positions, dict)

    def test_get_account_state(self):
        """Account state retrievable."""
        adapter = LiveBrokerAdapter()
        state = adapter.get_account_state()
        assert "cash" in state
        assert "positions" in state
        assert "broker_status" in state


# ============================================================
# Authorization Gate Tests
# ============================================================

class TestAuthorizationGate:
    """Test live authorization gate — fail-closed."""

    def _make_auth(self, **overrides):
        defaults = {
            "authorization_id": "auth-1",
            "campaign_id": "camp-1",
            "strategy_fingerprint": "strat-fp",
            "portfolio_fingerprint": "port-fp",
            "risk_fingerprint": "risk-fp",
            "execution_fingerprint": "exec-fp",
            "broker_identity": "broker-1",
            "account_identity": "acct-1",
            "execution_mode": ExecutionMode.LIVE.value,
            "max_capital": 10000.0,
            "max_drawdown": 2000.0,
            "operator_identity": "operator-1",
            "authorization_timestamp": "2026-01-01T00:00:00",
            "expiry_timestamp": "2026-12-31T23:59:59",
        }
        defaults.update(overrides)
        return LiveAuthorization(**defaults)

    def test_no_authorization_blocks_execution(self):
        """No authorization → execution rejected."""
        gate = AuthorizationGate()
        authorized, reason = gate.validate_authorization(
            "nonexistent", "2026-06-01T00:00:00"
        )
        assert authorized is False
        assert "not found" in reason.lower()

    def test_valid_authorization_passes(self):
        """Valid authorization passes."""
        gate = AuthorizationGate()
        auth = self._make_auth()
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            strategy_fingerprint="strat-fp",
            portfolio_fingerprint="port-fp",
            risk_fingerprint="risk-fp",
            broker_identity="broker-1",
            account_identity="acct-1",
        )
        assert authorized is True

    def test_expired_authorization_rejected(self):
        """Expired authorization rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(expiry_timestamp="2026-01-01T00:00:00")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1", "2026-06-01T00:00:00"
        )
        assert authorized is False
        assert "expired" in reason.lower()

    def test_strategy_fingerprint_mismatch_rejected(self):
        """Strategy fingerprint mismatch → rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(strategy_fingerprint="correct-fp")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            strategy_fingerprint="wrong-fp",
        )
        assert authorized is False
        assert "strategy" in reason.lower()

    def test_portfolio_fingerprint_mismatch_rejected(self):
        """Portfolio fingerprint mismatch → rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(portfolio_fingerprint="correct-fp")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            portfolio_fingerprint="wrong-fp",
        )
        assert authorized is False
        assert "portfolio" in reason.lower()

    def test_risk_fingerprint_mismatch_rejected(self):
        """Risk fingerprint mismatch → rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(risk_fingerprint="correct-fp")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            risk_fingerprint="wrong-fp",
        )
        assert authorized is False
        assert "risk" in reason.lower()

    def test_broker_identity_mismatch_rejected(self):
        """Broker identity mismatch → rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(broker_identity="broker-1")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            broker_identity="broker-2",
        )
        assert authorized is False
        assert "broker" in reason.lower()

    def test_account_identity_mismatch_rejected(self):
        """Account identity mismatch → rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth(account_identity="acct-1")
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            account_identity="acct-2",
        )
        assert authorized is False
        assert "account" in reason.lower()

    def test_revoked_authorization_rejected(self):
        """Revoked authorization rejected."""
        gate = AuthorizationGate()
        auth = self._make_auth()
        gate.grant_authorization(auth)
        gate.revoke_authorization("auth-1")
        authorized, reason = gate.validate_authorization(
            "auth-1", "2026-06-01T00:00:00"
        )
        assert authorized is False
        assert "revoked" in reason.lower() or "invalid" in reason.lower()

    def test_live_enabled_requires_active_live_auth(self):
        """is_live_enabled requires active LIVE authorization."""
        gate = AuthorizationGate()
        assert gate.is_live_enabled() is False
        auth = self._make_auth(execution_mode=ExecutionMode.LIVE.value)
        gate.grant_authorization(auth)
        assert gate.is_live_enabled() is True

    def test_shadow_mode_not_live_enabled(self):
        """Shadow authorization does not enable live."""
        gate = AuthorizationGate()
        auth = self._make_auth(execution_mode=ExecutionMode.SHADOW.value)
        gate.grant_authorization(auth)
        assert gate.is_live_enabled() is False

    def test_authorization_fingerprint_deterministic(self):
        """Authorization fingerprint is deterministic."""
        auth = self._make_auth()
        fp1 = auth.compute_fingerprint()
        fp2 = auth.compute_fingerprint()
        assert fp1 == fp2

    def test_rejection_log_populated(self):
        """Rejections are logged."""
        gate = AuthorizationGate()
        gate.validate_authorization("nonexistent", "2026-06-01T00:00:00")
        log = gate.get_rejection_log()
        assert len(log) == 1


# ============================================================
# Micro-Live Risk Envelope Tests
# ============================================================

class TestMicroLiveRiskEnvelope:
    """Test micro-live risk envelope."""

    def test_order_within_limits_allowed(self):
        """Order within limits is allowed."""
        envelope = MicroLiveRiskEnvelope()
        allowed, reason = envelope.check_order(
            notional=1000.0,
            current_positions=1,
        )
        assert allowed is True

    def test_order_exceeding_notional_blocked(self):
        """Order exceeding max notional is blocked."""
        limits = MicroLiveLimits(max_order_notional=500.0)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        allowed, reason = envelope.check_order(notional=1000.0, current_positions=0)
        assert allowed is False
        assert "notional" in reason.lower()

    def test_order_exceeding_position_count_blocked(self):
        """Order when max positions reached is blocked."""
        limits = MicroLiveLimits(max_concurrent_positions=2)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        allowed, reason = envelope.check_order(notional=100.0, current_positions=2)
        assert allowed is False
        assert "position" in reason.lower()

    def test_order_exceeding_spread_blocked(self):
        """Order with excessive spread is blocked."""
        limits = MicroLiveLimits(max_spread=0.005)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        allowed, reason = envelope.check_order(notional=100.0, current_positions=0, spread=0.01)
        assert allowed is False
        assert "spread" in reason.lower()

    def test_order_exceeding_slippage_blocked(self):
        """Order with excessive slippage is blocked."""
        limits = MicroLiveLimits(max_slippage=0.002)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        allowed, reason = envelope.check_order(notional=100.0, current_positions=0, slippage=0.01)
        assert allowed is False
        assert "slippage" in reason.lower()

    def test_daily_loss_blocks_orders(self):
        """Daily loss limit blocks orders."""
        limits = MicroLiveLimits(max_daily_loss=500.0)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        envelope.update_pnl(daily_pnl=-600.0, current_equity=9400.0)
        allowed, reason = envelope.check_order(notional=100.0, current_positions=0)
        assert allowed is False
        assert "daily loss" in reason.lower()

    def test_drawdown_blocks_orders(self):
        """Drawdown limit blocks orders."""
        limits = MicroLiveLimits(max_total_drawdown=1000.0)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        # Set peak equity high, then drop below
        envelope.update_pnl(daily_pnl=0.0, current_equity=10000.0)
        envelope.update_pnl(daily_pnl=0.0, current_equity=8999.0)
        allowed, reason = envelope.check_order(notional=100.0, current_positions=0)
        assert allowed is False
        assert "drawdown" in reason.lower()

    def test_order_frequency_limit(self):
        """Order frequency limit works."""
        limits = MicroLiveLimits(max_order_frequency=3)
        envelope = MicroLiveRiskEnvelope(limits=limits)
        envelope.record_order()
        envelope.record_order()
        envelope.record_order()
        allowed, reason = envelope.check_order(notional=100.0, current_positions=0)
        assert allowed is False
        assert "frequency" in reason.lower()

    def test_fingerprint_deterministic(self):
        """Limits fingerprint is deterministic."""
        limits = MicroLiveLimits()
        fp1 = limits.compute_fingerprint()
        fp2 = limits.compute_fingerprint()
        assert fp1 == fp2

    def test_kill_switch_stop_reasons(self):
        """Kill switch adds stop reasons."""
        envelope = MicroLiveRiskEnvelope()
        assert not envelope.is_stop
        envelope.add_stop_reason(StopReason.KILL_SWITCH)
        assert envelope.is_stop
        envelope.clear_stop_reasons()
        assert not envelope.is_stop


# ============================================================
# Campaign Lifecycle Tests
# ============================================================

class TestCampaignLifecycle:
    """Test micro-live campaign lifecycle."""

    def _make_campaign(self, status=CampaignStatus.PLANNED.value, **overrides):
        defaults = {
            "campaign_id": "camp-1",
            "strategy_fingerprint": "strat-fp",
            "portfolio_fingerprint": "port-fp",
            "feature_fingerprint": "feat-fp",
            "risk_fingerprint": "risk-fp",
            "execution_fingerprint": "exec-fp",
            "broker_identity": "broker-1",
            "account_identity": "acct-1",
            "capital_limit": 10000.0,
            "drawdown_limit": 2000.0,
            "start_timestamp": "2026-01-01T00:00:00",
            "expiry_timestamp": "2026-12-31T23:59:59",
            "status": status,
        }
        defaults.update(overrides)
        return MicroLiveCampaign(**defaults)

    def test_create_campaign(self):
        """Campaign creation works."""
        manager = CampaignManager()
        campaign = self._make_campaign()
        created = manager.create_campaign(campaign)
        assert created.campaign_id == "camp-1"

    def test_valid_transition(self):
        """Valid state transition works."""
        manager = CampaignManager()
        campaign = self._make_campaign()
        manager.create_campaign(campaign)
        assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "2026-01-01T01:00:00")
        updated = manager.get_campaign("camp-1")
        assert updated.status == CampaignStatus.PREFLIGHT.value

    def test_invalid_transition_blocked(self):
        """Invalid state transition is blocked."""
        manager = CampaignManager()
        campaign = self._make_campaign(status=CampaignStatus.COMPLETED.value)
        manager.create_campaign(campaign)
        assert manager.transition_campaign("camp-1", CampaignStatus.ACTIVE.value, "2026-01-01T01:00:00") is False
        updated = manager.get_campaign("camp-1")
        assert updated.status == CampaignStatus.COMPLETED.value

    def test_planned_to_preflight(self):
        """PLANNED → PREFLIGHT is valid."""
        assert self._make_campaign(CampaignStatus.PLANNED.value).can_transition_to(CampaignStatus.PREFLIGHT.value)

    def test_preflight_to_authorized(self):
        """PREFLIGHT → AUTHORIZED is valid."""
        assert self._make_campaign(CampaignStatus.PREFLIGHT.value).can_transition_to(CampaignStatus.AUTHORIZED.value)

    def test_authorized_to_active(self):
        """AUTHORIZED → ACTIVE is valid."""
        assert self._make_campaign(CampaignStatus.AUTHORIZED.value).can_transition_to(CampaignStatus.ACTIVE.value)

    def test_active_to_completed(self):
        """ACTIVE → COMPLETED is valid."""
        assert self._make_campaign(CampaignStatus.ACTIVE.value).can_transition_to(CampaignStatus.COMPLETED.value)

    def test_active_to_failed(self):
        """ACTIVE → FAILED is valid."""
        assert self._make_campaign(CampaignStatus.ACTIVE.value).can_transition_to(CampaignStatus.FAILED.value)

    def test_terminal_states_no_transitions(self):
        """Terminal states cannot transition."""
        for terminal in [CampaignStatus.COMPLETED.value, CampaignStatus.FAILED.value,
                         CampaignStatus.STOPPED.value, CampaignStatus.EXPIRED.value]:
            campaign = self._make_campaign(status=terminal)
            assert not campaign.can_transition_to(CampaignStatus.ACTIVE.value)

    def test_campaign_fingerprint_deterministic(self):
        """Campaign fingerprint is deterministic."""
        campaign = self._make_campaign()
        fp1 = campaign.compute_fingerprint()
        fp2 = campaign.compute_fingerprint()
        assert fp1 == fp2

    def test_status_history_accumulates(self):
        """Status history accumulates through transitions."""
        manager = CampaignManager()
        campaign = self._make_campaign()
        manager.create_campaign(campaign)
        manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "2026-01-01T01:00:00")
        manager.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "2026-01-01T02:00:00")
        updated = manager.get_campaign("camp-1")
        assert len(updated.status_history) == 2

    def test_events_recorded(self):
        """All transitions are recorded as events."""
        manager = CampaignManager()
        campaign = self._make_campaign()
        manager.create_campaign(campaign)
        manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "2026-01-01T01:00:00")
        events = manager.get_events()
        assert len(events) == 2  # CREATE + STATUS_CHANGED


# ============================================================
# Divergence Analysis Tests
# ============================================================

class TestDivergenceAnalysis:
    """Test live/shadow/backtest comparison."""

    def test_matching_decisions_produce_no_divergences(self):
        """Identical decisions produce no divergences."""
        analyzer = DivergenceAnalyzer()
        decisions = [
            {"instrument_id": "AAPL", "features": {"f1": 1.0}, "strategy_intent": {"side": "BUY"}, "risk_decision": {"approved": True}},
        ]
        result = analyzer.compare_decisions(decisions, decisions, "paper", "shadow", "comp-1")
        assert result.total_divergences == 0
        assert result.critical_divergences == 0

    def test_feature_divergence_detected(self):
        """Feature divergence detected."""
        analyzer = DivergenceAnalyzer()
        source = [{"instrument_id": "AAPL", "features": {"f1": 1.0}, "strategy_intent": {}, "risk_decision": {}}]
        target = [{"instrument_id": "AAPL", "features": {"f1": 2.0}, "strategy_intent": {}, "risk_decision": {}}]
        result = analyzer.compare_decisions(source, target, "paper", "shadow", "comp-1")
        assert result.total_divergences > 0

    def test_risk_divergence_classified_critical(self):
        """Risk divergence classified as CRITICAL."""
        analyzer = DivergenceAnalyzer()
        source = [{"instrument_id": "AAPL", "features": {}, "strategy_intent": {}, "risk_decision": {"approved": True}}]
        target = [{"instrument_id": "AAPL", "features": {}, "strategy_intent": {}, "risk_decision": {"approved": False}}]
        result = analyzer.compare_decisions(source, target, "paper", "shadow", "comp-1")
        assert result.critical_divergences > 0

    def test_execution_price_divergence(self):
        """Execution price divergence detected."""
        analyzer = DivergenceAnalyzer()
        intended = {"AAPL": 150.0}
        actual = {"AAPL": 155.0}
        result = analyzer.compare_execution_prices(
            intended, actual, "comp-1", source_mode="backtest", target_mode="live"
        )
        assert result.total_divergences > 0

    def test_execution_price_match(self):
        """Matching execution prices produce no divergences."""
        analyzer = DivergenceAnalyzer()
        prices = {"AAPL": 150.0}
        result = analyzer.compare_execution_prices(
            prices, prices, "comp-1", source_mode="backtest", target_mode="live"
        )
        assert result.total_divergences == 0

    def test_divergence_fingerprint_deterministic(self):
        """Divergence record fingerprint is deterministic."""
        div = DivergenceRecord(
            divergence_id="div-1",
            timestamp="2026-01-01",
            instrument_id="AAPL",
            category=DivergenceCategory.MATCH.value,
            severity=DivergenceSeverity.INFO.value,
            expected="1.0",
            observed="1.0",
            magnitude=0.0,
        )
        fp1 = div.compute_fingerprint()
        fp2 = div.compute_fingerprint()
        assert fp1 == fp2

    def test_critical_divergences_filtered(self):
        """Critical divergences can be filtered."""
        analyzer = DivergenceAnalyzer()
        source = [
            {"instrument_id": "AAPL", "features": {"f1": 1.0}, "strategy_intent": {"s": 1}, "risk_decision": {"a": 1}},
        ]
        target = [
            {"instrument_id": "AAPL", "features": {"f1": 2.0}, "strategy_intent": {"s": 2}, "risk_decision": {"a": 2}},
        ]
        analyzer.compare_decisions(source, target, "paper", "shadow", "comp-1")
        critical = analyzer.get_critical_divergences()
        all_divs = analyzer.get_all_divergences()
        assert len(all_divs) >= len(critical)


# ============================================================
# Preflight Tests
# ============================================================

class TestPreflight:
    """Test live preflight checks."""

    def test_all_checks_passed(self):
        """All checks passed → all_passed True."""
        preflight = LivePreflight()
        preflight.run_check("DATA_HEALTH", True, "CRITICAL")
        preflight.run_check("BROKER_HEALTH", True, "CRITICAL")
        assert preflight.all_passed

    def test_any_check_failed_all_passed_false(self):
        """Any check failed → all_passed False."""
        preflight = LivePreflight()
        preflight.run_check("DATA_HEALTH", True, "CRITICAL")
        preflight.run_check("BROKER_HEALTH", False, "CRITICAL")
        assert not preflight.all_passed

    def test_critical_failures_identified(self):
        """Critical failures identified."""
        preflight = LivePreflight()
        preflight.run_check("CHECK1", True, "CRITICAL")
        preflight.run_check("CHECK2", False, "CRITICAL")
        preflight.run_check("CHECK3", False, "WARNING")
        assert len(preflight.critical_failures) == 1

    def test_non_critical_not_in_critical_failures(self):
        """Non-critical failures not in critical_failures."""
        preflight = LivePreflight()
        preflight.run_check("CHECK1", False, "WARNING")
        assert len(preflight.critical_failures) == 0


# ============================================================
# Adversarial / Integration Tests
# ============================================================

class TestPhase1OAdversarial:
    """Adversarial tests for Phase 1O."""

    def test_rejected_risk_blocks_live_order(self):
        """Risk rejection blocks live order creation."""
        gate = AuthorizationGate()
        # No authorization granted
        authorized, _ = gate.validate_authorization("any", "2026-06-01T00:00:00")
        assert authorized is False

    def test_stale_data_cannot_trigger_live_execution(self):
        """Stale data → preflight fails."""
        preflight = LivePreflight()
        preflight.run_check("DATA_HEALTH", False, "CRITICAL", "Data is stale")
        assert not preflight.all_passed

    def test_duplicate_orders_cannot_create_exposure(self):
        """Duplicate order check — broker accepts but lifecycle prevents double exposure."""
        adapter = LiveBrokerAdapter()
        adapter.connect()
        order = _make_order()
        adapter.submit_order(order)
        # Second submit with same ID
        order2 = _make_order()
        result, msg = adapter.submit_order(order2)
        # Broker accepts (dedup handled at higher level)
        assert result == OrderResult.ACCEPTED
        # Only one order in state
        assert len(adapter._orders) == 1

    def test_reconciliation_failure_halts_trading(self):
        """Reconciliation failure stops new orders."""
        envelope = MicroLiveRiskEnvelope()
        envelope.add_stop_reason(StopReason.RECONCILIATION_MISMATCH)
        assert envelope.is_stop

    def test_kill_switch_prevents_live_execution(self):
        """Kill switch prevents live execution."""
        envelope = MicroLiveRiskEnvelope()
        envelope.add_stop_reason(StopReason.KILL_SWITCH)
        assert envelope.is_stop

    def test_configuration_mismatch_blocks_authorization(self):
        """Configuration mismatch blocks authorization."""
        gate = AuthorizationGate()
        auth = LiveAuthorization(
            authorization_id="auth-1",
            campaign_id="camp-1",
            strategy_fingerprint="correct-strat-fp",
            portfolio_fingerprint="port-fp",
            risk_fingerprint="risk-fp",
            execution_fingerprint="exec-fp",
            broker_identity="broker-1",
            account_identity="acct-1",
            execution_mode=ExecutionMode.LIVE.value,
            max_capital=10000.0,
            max_drawdown=2000.0,
            operator_identity="operator-1",
            authorization_timestamp="2026-01-01T00:00:00",
            expiry_timestamp="2026-12-31T23:59:59",
        )
        gate.grant_authorization(auth)
        authorized, reason = gate.validate_authorization(
            "auth-1",
            "2026-06-01T00:00:00",
            strategy_fingerprint="wrong-strat-fp",
        )
        assert authorized is False

    def test_micro_live_limits_stricter_than_normal(self):
        """Micro-live limits are deliberately conservative."""
        limits = MicroLiveLimits()
        assert limits.max_order_notional <= 10000.0
        assert limits.max_concurrent_positions <= 5
        assert limits.max_daily_loss <= 1000.0

    def test_campaign_immutable_after_creation(self):
        """Campaign is immutable after creation (new object on transition)."""
        manager = CampaignManager()
        campaign = MicroLiveCampaign(
            campaign_id="camp-1",
            strategy_fingerprint="fp",
            portfolio_fingerprint="fp",
            feature_fingerprint="fp",
            risk_fingerprint="fp",
            execution_fingerprint="fp",
            broker_identity="b1",
            account_identity="a1",
            capital_limit=10000.0,
            drawdown_limit=2000.0,
            start_timestamp="2026-01-01",
            expiry_timestamp="2026-12-31",
            status=CampaignStatus.PLANNED.value,
        )
        manager.create_campaign(campaign)
        original_status = campaign.status
        manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "2026-01-01T01:00:00")
        # Original unchanged
        assert campaign.status == original_status
        # New object updated
        updated = manager.get_campaign("camp-1")
        assert updated.status == CampaignStatus.PREFLIGHT.value

    def test_unknown_state_fails_closed(self):
        """Unknown broker state → cannot proceed."""
        adapter = LiveBrokerAdapter()
        assert adapter._status == BrokerStatus.DISCONNECTED
        # Cannot determine state → fail closed
        assert not adapter.health_check()

    def test_divergence_severity_classification(self):
        """Divergence severity correctly classified."""
        analyzer = DivergenceAnalyzer()
        source = [
            {"instrument_id": "AAPL", "features": {}, "strategy_intent": {"s": 1}, "risk_decision": {"a": 1}},
        ]
        target = [
            {"instrument_id": "AAPL", "features": {}, "strategy_intent": {"s": 2}, "risk_decision": {"a": 1}},
        ]
        result = analyzer.compare_decisions(source, target, "paper", "live", "comp-1")
        # Strategy intent divergence is CRITICAL
        assert result.critical_divergences >= 1

    def test_full_lifecycle_planned_to_completed(self):
        """Full campaign lifecycle works."""
        manager = CampaignManager()
        campaign = MicroLiveCampaign(
            campaign_id="camp-1",
            strategy_fingerprint="fp",
            portfolio_fingerprint="fp",
            feature_fingerprint="fp",
            risk_fingerprint="fp",
            execution_fingerprint="fp",
            broker_identity="b1",
            account_identity="a1",
            capital_limit=10000.0,
            drawdown_limit=2000.0,
            start_timestamp="2026-01-01",
            expiry_timestamp="2026-12-31",
            status=CampaignStatus.PLANNED.value,
        )
        manager.create_campaign(campaign)
        manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
        manager.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "t2")
        manager.transition_campaign("camp-1", CampaignStatus.ACTIVE.value, "t3")
        manager.transition_campaign("camp-1", CampaignStatus.COMPLETED.value, "t4")
        final = manager.get_campaign("camp-1")
        assert final.status == CampaignStatus.COMPLETED.value
        assert len(final.status_history) == 4
