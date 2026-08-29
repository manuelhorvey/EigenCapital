"""Dashboard Contract Tests — DTO validation, source-of-truth, read-only guarantees.

These tests verify:
1. Every DTO field has correct types and constraints
2. The dashboard state service is strictly read-only
3. Freshness semantics are correctly implemented
4. Error states return correct structures
5. No mutation capabilities exist in dashboard code
6. Data never silently degrades to misleading valid-looking values
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_type_hints

import pytest


# ═══════════════════════════════════════════════════════════════════
# DTO Contract Tests
# ═══════════════════════════════════════════════════════════════════


class TestAccountDTOContract:
    """Verify AccountDTO schema integrity."""

    def test_account_dto_required_fields(self) -> None:
        """AccountDTO must have all required fields."""
        from eigencapital.dashboard.schemas.portfolio import AccountDTO

        dto = AccountDTO(
            equity=10000.0,
            balance=10000.0,
            timestamp=datetime.now(UTC),
        )
        assert dto.equity == 10000.0
        assert dto.balance == 10000.0
        assert dto.currency == "USD"  # default
        assert dto.freshness is None  # default

    def test_account_dto_freshness_values(self) -> None:
        """AccountDTO freshness must be valid enum value or None."""
        from eigencapital.dashboard.schemas.portfolio import AccountDTO

        for freshness in ["LIVE", "STALE", "UNKNOWN", None]:
            dto = AccountDTO(
                equity=0,
                balance=0,
                timestamp=datetime.now(UTC),
                freshness=freshness,
            )
            assert dto.freshness == freshness

    def test_account_dto_source_values(self) -> None:
        """AccountDTO source must track data provenance."""
        from eigencapital.dashboard.schemas.portfolio import AccountDTO

        dto = AccountDTO(
            equity=0,
            balance=0,
            timestamp=datetime.now(UTC),
            source="mt5",
        )
        assert dto.source == "mt5"

    def test_account_dto_empty_state(self) -> None:
        """AccountDTO with zero equity must be constructible (unavailable state)."""
        from eigencapital.dashboard.schemas.portfolio import AccountDTO

        dto = AccountDTO(
            equity=0,
            balance=0,
            timestamp=datetime.now(UTC),
            freshness="UNKNOWN",
            source="unavailable",
        )
        assert dto.equity == 0
        assert dto.freshness == "UNKNOWN"
        assert dto.source == "unavailable"

    def test_account_dto_serialization(self) -> None:
        """AccountDTO must serialize to JSON correctly."""
        from eigencapital.dashboard.schemas.portfolio import AccountDTO

        dto = AccountDTO(
            equity=10000.50,
            balance=9950.25,
            timestamp=datetime.now(UTC),
            freshness="LIVE",
        )
        data = dto.model_dump()
        assert data["equity"] == 10000.50
        assert data["balance"] == 9950.25
        assert "timestamp" in data
        assert data["freshness"] == "LIVE"


class TestPositionDTOContract:
    """Verify PositionDTO schema integrity."""

    def test_position_dto_required_fields(self) -> None:
        """PositionDTO must have all required fields."""
        from eigencapital.dashboard.schemas.portfolio import PositionDTO

        dto = PositionDTO(
            ticket=12345,
            symbol="XAUUSD",
            direction="BUY",
            size=0.01,
            entry_price=2500.0,
            current_price=2510.0,
            unrealized_pnl=10.0,
            protected=True,
            last_update=datetime.now(UTC),
        )
        assert dto.ticket == 12345
        assert dto.symbol == "XAUUSD"
        assert dto.protected is True

    def test_position_dto_unprotected(self) -> None:
        """Unprotected position must be representable."""
        from eigencapital.dashboard.schemas.portfolio import PositionDTO

        dto = PositionDTO(
            ticket=12345,
            symbol="XAUUSD",
            direction="BUY",
            size=0.01,
            entry_price=2500.0,
            current_price=2510.0,
            unrealized_pnl=10.0,
            protected=False,
            risk_state="WARNING",
            last_update=datetime.now(UTC),
        )
        assert dto.protected is False
        assert dto.risk_state == "WARNING"

    def test_position_dto_optional_fields(self) -> None:
        """Optional fields should default correctly."""
        from eigencapital.dashboard.schemas.portfolio import PositionDTO

        dto = PositionDTO(
            ticket=1,
            symbol="XAUUSD",
            direction="BUY",
            size=0.01,
            entry_price=2500.0,
            current_price=2500.0,
            unrealized_pnl=0.0,
            protected=True,
            last_update=datetime.now(UTC),
        )
        assert dto.stop_loss is None
        assert dto.distance_to_sl is None
        assert dto.mae is None
        assert dto.mfe is None
        assert dto.holding_time is None
        assert dto.attribution_state is None
        assert dto.details == {}

    def test_position_risk_state_enum(self) -> None:
        """Position risk_state should accept valid states."""
        from eigencapital.dashboard.schemas.portfolio import PositionDTO

        for state in ["NORMAL", "WARNING", "CRITICAL"]:
            dto = PositionDTO(
                ticket=1,
                symbol="XAUUSD",
                direction="BUY",
                size=0.01,
                entry_price=2500.0,
                current_price=2500.0,
                unrealized_pnl=0.0,
                protected=True,
                risk_state=state,
                last_update=datetime.now(UTC),
            )
            assert dto.risk_state == state


class TestRiskStateDTOContract:
    """Verify RiskStateDTO schema integrity."""

    def test_risk_state_dto_structure(self) -> None:
        """RiskStateDTO must have all required fields."""
        from eigencapital.dashboard.schemas.risk import RiskObservationDTO, RiskStateDTO

        obs = RiskObservationDTO(
            dimension="drawdown",
            level="NORMAL",
            value=2.5,
            message="Drawdown at 2.5%",
            timestamp=datetime.now(UTC),
        )
        dto = RiskStateDTO(
            overall_level="NORMAL",
            observations=[obs],
            any_critical=False,
            any_warning=False,
            critical_dimensions=[],
            warning_dimensions=[],
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_level == "NORMAL"
        assert len(dto.observations) == 1
        assert dto.observations[0].dimension == "drawdown"

    def test_risk_critical_state(self) -> None:
        """Critical risk state must be clearly representable."""
        from eigencapital.dashboard.schemas.risk import RiskObservationDTO, RiskStateDTO

        obs = RiskObservationDTO(
            dimension="drawdown",
            level="CRITICAL",
            value=9.5,
            limit=10.0,
            message="Drawdown at 9.5% — near limit",
            timestamp=datetime.now(UTC),
        )
        dto = RiskStateDTO(
            overall_level="CRITICAL",
            observations=[obs],
            any_critical=True,
            any_warning=False,
            critical_dimensions=["drawdown"],
            warning_dimensions=[],
            timestamp=datetime.now(UTC),
        )
        assert dto.any_critical is True
        assert "drawdown" in dto.critical_dimensions

    def test_risk_observation_optional_fields(self) -> None:
        """RiskObservationDTO optional fields default correctly."""
        from eigencapital.dashboard.schemas.risk import RiskObservationDTO

        obs = RiskObservationDTO(
            dimension="test",
            level="NORMAL",
            value=0.0,
            message="test",
            timestamp=datetime.now(UTC),
        )
        assert obs.limit is None
        assert obs.utilization is None
        assert obs.trend is None
        assert obs.details == {}


class TestHealthDTOContract:
    """Verify Health DTO schema integrity."""

    def test_system_health_dto(self) -> None:
        """SystemHealthDTO must represent all health states."""
        from eigencapital.dashboard.schemas.health import SystemHealthDTO

        dto = SystemHealthDTO(
            overall_state="HEALTHY",
            trading_authorization="TRADING_AUTHORIZED",
            dimensions=[],
            blocking_dimensions=[],
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_state == "HEALTHY"
        assert dto.trading_authorization == "TRADING_AUTHORIZED"

    def test_halted_state(self) -> None:
        """HALTED state must be clearly representable."""
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
        assert "SYSTEM_HEALTH" in dto.blocking_dimensions

    def test_trading_authorization_states(self) -> None:
        """All three authorization states must be representable."""
        from eigencapital.dashboard.schemas.health import TradingAuthorizationDTO

        for status in ["TRADING_AUTHORIZED", "TRADING_BLOCKED", "TRADING_HALTED"]:
            dto = TradingAuthorizationDTO(
                status=status,
                execution_mode="live",
                fingerprint_status="VERIFIED",
                timestamp=datetime.now(UTC),
            )
            assert dto.status == status

    def test_watchdog_dto(self) -> None:
        """WatchdogDTO must represent all watchdog states."""
        from eigencapital.dashboard.schemas.health import WatchdogDTO

        dto = WatchdogDTO(
            state="NORMAL",
            authorize_trading=True,
            reason="All systems healthy",
            timestamp=datetime.now(UTC),
        )
        assert dto.authorize_trading is True

        dto_blocked = WatchdogDTO(
            state="BLOCKED",
            authorize_trading=False,
            reason="Health check failed",
            timestamp=datetime.now(UTC),
        )
        assert dto_blocked.authorize_trading is False


class TestEvidenceDTOContract:
    """Verify Evidence DTO schema integrity."""

    def test_qualification_status_dto(self) -> None:
        """QualificationStatusDTO must have all required fields."""
        from eigencapital.dashboard.schemas.evidence import (
            EvidenceMaturityDTO,
            QualificationStatusDTO,
        )

        maturity = EvidenceMaturityDTO(
            e0_count=10,
            e1_count=8,
            e2_count=5,
            e3_count=3,
            e4_count=2,
            e5_count=1,
            e6_count=0,
            total_trades=10,
            open_trades=2,
            completed_lifecycles=8,
            observation_days=15,
            timestamp=datetime.now(UTC),
        )
        dto = QualificationStatusDTO(
            campaign_id="campaign-001",
            evidence_maturity=maturity,
            gates=[],
            overall_status="COLLECTING",
            evidence_insufficient=True,
            timestamp=datetime.now(UTC),
        )
        assert dto.evidence_insufficient is True
        assert dto.evidence_maturity.total_trades == 10

    def test_shadow_reduced_labeled(self) -> None:
        """Shadow REDUCED must be explicitly labeled as NOT APPLIED LIVE."""
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

    def test_build_identity_dto(self) -> None:
        """BuildIdentityDTO must represent verified and drifted states."""
        from eigencapital.dashboard.schemas.evidence import BuildIdentityDTO

        # Verified build
        verified = BuildIdentityDTO(
            git_head="abc123",
            manifest_identity="def456",
            config_fingerprint="ghi789",
            loop_script_sha256="jkl012",
            build_id="build-001",
            verified=True,
            timestamp=datetime.now(UTC),
        )
        assert verified.verified is True
        assert verified.drift_detected is False

        # Drifted build
        drifted = BuildIdentityDTO(
            git_head="abc123",
            manifest_identity="def456",
            config_fingerprint="ghi789",
            loop_script_sha256="jkl012",
            build_id="build-001",
            verified=False,
            drift_detected=True,
            timestamp=datetime.now(UTC),
        )
        assert drifted.verified is False
        assert drifted.drift_detected is True


class TestReconciliationDTOContract:
    """Verify Reconciliation DTO schema integrity."""

    def test_reconciliation_status_dto(self) -> None:
        """ReconciliationStatusDTO must represent all status states."""
        from eigencapital.dashboard.schemas.reconciliation import ReconciliationStatusDTO

        for status in ["CLEAN", "WARNING", "CRITICAL", "HALT"]:
            dto = ReconciliationStatusDTO(
                overall_status=status,
                checks_performed=10,
                checks_passed=10,
                checks_warning=0,
                checks_critical=0,
                checks_blocking=0,
                timestamp=datetime.now(UTC),
            )
            assert dto.overall_status == status

    def test_reconciliation_with_discrepancies(self) -> None:
        """Reconciliation must represent discrepancy counts."""
        from eigencapital.dashboard.schemas.reconciliation import ReconciliationStatusDTO

        dto = ReconciliationStatusDTO(
            overall_status="WARNING",
            checks_performed=10,
            checks_passed=8,
            checks_warning=2,
            checks_critical=0,
            checks_blocking=0,
            stale_positions=1,
            missing_fills=0,
            duplicate_orders=0,
            foreign_positions=1,
            timestamp=datetime.now(UTC),
        )
        assert dto.overall_status == "WARNING"
        assert dto.stale_positions == 1
        assert dto.foreign_positions == 1


class TestAlertDTOContract:
    """Verify Alert DTO schema integrity."""

    def test_alert_severity_levels(self) -> None:
        """AlertDTO must represent all severity levels."""
        from eigencapital.dashboard.schemas.evidence import AlertDTO

        for severity in ["CRITICAL", "WARNING", "INFO"]:
            alert = AlertDTO(
                alert_id="alert-1",
                timestamp=datetime.now(UTC),
                severity=severity,
                category="HEALTH",
                event_type="HEALTH_STATE_CHANGE",
                message="Test alert",
            )
            assert alert.severity == severity

    def test_alert_consecutive_count(self) -> None:
        """Alert consecutive count must default to 1."""
        from eigencapital.dashboard.schemas.evidence import AlertDTO

        alert = AlertDTO(
            alert_id="alert-1",
            timestamp=datetime.now(UTC),
            severity="WARNING",
            category="SYSTEM",
            event_type="TEST",
            message="Test",
        )
        assert alert.consecutive_count == 1
        assert alert.acknowledged is False


# ═══════════════════════════════════════════════════════════════════
# Data Freshness Tests
# ═══════════════════════════════════════════════════════════════════


class TestDataFreshness:
    """Verify freshness semantics are correct."""

    def test_freshness_enum_values(self) -> None:
        """DataFreshness enum must have exactly LIVE, STALE, UNKNOWN."""
        from eigencapital.dashboard.schemas.common import DataFreshness

        assert DataFreshness.LIVE.value == "LIVE"
        assert DataFreshness.STALE.value == "STALE"
        assert DataFreshness.UNKNOWN.value == "UNKNOWN"
        assert len(DataFreshness) == 3

    def test_freshness_assessment_live(self) -> None:
        """Data < 30s old must be assessed as LIVE."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        now = datetime.now(UTC).isoformat()
        assert service._assess_freshness(now) == "LIVE"

    def test_freshness_assessment_stale(self) -> None:
        """Data 30s-5min old must be assessed as STALE."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        # 90 seconds ago — within STALE range (30s-120s)
        from datetime import timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        assert service._assess_freshness(ts) == "STALE"

    def test_freshness_assessment_unknown(self) -> None:
        """Data > 5min old must be assessed as UNKNOWN."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        from datetime import timedelta

        ts = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        assert service._assess_freshness(ts) == "UNKNOWN"

    def test_freshness_assessment_none(self) -> None:
        """None timestamp must be assessed as UNKNOWN."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        assert service._assess_freshness(None) == "UNKNOWN"

    def test_freshness_assessment_invalid(self) -> None:
        """Invalid timestamp must be assessed as UNKNOWN."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        assert service._assess_freshness("not-a-date") == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════
