"""Phase 2 P1 regression tests — dashboard synchronization fixes.

Covers audit findings (docs/audits/FULL_SYNC_DASHBOARD_AUDIT_2026-09-25.md):
- F-03: alerts ordering (newest-first slice, not oldest)
- F-11/F-12: single-writer rule — dashboard service never writes loop-owned
  state files and does not pass dashboard-owned risk constants to RiskObserver
- F-04: WebSocket authentication + shared broadcaster (no per-connection polls)
- e0_count: qualification maturity counters read from nested evidence_maturity
Contract reference: docs/production/DASHBOARD_CONTRACT.md (§2 T1–T5, §4).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ═══════════════════════════════════════════════════════════════════
# F-03 — Alerts ordering
# ═══════════════════════════════════════════════════════════════════


class TestAlertOrdering:
    """get_recent_alerts must return the NEWEST alerts, newest first (F-03)."""

    @pytest.fixture
    def service_with_monitor(self, tmp_path: Path):
        """Service pointed at a temp reports dir with a synthetic monitor log."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        now = datetime.now(UTC)
        records = []
        for i in range(10):
            ts = (now - timedelta(minutes=100 - i)).isoformat()  # ascending
            records.append(
                json.dumps(
                    {
                        "timestamp": ts,
                        "level": "WARNING",
                        "title": f"alert-{i}",
                        "body": f"body-{i}",
                    }
                )
            )

        reports = tmp_path / "reports"
        loop_dir = reports / "r4_loop"
        loop_dir.mkdir(parents=True)
        (loop_dir / "monitor.jsonl").write_text("\n".join(records) + "\n")

        service = DashboardStateService()
        service._data_dir = reports
        service._loop_dir = loop_dir
        service._evidence_dir = reports / "r4_qualification"
        service._alert_path = reports / "alerts.jsonl"
        service._decisions_path = loop_dir / "decisions.jsonl"
        service._monitor_path = loop_dir / "monitor.jsonl"
        return service

    def test_returns_newest_first(self, service_with_monitor) -> None:
        alerts = service_with_monitor.get_recent_alerts(limit=5)
        assert len(alerts) == 5
        titles = [a.get("category") for a in alerts]
        # Newest records are alert-9..alert-5 (highest timestamps)
        assert titles == ["alert-9", "alert-8", "alert-7", "alert-6", "alert-5"]

    def test_limit_takes_newest_slice_not_oldest(self, service_with_monitor) -> None:
        """The previous [-limit:] bug returned alert-0..alert-4 (oldest)."""
        alerts = service_with_monitor.get_recent_alerts(limit=3)
        titles = [a.get("category") for a in alerts]
        assert titles == ["alert-9", "alert-8", "alert-7"]

    def test_default_limit_returns_newest(self, service_with_monitor) -> None:
        alerts = service_with_monitor.get_recent_alerts()
        assert alerts[0].get("category") == "alert-9"

    def test_severity_normalized(self, service_with_monitor) -> None:
        alerts = service_with_monitor.get_recent_alerts(limit=1)
        assert alerts[0]["severity"] == "WARNING"


# ═══════════════════════════════════════════════════════════════════
# F-11/F-12 — Single-writer rule
# ═══════════════════════════════════════════════════════════════════


class TestSingleWriterRule:
    """Dashboard observes state files; it must never write them (contract §4)."""

    def test_service_has_no_persist_helpers(self) -> None:
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        assert not hasattr(service, "_persist_json")
        assert not hasattr(service, "_append_jsonl")

    def test_derived_qualification_does_not_write_status_file(self, tmp_path: Path) -> None:
        """_derive_qualification_from_evidence must be compute-only."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        evidence_dir = tmp_path / "reports" / "r4_qualification"
        (evidence_dir / "evidence").mkdir(parents=True)
        (evidence_dir / "evidence" / "t1.json").write_text(json.dumps({"evidence_level": "e1"}))

        service = DashboardStateService()
        service._data_dir = tmp_path / "reports"
        service._evidence_dir = evidence_dir
        service._loop_dir = tmp_path / "reports" / "r4_loop"
        service._decisions_path = service._loop_dir / "decisions.jsonl"
        # Isolate from any live MT5 bridge (open_count must be deterministic)
        service.get_positions = lambda: []  # type: ignore[method-assign]

        result = service._derive_qualification_from_evidence()

        assert result["evidence_maturity"]["total_trades"] == 1
        assert not (evidence_dir / "qualification_status.json").exists()

    def test_derived_reconciliation_does_not_write_state_file(self, tmp_path: Path) -> None:
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        loop_dir = tmp_path / "reports" / "r4_loop"
        loop_dir.mkdir(parents=True)

        service = DashboardStateService()
        service._data_dir = tmp_path / "reports"
        service._loop_dir = loop_dir
        # Isolate from any live MT5 bridge (dev machines may have one on :8001)
        service.get_positions = lambda: []  # type: ignore[method-assign]

        status = service.get_reconciliation_status()

        assert status["overall_status"] == "NO_DATA"
        assert not (loop_dir / "reconciliation_state.json").exists()

    def test_risk_observer_constants_not_duplicated(self) -> None:
        """Dashboard must use RiskObserver defaults, not re-declare 0.30/0.80."""
        from eigencapital.dashboard.services import dashboard_state

        source = inspect.getsource(dashboard_state)
        assert "max_concentration_pct=0.30" not in source
        assert "max_margin_utilization=0.80" not in source


# ═══════════════════════════════════════════════════════════════════
# F-04 — WebSocket authentication + shared broadcaster
# ═══════════════════════════════════════════════════════════════════


class TestWebSocketAuth:
    """/ws/live must require the API key (contract §2 T5)."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DASHBOARD_DISABLE_AUTH", raising=False)
        monkeypatch.setenv("DASHBOARD_API_KEY", "test-key-123")
        yield

    def _make_ws(self, token: str | None = None, auth_header: str | None = None):
        from eigencapital.dashboard.streaming.events import _is_authorized

        ws = AsyncMock()
        qp = {}
        if token is not None:
            qp["token"] = token
        ws.query_params = qp
        headers = {}
        if auth_header is not None:
            headers["authorization"] = auth_header
        ws.headers = headers
        return ws, _is_authorized(ws)

    def test_missing_token_rejected(self) -> None:
        _, ok = self._make_ws()
        assert ok is False

    def test_wrong_token_rejected(self) -> None:
        _, ok = self._make_ws(token="wrong")
        assert ok is False

    def test_valid_token_accepted(self) -> None:
        _, ok = self._make_ws(token="test-key-123")
        assert ok is True

    def test_bearer_header_accepted(self) -> None:
        _, ok = self._make_ws(auth_header="Bearer test-key-123")
        assert ok is True

    def test_disable_auth_bypass_is_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DASHBOARD_DISABLE_AUTH", "1")
        from eigencapital.dashboard.streaming.events import _is_authorized

        ws = AsyncMock()
        ws.query_params = {}
        ws.headers = {}
        assert _is_authorized(ws) is True


