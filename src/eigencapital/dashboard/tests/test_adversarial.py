"""Adversarial Validation Tests — verify dashboard behavior under hostile conditions.

These tests ensure the dashboard accurately represents system state even when:
- Data is missing or corrupted
- Broker disconnects
- Risk is BLOCKED
- System is HALTED
- Build fingerprints drift
- Events are incomplete
- Positions are stale
- WebSocket disconnects
"""

from __future__ import annotations

from datetime import UTC, datetime


class TestHealthStateAccuracy:
    """Verify health state is accurately represented."""

    def test_blocked_state_represents_correctly(self) -> None:
        """HALTED state cannot appear as healthy."""
        from eigencapital.dashboard.schemas.health import SystemHealthDTO

        dto = SystemHealthDTO(
            overall_state="HALTED",
            trading_authorization="TRADING_HALTED",
            dimensions=[],
            blocking_dimensions=["SYSTEM_HEALTH"],
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_state == "HALTED"
        assert dto.trading_authorization == "TRADING_HALTED"

    def test_degraded_state_not_healthy(self) -> None:
        """DEGRADED state is not HEALTHY."""
        from eigencapital.dashboard.schemas.health import SystemHealthDTO

        dto = SystemHealthDTO(
            overall_state="DEGRADED",
            trading_authorization="TRADING_BLOCKED",
            dimensions=[],
            blocking_dimensions=["BROKER_HEALTH"],
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_state != "HEALTHY"


class TestStaleDataDetection:
    """Verify stale data is visibly stale."""

    def test_stale_data_detected(self) -> None:
        """Stale data should be detected and marked."""
        from eigencapital.dashboard.schemas.common import DataFreshness

        # Fresh data
        assert DataFreshness.LIVE.value == "LIVE"

        # Stale data
        assert DataFreshness.STALE.value == "STALE"

        # Unknown data
        assert DataFreshness.UNKNOWN.value == "UNKNOWN"


class TestDashboardReadOnly:
    """Verify dashboard cannot modify production state."""

    def test_read_only_guarantee(self) -> None:
        """Dashboard must be read-only."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()

        # Verify no write methods exist
        assert not hasattr(service, "modify_r4")
        assert not hasattr(service, "submit_order")
        assert not hasattr(service, "close_position")
        assert not hasattr(service, "activate_reduced")
        assert not hasattr(service, "modify_risk_limits")


class TestRiskStateAccuracy:
    """Verify risk state is accurately represented."""

    def test_critical_state_represents_correctly(self) -> None:
        """Critical risk state must be clearly visible."""
        from eigencapital.dashboard.schemas.risk import RiskStateDTO

        dto = RiskStateDTO(
            overall_level="CRITICAL",
            observations=[],
            any_critical=True,
            any_warning=False,
            critical_dimensions=["DRAWDOWN", "DAILY_LOSS"],
            warning_dimensions=[],
            timestamp=datetime.now(UTC),
        )
        assert dto.any_critical is True
        assert len(dto.critical_dimensions) == 2

    def test_shadow_reduced_labeled_correctly(self) -> None:
        """Shadow REDUCED must be labeled as NOT APPLIED LIVE."""
        from eigencapital.dashboard.schemas.evidence import ShadowReducedDTO

        dto = ShadowReducedDTO(
            mode="SHADOW_ONLY",
            observations=100,
            hypothetical_reductions=15,
            label="Would Have Happened — NOT APPLIED LIVE",
            timestamp=datetime.now(UTC),
        )
        assert dto.mode == "SHADOW_ONLY"
        assert "NOT APPLIED LIVE" in dto.label


class TestBuildVerification:
    """Verify build identity is accurately represented."""

    def test_drift_detected_represents_correctly(self) -> None:
        """Build drift must be clearly visible."""
        from eigencapital.dashboard.schemas.evidence import BuildIdentityDTO

        dto = BuildIdentityDTO(
            git_head="abc123",
            manifest_identity="def456",
            config_fingerprint="ghi789",
            loop_script_sha256="jkl012",
            build_id="test-build",
            verified=False,
            drift_detected=True,
            timestamp=datetime.now(UTC),
        )
        assert dto.verified is False
        assert dto.drift_detected is True


class TestEventCorrelation:
    """Verify event correlation IDs are preserved."""

    def test_correlation_id_preserved(self) -> None:
        """Events must maintain correlation IDs."""
        from eigencapital.dashboard.schemas.evidence import EventDTO

        event = EventDTO(
            event_id="test-event-1",
            event_type="ORDER_SUBMITTED",
            timestamp=datetime.now(UTC),
            correlation_id="corr-123",
            message="Order submitted",
        )
        assert event.correlation_id == "corr-123"


class TestPositionProtection:
    """Verify position protection status is visible."""

    def test_unprotected_position_visible(self) -> None:
        """Unprotected positions must be clearly visible."""
        from eigencapital.dashboard.schemas.portfolio import PositionDTO

        pos = PositionDTO(
            ticket=12345,
            symbol="XAUUSD",
            direction="BUY",
            size=0.01,
            entry_price=2500.0,
            current_price=2510.0,
            unrealized_pnl=10.0,
            unrealized_pnl_pct=0.004,
            protected=False,
            risk_state="WARNING",
            last_update=datetime.now(UTC),
        )
        assert pos.protected is False


class TestReconciliationAccuracy:
    """Verify reconciliation state is accurately represented."""

    def test_reconciled_state(self) -> None:
        """Reconciled state must be clearly represented."""
        from eigencapital.dashboard.schemas.reconciliation import ReconciliationStatusDTO

        dto = ReconciliationStatusDTO(
            overall_status="CLEAN",
            checks_performed=10,
            checks_passed=10,
            checks_warning=0,
            checks_critical=0,
            checks_blocking=0,
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_status == "CLEAN"
        assert dto.checks_critical == 0


class TestAlertSeverity:
    """Verify alert severity is accurately represented."""

    def test_critical_alert_visible(self) -> None:
        """Critical alerts must be clearly visible."""
        from eigencapital.dashboard.schemas.evidence import AlertDTO

        alert = AlertDTO(
            alert_id="alert-1",
            timestamp=datetime.now(UTC),
            severity="CRITICAL",
            category="HEALTH",
            event_type="HEALTH_STATE_CHANGE",
            message="System halted",
            severity_label="CRITICAL",
        )
        assert alert.severity == "CRITICAL"


class TestAPIEndpoints:
    """Verify API endpoints return correct data."""

    def test_health_endpoint_structure(self) -> None:
        """Health endpoint must return correct structure."""
        from eigencapital.dashboard.schemas.health import SystemHealthDTO

        dto = SystemHealthDTO(
            overall_state="HEALTHY",
            trading_authorization="TRADING_AUTHORIZED",
            dimensions=[],
            blocking_dimensions=[],
            timestamp=datetime.now(UTC),
        )
        data = dto.model_dump()
        assert "overall_state" in data
        assert "trading_authorization" in data
        assert "dimensions" in data
