# F-14 — Dashboard Truth (account/risk/health/reconciliation)

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION` (reconciliation-record portion blocked pending F-06)
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `dfb99ea`
**Severity:** Medium · **Phase:** P1
**Date:** 2026-11-01

---

## 1. Finding

`src/eigencapital/dashboard/services/dashboard_state.py` misreported dashboard state:

- `get_account_state` called `mt5.shutdown()` (line 626) before `positions_get()` (line 687), so `unrealized_pnl` was always 0.
- `daily_loss_remaining` was set to `max_daily_loss` and never decremented (line 650).
- `get_system_health` trusted the `alive` flag from `loop_health.json`/`last_health.json` with no staleness TTL; a stale `last_health.json` (`alive=true`, dated 2026-09-27) was reported as live.
- `get_reconciliation_status` derived `CLEAN` from SL presence when no engine reconciliation record existed (line 1023), conflating stop-loss protection with reconciliation.

## 2. Correction

`get_account_state`:
- Moved `mt5.shutdown()` to after `positions_get()`, so `unrealized_pnl` sums real per-position profit before the session closes.
- `daily_loss_remaining` now uses `_compute_daily_loss_remaining(daily_pnl, max_daily_loss)` = `max(0, max_daily_loss - abs(daily_pnl))`, derived from the same baseline as the risk engine. It never resets to the full limit.

`get_system_health`:
- Added `HEALTH_STALENESS_TTL_SECONDS = 300`. Health data older than the TTL is treated as stale: `alive` is forced False, the supervisor dimension reports `HALTED`, and `details.health_stale` is set. A leftover `alive=true` file is no longer trusted.

`get_reconciliation_status`:
- When no engine `reconciliation_state.json` exists, returns `overall_status: "UNKNOWN"`, `engine_record: false`, `freshness: UNKNOWN` instead of deriving `CLEAN`/`WARNING` from SL presence. The reconciliation-record portion (reading the engine's own record) remains blocked pending F-06.

## 3. Files changed

- `src/eigencapital/dashboard/services/dashboard_state.py`
- `tests/unit/dashboard/test_f14_dashboard_truth.py` (new)
- `tests/unit/dashboard/test_p1_sync_fixes.py` (updated reconciliation assertion)

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/dashboard/test_f14_dashboard_truth.py -q` | **11 passed** |
| `pytest tests/unit/dashboard tests/unit/live tests/unit/analytics -q` | **763 passed** |

New coverage: daily-loss remaining decrements/cannot be negative/zero baseline; health staleness TTL (stale alive → HALTED, fresh → HEALTHY, missing file → HALTED, within-TTL → fresh); reconciliation missing engine record → UNKNOWN; MT5 unavailable → empty UNKNOWN state; positions fetched before shutdown with correct `unrealized_pnl` and call ordering.

## 5. What this does not establish

- The dashboard still does NOT read the engine's reconciliation record; that depends on F-06 (loop writes `reconciliation_state.json`). Until F-06, missing record → UNKNOWN (honest, not fabricated CLEAN).
- `daily_loss_remaining` is derived from `daily_baseline.json` persisted by the loop; the baseline itself comes from F-01/F-02 ledger work, which is blocked.
- Independent review has not occurred.
- Capital-readiness decision unchanged.

## 6. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`. Remaining: independent review, and the reconciliation-record portion is blocked pending F-06.