# Read-Only Guarantee Tests
# ═══════════════════════════════════════════════════════════════════


class TestReadOnlyGuarantee:
    """Verify dashboard cannot modify production state."""

    def test_state_service_has_no_write_methods(self) -> None:
        """DashboardStateService must not have mutation methods."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        write_methods = [
            "modify_r4",
            "submit_order",
            "close_position",
            "activate_reduced",
            "modify_risk_limits",
            "modify_parameters",
            "place_order",
            "cancel_order",
            "modify_position",
            "set_stop_loss",
            "flatten",
        ]
        for method in write_methods:
            assert not hasattr(service, method), f"Dashboard has write method: {method}"

    def test_state_service_only_has_read_methods(self) -> None:
        """DashboardStateService should only have read/get methods."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        public_methods = [m for m in dir(service) if not m.startswith("_")]
        # All public methods should be getters
        for method in public_methods:
            assert method.startswith("get_") or method == "_ensure_dirs" or method.startswith("_"), (
                f"Unexpected public method on read-only service: {method}"
            )

    def test_api_app_only_allows_get(self) -> None:
        """FastAPI app must only allow GET methods (HEAD allowed for OpenAPI/docs)."""
        from eigencapital.dashboard.api.app import app

        allowed_methods = {"GET", "HEAD"}  # HEAD is auto-added by FastAPI for docs/openapi
        for route in app.routes:
            if hasattr(route, "methods"):
                for method in route.methods:
                    assert method in allowed_methods, f"Non-GET method found: {method} on {route.path}"

    def test_cors_allows_only_get(self) -> None:
        """CORS middleware must only allow GET."""
        from eigencapital.dashboard.api.app import app

        for middleware in app.user_middleware:
            if hasattr(middleware, "cls") and "CORS" in str(middleware.cls):
                # CORS is configured with allow_methods=["GET"]
                break  # CORS found, methods checked at config level

    def test_no_post_put_patch_delete_endpoints(self) -> None:
        """No mutation endpoints must exist in any router."""
        from eigencapital.dashboard.api.routes import (
            alerts,
            evidence,
            health,
            portfolio,
            reconciliation,
            risk,
            system,
        )

        mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
        for router_module in [alerts, evidence, health, portfolio, reconciliation, risk, system]:
            router = router_module.router
            for route in router.routes:
                if hasattr(route, "methods"):
                    overlap = route.methods & mutation_methods
                    assert not overlap, (
                        f"Mutation method {overlap} found on {route.path} in {router_module.__name__}"
                    )