class TestSharedBroadcaster:
    """One shared broadcaster/cache — no per-connection poll loops (F-04)."""

    def test_state_cache_reuses_snapshot(self) -> None:
        from eigencapital.dashboard.streaming import events

        async def scenario() -> None:
            calls = {"n": 0}

            async def fake_state() -> dict:
                calls["n"] += 1
                return {"type": "state_update", "data": {"seq": calls["n"]}}

            original = events.get_live_state
            events._state_cache = None
            events._state_cache_ts = 0.0
            try:
                events.get_live_state = fake_state  # type: ignore[assignment]
                first = await events.get_live_state_cached()
                second = await events.get_live_state_cached()
                # Same cached object — no re-poll within the max-age window
                assert first is second
                assert calls["n"] == 1
            finally:
                events.get_live_state = original  # type: ignore[assignment]
                events._state_cache = None
                events._state_cache_ts = 0.0

        asyncio.run(scenario())

    def test_module_has_no_per_connection_broadcaster(self) -> None:
        """state_broadcaster must not be spawned inside websocket_live."""
        from eigencapital.dashboard.streaming import events

        source = inspect.getsource(events.websocket_live)
        assert "state_broadcaster" not in source
        # The shared loop exists at module level
        assert inspect.iscoroutinefunction(events._broadcast_loop)


# ═══════════════════════════════════════════════════════════════════
# GET /evidence/qualification — maturity counters are NESTED
# (regression: flat qual.get("e0_count") read always returned 0)
# ═══════════════════════════════════════════════════════════════════


class TestQualificationMaturityNesting:
    """qualification_status.json nests counters under "evidence_maturity"."""

    @staticmethod
    def _run(payload: dict):
        from types import SimpleNamespace

        from eigencapital.dashboard.api.routes import evidence as evidence_routes

        fake = SimpleNamespace(get_qualification_status=lambda: payload)
        return asyncio.run(evidence_routes.get_qualification(state=fake))

    def test_nested_maturity_counts_are_read(self) -> None:
        payload = {
            "campaign_id": "camp-1",
            "overall_status": "COLLECTING",
            "evidence_insufficient": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "evidence_maturity": {
                "e0_count": 7,
                "e1_count": 3,
                "e2_count": 1,
                "e3_count": 0,
                "e4_count": 0,
                "e5_count": 0,
                "e6_count": 0,
                "total_trades": 11,
                "open_trades": 2,
                "completed_lifecycles": 5,
                "observation_days": 42,
            },
            "gates": [],
        }
        dto = self._run(payload)
        maturity = dto.evidence_maturity
        assert maturity.e0_count == 7
        assert maturity.e1_count == 3
        assert maturity.e2_count == 1
        assert maturity.total_trades == 11
        assert maturity.open_trades == 2
        assert maturity.completed_lifecycles == 5
        assert maturity.observation_days == 42

    def test_missing_maturity_block_defaults_to_zero(self) -> None:
        """No observed counters → 0, never a fabricated number (contract T3)."""
        dto = self._run(
            {
                "campaign_id": "camp-1",
                "overall_status": "UNKNOWN",
                "evidence_insufficient": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "gates": [],
            }
        )
        assert dto.evidence_maturity.e0_count == 0
        assert dto.evidence_maturity.total_trades == 0

    def test_flat_keys_still_supported(self) -> None:
        """Legacy flat payloads (pre-nesting shape) keep working."""
        dto = self._run(
            {
                "campaign_id": "camp-1",
                "overall_status": "OK",
                "evidence_insufficient": False,
                "timestamp": datetime.now(UTC).isoformat(),
                "e0_count": 4,
                "total_trades": 9,
                "gates": [],
            }
        )
        assert dto.evidence_maturity.e0_count == 4
        assert dto.evidence_maturity.total_trades == 9
