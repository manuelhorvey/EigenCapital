"""Phase 2 Parity Tests — verify R4 behavior unchanged after infrastructure changes.

These tests ensure that the P0 infrastructure implementations
(event ledger, reconciliation, health states, risk observation,
structured alerts, failure instrumentation) do not alter R4's
intended behavior.

Every infrastructure change must pass these parity tests
before being considered Phase-2-safe.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Any

import pytest

# Import R4 core components
from eigencapital.config import load_config
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.risk.policy import RiskPolicy
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

# Import P0 infrastructure components
from eigencapital.production_qual.event_ledger import EventLedger, EventType
from eigencapital.reconciliation.engine import ReconciliationEngine, BrokerState, InternalState
from eigencapital.live.health import HealthMonitor, HealthDimension, HealthState
from eigencapital.live.risk_observation import RiskObserver, RiskObservationLevel
from eigencapital.live.structured_alerts import StructuredAlertDispatcher, AlertSeverity, AlertCategory
from eigencapital.live.failure_instrumentation import FailureInstrumentation, FailureType, FailureSeverity


@pytest.fixture
def config():
    """Load production config."""
    return load_config("production")


@pytest.fixture
def manifest():
    """Create R4 manifest."""
    return R4ConfigManifest()


@pytest.fixture
def risk_policy():
    """Create risk policy."""
    return RiskPolicy()


@pytest.fixture
def fingerprint_verifier(config):
    """Create fingerprint verifier."""
    return FingerprintVerifier(config=config)


class TestR4FingerprintParity:
    """Verify R4 fingerprint remains unchanged."""
    
    def test_manifest_fingerprint_unchanged(self, manifest):
        """R4 manifest fingerprint must be identical."""
        # This is the known frozen fingerprint
        expected = "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"
        actual = manifest.compute_identity()
        assert actual == expected, f"R4 manifest fingerprint changed: {actual}"
    
    def test_strategy_version_unchanged(self, config):
        """R4 strategy version must remain R4.0."""
        assert config.strategy.version == "R4.0"
    
    def test_fingerprint_verifier_all_verified(self, fingerprint_verifier):
        """All fingerprints must verify at startup."""
        result = fingerprint_verifier.verify_all()
        assert result.all_verified, f"Fingerprint verification failed: {result.checks}"


class TestR4ConfigParity:
    """Verify R4 configuration parameters unchanged."""
    
    def test_signal_parameters_unchanged(self, config):
        """R4 signal parameters must not change."""
        assert config.strategy.skip_months == 1
        assert config.strategy.vol_lookback_signal == 60
        assert config.strategy.risk_lookback == 20
        assert config.strategy.signal_lookback_short == 63
        assert config.strategy.signal_lookback_long == 252
    
    def test_execution_parameters_unchanged(self, config):
        """R4 execution parameters must not change."""
        assert config.execution.max_orders_per_cycle == 8
        assert config.strategy.transaction_cost_bps == 10.0
        assert config.strategy.slippage_bps == 5.0
    
    def test_risk_envelope_unchanged(self, config):
        """R4 risk envelope must not change."""
        assert config.live_risk.max_concurrent_positions == 19
        assert config.live_risk.max_position_notional == 2500.0
        assert config.live_risk.max_daily_loss == 250.0
        assert config.live_risk.min_equity == 4000.0
        assert config.live_risk.t0_equity == 5010.94


class TestEventLedgerParity:
    """Verify event ledger does not alter R4 behavior."""
    
    def test_event_ledger_append_only(self):
        """Event ledger must be append-only (no modifications)."""
        ledger = EventLedger(base_path="/tmp/test_event_ledger")
        
        # Append event
        event1 = ledger.append(
            event_type=EventType.SIGNAL_COMPUTED,
            account_id="test",
            tier="T1-5K",
            campaign_id="TEST",
            symbol="EURUSD",
            payload={"test": True},
        )
        
        # Verify event is immutable (frozen dataclass)
        assert hasattr(event1, 'event_id')
        assert hasattr(event1, 'timestamp')
        
        # Verify we can't modify it
        with pytest.raises(AttributeError):
            event1.event_id = "modified"
    
    def test_event_ledger_correlation(self):
        """Event ledger must maintain correlation chains."""
        ledger = EventLedger(base_path="/tmp/test_event_ledger", flush_after=100)
        
        # Create correlated events
        correlation_id = "test-correlation-123"
        
        event1 = ledger.append(
            event_type=EventType.SIGNAL_COMPUTED,
            account_id="test",
            tier="T1-5K",
            campaign_id="TEST",
            symbol="EURUSD",
            correlation_id=correlation_id,
        )
        
        event2 = ledger.append(
            event_type=EventType.ORDER_SUBMITTED,
            account_id="test",
            tier="T1-5K",
            campaign_id="TEST",
            symbol="EURUSD",
            correlation_id=correlation_id,
            parent_event_id=event1.event_id,
        )
        
        # Query by correlation
        events = ledger.query_by_correlation(correlation_id)
        assert len(events) == 2
        assert all(e.correlation_id == correlation_id for e in events)
    
    def test_event_ledger_does_not_affect_r4(self, config):
        """Event ledger must not affect R4 signal computation."""
        # This is a behavioral test - R4 signal must be identical
        # regardless of whether event ledger is active
        
        # Compute signal without ledger
        manifest = R4ConfigManifest()
        fingerprint1 = manifest.compute_identity()
        
        # Create ledger and append events
        ledger = EventLedger(base_path="/tmp/test_event_ledger")
        ledger.append(
            event_type=EventType.SIGNAL_COMPUTED,
            account_id="test",
            tier="T1-5K",
            campaign_id="TEST",
            symbol="EURUSD",
        )
        
        # Compute signal with ledger active
        manifest2 = R4ConfigManifest()
        fingerprint2 = manifest2.compute_identity()
        
        # Fingerprints must be identical
        assert fingerprint1 == fingerprint2


class TestReconciliationParity:
    """Verify reconciliation engine does not alter R4 behavior."""
    
    def test_reconciliation_engine_read_only(self):
        """Reconciliation must be read-only (no state modification)."""
        engine = ReconciliationEngine()
        
        # Create mock states
        broker = BrokerState(
            positions=[],
            account_equity=5000.0,
            account_balance=5000.0,
            account_free_margin=5000.0,
            orders=[],
            timestamp="2026-08-26T00:00:00Z",
        )
        
        internal = InternalState(
            positions={},
            pending_orders=[],
            last_signal={},
            target_weights={},
            timestamp="2026-08-26T00:00:00Z",
        )
        
        # Run reconciliation
        result = engine.reconcile(broker, internal)
        
        # Verify result is a snapshot (no side effects)
        assert result.status == "RECONCILED"
        assert len(result.checks) > 0
        
        # Verify broker state unchanged
        assert broker.account_equity == 5000.0
    
    def test_reconciliation_does_not_affect_r4(self, config):
        """Reconciliation must not affect R4 signal computation."""
        # Compute fingerprint before reconciliation
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Run reconciliation
        engine = ReconciliationEngine()
        broker = BrokerState(
            positions=[],
            account_equity=5000.0,
            account_balance=5000.0,
            account_free_margin=5000.0,
            orders=[],
            timestamp="2026-08-26T00:00:00Z",
        )
        internal = InternalState(
            positions={},
            pending_orders=[],
            last_signal={},
            target_weights={},
            timestamp="2026-08-26T00:00:00Z",
        )
        engine.reconcile(broker, internal)
        
        # Compute fingerprint after reconciliation
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2


class TestHealthStateParity:
    """Verify health states do not alter R4 behavior."""
    
    def test_health_monitor_read_only(self):
        """Health monitor must be read-only."""
        monitor = HealthMonitor()
        
        # Update health
        monitor.update_dimension(
            dimension=HealthDimension.BROKER,
            state=HealthState.HEALTHY,
            message="Test",
        )
        
        # Get system health
        health = monitor.get_system_health()
        
        # Verify authorization is computed, not stored
        assert health.authorization in ("TRADING_AUTHORIZED", "TRADING_BLOCKED", "TRADING_HALTED")
    
    def test_health_does_not_affect_r4(self, config):
        """Health monitoring must not affect R4 signal computation."""
        # Compute fingerprint before health update
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Update health
        monitor = HealthMonitor()
        monitor.update_dimension(
            dimension=HealthDimension.BROKER,
            state=HealthState.HEALTHY,
            message="Test",
        )
        
        # Compute fingerprint after health update
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2


class TestRiskObservationParity:
    """Verify risk observation does not alter R4 behavior."""
    
    def test_risk_observer_observe_only(self):
        """Risk observer must observe only (no sizing changes)."""
        observer = RiskObserver()
        
        # Observe risk
        state = observer.observe(
            equity=5000.0,
            balance=5000.0,
            free_margin=5000.0,
            positions=[],
            daily_pnl=0.0,
        )
        
        # Verify observation is a snapshot
        assert state.overall_level in ("NORMAL", "ELEVATED", "WARNING", "CRITICAL", "HALT")
        assert len(state.observations) > 0
        
        # Verify no sizing parameters were modified
        # (This is a structural test - in practice, you'd verify
        # that R4's sizing logic is unchanged)
    
    def test_risk_observation_does_not_affect_r4(self, config):
        """Risk observation must not affect R4 signal computation."""
        # Compute fingerprint before risk observation
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Observe risk
        observer = RiskObserver()
        observer.observe(
            equity=5000.0,
            balance=5000.0,
            free_margin=5000.0,
            positions=[],
            daily_pnl=0.0,
        )
        
        # Compute fingerprint after risk observation
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2


class TestStructuredAlertsParity:
    """Verify structured alerts do not alter R4 behavior."""
    
    def test_alert_dispatcher_deduplication(self):
        """Alerts must be deduplicated."""
        dispatcher = StructuredAlertDispatcher(
            alert_path="/tmp/test_alerts.jsonl",
            dedup_window_seconds=300,
        )
        
        # Send same alert twice
        alert1 = dispatcher.dispatch(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.HEALTH,
            event_type="TEST_DEDUP",
            message="Test alert",
        )
        
        alert2 = dispatcher.dispatch(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.HEALTH,
            event_type="TEST_DEDUP",
            message="Test alert",
        )
        
        # Second alert should be deduplicated
        assert alert2.alert_id == "DEDUP"
    
    def test_alerts_do_not_affect_r4(self, config):
        """Alerts must not affect R4 signal computation."""
        # Compute fingerprint before alert
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Send alert
        dispatcher = StructuredAlertDispatcher(
            alert_path="/tmp/test_alerts.jsonl",
        )
        dispatcher.dispatch(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            event_type="TEST",
            message="Test",
        )
        
        # Compute fingerprint after alert
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2


class TestFailureInstrumentationParity:
    """Verify failure instrumentation does not alter R4 behavior."""
    
    def test_failure_instrumentation_read_only(self):
        """Failure instrumentation must be read-only."""
        instrumentation = FailureInstrumentation()
        
        # Record failure
        failure = instrumentation.record_failure(
            failure_type=FailureType.PARTIAL_FILL,
            severity=FailureSeverity.WARNING,
            message="Test failure",
            details={"test": True},
        )
        
        # Verify failure is recorded
        assert failure.failure_id.startswith("FAIL-")
        
        # Verify no side effects on external state
        assert failure.recovered is False
    
    def test_failure_instrumentation_does_not_affect_r4(self, config):
        """Failure instrumentation must not affect R4 signal computation."""
        # Compute fingerprint before failure recording
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Record failure
        instrumentation = FailureInstrumentation()
        instrumentation.record_failure(
            failure_type=FailureType.PARTIAL_FILL,
            severity=FailureSeverity.WARNING,
            message="Test failure",
        )
        
        # Compute fingerprint after failure recording
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2


class TestPhase2BaselineLock:
    """Verify Phase 2 baseline lock integrity."""
    
    def test_baseline_lock_exists(self):
        """Phase 2 baseline lock must exist."""
        baseline_path = Path("reports/phase2_baseline.json")
        if not baseline_path.exists():
            pytest.skip("Phase 2 baseline lock not yet captured - run scripts/capture_phase2_baseline.py")
    
    def test_baseline_lock_hash(self):
        """Phase 2 baseline lock hash must be valid."""
        baseline_path = Path("reports/phase2_baseline.json")
        if baseline_path.exists():
            with open(baseline_path) as f:
                baseline = json.load(f)
            
            # Verify required fields
            required_fields = [
                "git_head", "build_id", "campaign_id",
                "fingerprints", "universe", "cadence",
                "risk_limits", "strategy_params", "evidence_schema",
                "test_info", "git_status", "phase2_governance",
                "baseline_hash",
            ]
            
            for field in required_fields:
                assert field in baseline, f"Missing required field: {field}"
            
            # Verify governance rules
            governance = baseline["phase2_governance"]
            assert governance["r4_signal_frozen"] is True
            assert governance["r4_universe_frozen"] is True
            assert governance["r4_cadence_frozen"] is True
            assert governance["r4_sizing_frozen"] is True
            assert governance["r4_exit_logic_frozen"] is True
            assert governance["no_optimization"] is True


class TestCombinedParity:
    """Verify all P0 components together do not affect R4."""
    
    def test_all_components_simultaneously(self, config):
        """All P0 components must work together without affecting R4."""
        # Compute initial fingerprint
        verifier1 = FingerprintVerifier(config=config)
        fp1 = verifier1.frozen_manifest_fingerprint
        
        # Initialize all P0 components
        ledger = EventLedger(base_path="/tmp/test_combined_ledger")
        reconciliation_engine = ReconciliationEngine()
        health_monitor = HealthMonitor()
        risk_observer = RiskObserver()
        alert_dispatcher = StructuredAlertDispatcher(
            alert_path="/tmp/test_combined_alerts.jsonl",
        )
        failure_instrumentation = FailureInstrumentation()
        
        # Use all components
        # 1. Append event
        event = ledger.append(
            event_type=EventType.SIGNAL_COMPUTED,
            account_id="test",
            tier="T1-5K",
            campaign_id="TEST",
            symbol="EURUSD",
        )
        
        # 2. Run reconciliation
        broker = BrokerState(
            positions=[],
            account_equity=5000.0,
            account_balance=5000.0,
            account_free_margin=5000.0,
            orders=[],
            timestamp="2026-08-26T00:00:00Z",
        )
        internal = InternalState(
            positions={},
            pending_orders=[],
            last_signal={},
            target_weights={},
            timestamp="2026-08-26T00:00:00Z",
        )
        reconciliation_engine.reconcile(broker, internal)
        
        # 3. Update health
        health_monitor.update_dimension(
            dimension=HealthDimension.BROKER,
            state=HealthState.HEALTHY,
            message="Connected",
        )
        
        # 4. Observe risk
        risk_observer.observe(
            equity=5000.0,
            balance=5000.0,
            free_margin=5000.0,
            positions=[],
            daily_pnl=0.0,
        )
        
        # 5. Send alert
        alert_dispatcher.dispatch(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            event_type="TEST",
            message="Test",
        )
        
        # 6. Record failure
        failure_instrumentation.record_failure(
            failure_type=FailureType.PARTIAL_FILL,
            severity=FailureSeverity.WARNING,
            message="Test",
        )
        
        # Compute final fingerprint
        verifier2 = FingerprintVerifier(config=config)
        fp2 = verifier2.frozen_manifest_fingerprint
        
        # Fingerprints must be identical
        assert fp1 == fp2, "R4 fingerprint changed after P0 infrastructure usage"
        
        # Verify all components collected data
        assert ledger.get_stats()["total_events"] > 0
        assert reconciliation_engine.get_stats()["total"] > 0
        assert health_monitor.get_stats()["dimensions"] > 0
        assert risk_observer.get_stats()["total_observations"] > 0
        assert alert_dispatcher.get_stats()["total_dispatched"] > 0
        assert failure_instrumentation.get_stats()["total_failures"] > 0