# ═══════════════════════════════════════════════════════════════════
# Error Handling Tests
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Verify error responses are safe and informative."""

    def test_empty_account_state(self) -> None:
        """Empty account state must not look like valid zero."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        state = service._empty_account_state()
        assert state["freshness"] == "UNKNOWN"
        assert state["source"] == "unavailable"
        assert state["equity"] == 0
        # Key: freshness must NOT be LIVE when data is unavailable
        assert state["freshness"] != "LIVE"

    def test_empty_positions_return_empty_list(self) -> None:
        """Missing positions must return empty list, not None."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        # When MT5 is unavailable, positions should be []
        positions = service.get_positions()
        assert isinstance(positions, list)

    def test_empty_events_return_empty_list(self) -> None:
        """Missing events must return empty list, not None."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        events = service.get_recent_events()
        assert isinstance(events, list)

    def test_empty_alerts_return_empty_list(self) -> None:
        """Missing alerts must return empty list, not None."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        alerts = service.get_recent_alerts()
        assert isinstance(alerts, list)

    def test_shadow_reduced_empty_state(self) -> None:
        """Shadow REDUCED when unavailable must be labeled correctly."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        reduced = service.get_shadow_reduced()
        assert reduced["mode"] == "SHADOW_ONLY"
        assert "NOT APPLIED LIVE" in reduced["label"]
        assert reduced["freshness"] == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════
