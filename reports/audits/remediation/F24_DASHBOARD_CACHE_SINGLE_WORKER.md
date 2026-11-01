# F-24 — Dashboard Snapshot Cache / Single-Worker Constraint

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** pending
**Severity:** Low · **Phase:** P3
**Date:** 2026-11-01

---

## 1. Finding

REST handlers re-read state files on every request (each request constructs a
fresh ``DashboardStateService()`` and there is no shared cache across REST
requests); the per-IP rate limiter is an in-memory ``dict`` scoped to a single
process; the broadcaster already shares one snapshot per broadcast interval
(``eigencapital.dashboard.streaming.events.get_live_state_cached``).

Root cause: no shared snapshot cache across REST requests; multi-worker
deployments would not share rate-limit state.

## 2. Correction

Read-only consumer documentation (no live execution, broker behaviour, R4
strategy, risk-limit, or capital change):

**`src/eigencapital/dashboard/services/dashboard_state.py`** — module docstring
documents the single-worker constraint:
- every ``DashboardStateService()`` instance reads state files fresh on each
  call; no shared in-memory cache across REST requests (REST returns exact,
  unmasked values);
- the broadcaster surface shares one masked snapshot per broadcast interval;
- the per-IP rate limiter in ``dashboard/api/app.py`` (``_RATE_LIMITS``) is an
  in-memory dict scoped to a single process — not safe across multiple workers;
  run the dashboard as a single worker or use an external rate limiter for
  multi-worker deployments.

**`src/eigencapital/dashboard/api/app.py`** — comment beside ``_RATE_LIMITS``
documents that the rate limiter is per-process and single-worker only.

## 3. Files changed

- `src/eigencapital/dashboard/services/dashboard_state.py` (docstring)
- `src/eigencapital/dashboard/api/app.py` (comment)
- `tests/unit/dashboard/test_f24_dashboard_single_worker.py` (new)

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/dashboard/test_f24_dashboard_single_worker.py -q` | **2 passed** |
| `pytest tests/unit/dashboard -q` | **168 passed** |

The broadcaster snapshot-cache sharing is regression-tested at
``tests/unit/dashboard/test_p1_sync_fixes.py::test_state_cache_reuses_snapshot``
(shared snapshot within the TTL interval) and is not duplicated here.

## 5. Limitations (noted, not hidden)

- The REST path intentionally re-reads files per request to return exact,
  unmasked values (consistent with F-13/F-15 masking boundaries); the shared
  snapshot cache applies to the streaming/broadcast surface only.
- No external rate limiter was introduced; the single-worker constraint is
  documented. A multi-worker deployment would still need an external limiter.
- No live execution, broker behaviour, R4 strategy, risk-limit, or capital
  change.

## 6. What this does not establish

- Independent review has not occurred.
- No multi-worker deployment was tested.
- Capital-readiness decision unchanged.

## 7. Closure decision

`VERIFIED WITH LIMITATIONS`. Not `CLOSED`. Remaining: independent review.
