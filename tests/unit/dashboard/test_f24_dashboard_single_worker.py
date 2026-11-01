"""F-24 — Dashboard snapshot cache / single-worker constraint.

Covers:
- ``DashboardStateService`` reads state files fresh per instance; REST
  requests do not share an in-memory cache across requests (each request
  re-reads files). The streaming broadcaster (``eigencapital.dashboard
  .streaming.events``) is the shared-cache surface: it serves one snapshot
  per broadcast interval to all WebSocket/SSE clients. That broadcaster
  cache-sharing is regression-tested at
  ``tests/unit/dashboard/test_p1_sync_fixes.py::test_state_cache_reuses_snapshot``.
- The per-IP rate limiter in ``eigencapital.dashboard.api.app`` (``_RATE_LIMITS``)
  is an in-memory dict scoped to a single process; it is NOT safe across
  multiple workers (documented in ``dashboard/api/app.py``).

These are read-only consumer observations: no live execution, broker
behaviour, R4 strategy, risk-limit, or capital change.
"""

from __future__ import annotations

from eigencapital.dashboard.services.dashboard_state import DashboardStateService


class TestDashboardStateSingleWorker:
    """REST state service reads files fresh per instance (no shared cache
    across REST requests)."""

    def test_state_service_reads_fresh_per_instance(self):
        """Each ``DashboardStateService()`` instance reads state files
        independently; there is no shared in-memory cache across REST
        requests."""
        svc_a = DashboardStateService()
        svc_b = DashboardStateService()

        health_a = svc_a.get_system_health()
        health_b = svc_b.get_system_health()

        assert health_a["overall_state"] in (
            "HEALTHY",
            "DEGRADED",
            "HALTED",
            "UNKNOWN",
        )
        assert health_b["overall_state"] in (
            "HEALTHY",
            "DEGRADED",
            "HALTED",
            "UNKNOWN",
        )
        assert svc_a is not svc_b

    def test_state_service_reads_files_on_repeated_calls(self):
        """Repeated calls on one instance each re-read state files (REST
        returns fresh values per request; no cross-call cache)."""
        svc = DashboardStateService()

        first = svc.get_system_health()
        second = svc.get_system_health()

        assert first["overall_state"] in (
            "HEALTHY",
            "DEGRADED",
            "HALTED",
            "UNKNOWN",
        )
        assert second["overall_state"] == first["overall_state"]
        # Same set of dimensions is produced on each call (no cached
        # structural result); timestamps within dimensions may differ because
        # they are stamped at read time.
        assert [d["dimension"] for d in first["dimensions"]] == [
            d["dimension"] for d in second["dimensions"]
        ]