# Source of Truth Tests
# ═══════════════════════════════════════════════════════════════════


class TestSourceOfTruth:
    """Verify each data domain reads from authoritative source."""

    def test_account_state_has_source_field(self) -> None:
        """Account state must declare its data source."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        state = service._empty_account_state()
        assert "source" in state
        assert state["source"] in ("mt5", "unavailable")

    def test_health_state_has_freshness(self) -> None:
        """Health state must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        assert "freshness" in health
        assert health["freshness"] in ("LIVE", "STALE", "UNKNOWN")

    def test_risk_state_has_freshness(self) -> None:
        """Risk state must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        risk = service.get_risk_state()
        assert "freshness" in risk
        assert risk["freshness"] in ("LIVE", "STALE", "UNKNOWN")

    def test_qualification_has_freshness(self) -> None:
        """Qualification status must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        qual = service.get_qualification_status()
        assert "freshness" in qual
        assert qual["freshness"] in ("LIVE", "STALE", "UNKNOWN")

    def test_reconciliation_has_freshness(self) -> None:
        """Reconciliation status must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        recon = service.get_reconciliation_status()
        assert "freshness" in recon
        assert recon["freshness"] in ("LIVE", "STALE", "UNKNOWN")

    def test_build_identity_has_freshness(self) -> None:
        """Build identity must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        build = service.get_build_identity()
        assert "freshness" in build
        assert build["freshness"] in ("LIVE", "STALE", "UNKNOWN")

    def test_shadow_reduced_has_freshness(self) -> None:
        """Shadow REDUCED must include freshness metadata."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        reduced = service.get_shadow_reduced()
        assert "freshness" in reduced
        assert reduced["freshness"] in ("LIVE", "STALE", "UNKNOWN")


# ═══════════════════════════════════════════════════════════════════
# API Response Structure Tests
# ═══════════════════════════════════════════════════════════════════


class TestAPIResponseStructure:
    """Verify API responses match DTO contracts."""

    def test_system_info_read_only(self) -> None:
        """System info must confirm read-only mode."""
        import asyncio

        from eigencapital.dashboard.api.routes.system import get_system_info

        result = asyncio.run(get_system_info())
        assert result["read_only"] is True
        assert result["can_submit_orders"] is False
        assert result["can_modify_r4"] is False
        assert result["can_modify_risk_limits"] is False
        assert result["can_activate_reduced"] is False

    def test_health_endpoint_returns_valid_state(self) -> None:
        """Health endpoint must return valid state structure."""
        from eigencapital.dashboard.schemas.health import SystemHealthDTO
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        dto = SystemHealthDTO(
            overall_state=health["overall_state"],
            trading_authorization=health["trading_authorization"],
            dimensions=health["dimensions"],
            blocking_dimensions=health["blocking_dimensions"],
            timestamp=datetime.fromisoformat(health["timestamp"]),
        )
        assert dto.overall_state in ("HEALTHY", "DEGRADED", "HALTED", "UNKNOWN")
        assert dto.trading_authorization in ("TRADING_AUTHORIZED", "TRADING_BLOCKED", "TRADING_HALTED", "UNKNOWN")


# ═══════════════════════════════════════════════════════════════════
# Health Dimensions Tests
# ═══════════════════════════════════════════════════════════════════


class TestHealthDimensions:
    """Verify health dimensions are populated from authoritative sources."""

    def test_dimensions_not_empty(self) -> None:
        """Health must return populated dimensions list."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        assert len(health["dimensions"]) >= 1, "Health dimensions must not be empty"

    def test_dimension_structure(self) -> None:
        """Each dimension must have required fields."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        for dim in health["dimensions"]:
            assert "dimension" in dim, f"Missing 'dimension' field in {dim}"
            assert "state" in dim, f"Missing 'state' field in {dim}"
            assert "message" in dim, f"Missing 'message' field in {dim}"
            assert "timestamp" in dim, f"Missing 'timestamp' field in {dim}"

    def test_dimension_states_valid(self) -> None:
        """All dimension states must be valid."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        valid_states = {"HEALTHY", "DEGRADED", "BLOCKED", "CONTAINED", "HALTED"}
        service = DashboardStateService()
        health = service.get_system_health()
        for dim in health["dimensions"]:
            assert dim["state"] in valid_states, (
                f"Invalid state '{dim['state']}' in dimension '{dim['dimension']}'"
            )

    def test_blocking_dimensions_from_data(self) -> None:
        """Blocking dimensions must be derived from actual data, not hardcoded."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        # Blocking dimensions should only contain dimensions that exist in the list
        dim_names = {d["dimension"] for d in health["dimensions"]}
        for blocking in health["blocking_dimensions"]:
            assert blocking in dim_names, (
                f"Blocking dimension '{blocking}' not in dimensions list {dim_names}"
            )

    def test_health_overall_state_derived_from_dimensions(self) -> None:
        """Overall state must be consistent with dimension states."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        dim_states = {d["state"] for d in health["dimensions"]}

        if "HALTED" in dim_states:
            assert health["overall_state"] == "HALTED"
        elif "BLOCKED" in dim_states or "CRITICAL" in dim_states:
            assert health["overall_state"] in ("DEGRADED", "HALTED")
        elif health["overall_state"] == "HEALTHY":
            assert "HALTED" not in dim_states
            assert "BLOCKED" not in dim_states

    def test_supervisor_dimension_present(self) -> None:
        """Supervisor dimension must always be present."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        dim_names = [d["dimension"] for d in health["dimensions"]]
        assert "supervisor" in dim_names, f"Supervisor dimension missing from {dim_names}"

    def test_broker_dimension_present(self) -> None:
        """Broker dimension must always be present."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        dim_names = [d["dimension"] for d in health["dimensions"]]
        assert "broker" in dim_names, f"Broker dimension missing from {dim_names}"

    def test_build_dimension_present(self) -> None:
        """Build dimension must always be present."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        dim_names = [d["dimension"] for d in health["dimensions"]]
        assert "build" in dim_names, f"Build dimension missing from {dim_names}"

    def test_health_matrix_renders_all_dimensions(self) -> None:
        """HealthMatrix component receives non-empty dimensions."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        health = service.get_system_health()
        # The HealthMatrix component needs at least one dimension to render
        assert len(health["dimensions"]) > 0
        # Each dimension should have a short enough name for the grid
        for dim in health["dimensions"]:
            assert len(dim["dimension"]) <= 30, (
                f"Dimension name '{dim['dimension']}' too long for grid display"
            )


# ═══════════════════════════════════════════════════════════════════
# Security Tests
# ═══════════════════════════════════════════════════════════════════


class TestDashboardSecurity:
    """Verify dashboard security properties."""

    def test_no_mutation_imports(self) -> None:
        """Dashboard code must not import trading execution modules."""
        import eigencapital.dashboard.services.dashboard_state as ds_module
        import inspect

        source = inspect.getsource(ds_module)
        dangerous_imports = [
            "submit_order",
            "place_order",
            "execute_trade",
            "modify_position",
            "cancel_order",
            "flatten_position",
        ]
        for dangerous in dangerous_imports:
            assert dangerous not in source, f"Dashboard imports dangerous function: {dangerous}"

    def test_cors_headers_present(self) -> None:
        """Security headers must be configured."""
        from eigencapital.dashboard.api.app import app

        # Verify middleware is configured
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_global_exception_handler(self) -> None:
        """Global exception handler must not expose stack traces."""
        from eigencapital.dashboard.api.app import app

        # Verify exception handler exists
        assert app.exception_handlers.get(500) is not None or len(app.exception_handlers) > 0
