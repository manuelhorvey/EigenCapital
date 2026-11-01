# F-15 — Predictable Default Dashboard Key and Auth Bypass

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `e0fec4c`
**Severity:** Medium · **Phase:** P1
**Date:** 2026-11-01

---

## 1. Finding

The dashboard shipped a predictable default key (`dev-key-change-in-production`),
accepted auth bypass via `DASHBOARD_DISABLE_AUTH=1` without warning, accepted the
legacy `?token=` query parameter (key in the URL, H-11), and embedded the key in
the frontend bundle via `VITE_API_KEY`.

## 2. Correction

`src/eigencapital/dashboard/api/app.py`:

- `_api_key()` now resolves per request: a missing or default key returns `None`
  and the `/api/v1` middleware returns `503` (fail closed) unless
  `DASHBOARD_ALLOW_INSECURE_DEV=1` is set, which permits the default key for
  local development only (warned once).
- Added a startup event that logs a loud warning when `DASHBOARD_DISABLE_AUTH=1`.

`src/eigencapital/dashboard/streaming/events.py`:

- Removed the `?token=` query-parameter candidate entirely (credentials never
  travel in the URL; H-11). Only `api-key.<key>` subprotocol and
  `Authorization: Bearer` remain.
- Missing/default key fails closed (no credentials accepted).

`scripts/start_dashboard.sh`:

- When the default key is used, sets `DASHBOARD_ALLOW_INSECURE_DEV=1` and
  prints a loud warning; dev mode keeps working, production requires a real key.

`tests/unit/dashboard/test_dashboard_contracts.py`,
`tests/unit/dashboard/test_p1_sync_fixes.py`:

- Auth tests now use a real (non-default) key.
- Added fail-closed (503 when unconfigured) and dev-opt-in tests.
- `?token=` acceptance test replaced with a rejection test.

## 3. Files changed

- `src/eigencapital/dashboard/api/app.py`
- `src/eigencapital/dashboard/streaming/events.py`
- `scripts/start_dashboard.sh`
- `tests/unit/dashboard/test_dashboard_contracts.py`
- `tests/unit/dashboard/test_p1_sync_fixes.py`

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/dashboard -q` | **157 passed** |

## 5. Residual (noted, not fixed here)

- `VITE_API_KEY` still embeds the dashboard key in the frontend bundle. The
  frontend needs it to call the authenticated backend; removing it is a
  separate frontend architecture decision. It is scoped to local-dev default
  key unless overridden.
- `start_dashboard.sh` binds loopback (already the case) — no change.

## 6. What this does not establish

- Independent review has not occurred.
- No production deployment was performed.
- Capital-readiness decision unchanged.

## 7. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
