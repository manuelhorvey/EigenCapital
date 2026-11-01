# Execution and Operational Safety

Primary evidence: `scripts/r4_rebalance_loop.py` (3,329 lines), `src/eigencapital/live/*`, `src/eigencapital/reconciliation/engine.py`, `src/eigencapital/dashboard/*`, `reports/r4_loop/*`.

## Live cycle order of operations (as implemented)

1. Connection/session validation and reconnect handling.
2. Position attribution (foreign-position quarantine; R4 overflow detection).
3. **Reconciliation** (before any order work).
4. Risk gates (`RiskEnforcer.check_all`, with `target_orders=0`).
5. Target generation (R4 signal) and order generation.
6. Rebalance-policy decision (CANONICAL by default).
7. Order envelope / feasibility checks.
8. Execution (`execute_orders`).
9. State persistence (`runtime_state.json`, `decisions.jsonl`, weight-deviation evidence).

This ordering is defensible: risk gates run before execution and a HALT reconciliation returns early. The problem is that step 3 cannot detect what it exists to detect, and steps 9 persist an incomplete record.

## 1. Reconciliation is tautological (High)

`scripts/r4_rebalance_loop.py:1680-1705` builds `InternalState.positions` from **the same `pos_list`** used to build `BrokerState.positions`:

```python
broker_state = BrokerState(positions=[... for p in pos_list], ...)
internal_state = InternalState(positions={p.ticket: {...} for p in pos_list}, ...)
recon_result = _reconciliation_engine.reconcile(broker_state, internal_state)
```

Every position-level comparison (count, quantity, side, tickets) is therefore guaranteed to pass. Only checks that are broker-only (foreign magic, stale) can fire. `InternalState.target_weights` is populated but no engine check consumes it to detect divergence.

**Impact:** P0-1/P1-5 remain open. Manual broker intervention, missed fills, and partial fills cannot be detected at the position level. Equity is never compared to an internal ledger at all.

**Required shape:** internal positions must be derived from *confirmed fills* persisted independently (intents + fills), not from the broker query; reconciliation then compares that ledger to the broker and persists the result.

## 2. Reconciliation result is never persisted (High)

Lines 1740-1766:

- `recon_record.cycle_counter = diag.get("cycle_counter", 0)` — `diag` never receives a `cycle_counter`, so this is always `0`.
- `last_cycle` initializes to `0`; if the file is absent, `0 != 0` is false → **no write ever happens** on the first cycle.
- On subsequent runs the last record (if any existed) also has `0`, so writes remain skipped.
- The comment claims crash-safe idempotent persistence; the observed behavior is "never persist".

Additionally, the dashboard reads a **different filename**: `reconciliation_state.json` (`dashboard/services/dashboard_state.py:1013`) while the loop targets `reconciliation_state.jsonl`. Even after fixing the counter, the dashboard would still not see it.

**Impact:** the dashboard's reconciliation panel is fed by fallback heuristics, not by the engine's actual result.

## 3. Durable execution audit chain absent (High)

- `src/eigencapital/live/durable_audit.py` provides a hash-chained, mirrored, fsync'd, `fcntl`-locked log.
- `src/eigencapital/execution/events.py` provides `AuditLog` JSONL events.
- `src/eigencapital/production_qual/event_ledger.py` provides typed events with `correlation_id` and `get_trade_chain()`.

None is imported by `scripts/r4_rebalance_loop.py`. Grep shows `EventLedger` has **zero** callers outside `production_qual/__init__.py` and its own module. `DurableAudit` is used only by `live/campaign.py`.

Consequently there is no durable `decision_id → intent_id → order_id → fill_id` chain. `execute_orders` uses an in-memory `(symbol, side)` dedup set scoped to one cycle, so:
- a crash after submission but before recording can resubmit on restart;
- an operator cannot reconstruct why an order exists from durable evidence.

## 4. Execution robustness (High–Medium)

Observed in `execute_orders` / `_build_mt5_order_request`:

| Issue | Detail |
|---|---|
| Filling mode hard-coded | `detect_filling_mode()` always returns `ORDER_FILLING_FOK` regardless of symbol/broker capability. |
| Deviation hard-coded, inconsistent | `10` at line 995 (normal path), `20` at line 2564 (flatten path). Config `max_slippage` is not used. |
| Ambiguous timeout | On an ambiguous send result, the loop marks remaining orders and breaks; it does **not** query the broker to resolve whether the order filled. |
| Partial fills | Treated as failure, with no follow-up/repair; a partial position can survive unreconciled. |
| No chase | `max_chase_attempts` exists in config but is never consumed. |
| Age/slippage/frequency guards | `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency` exist in config but are never consumed. |
| Idempotency | Per-cycle, in-memory only; no durable client order ID. |

## 5. Risk gates (Medium)

- `RiskEnforcer.check_all(...)` is called with `target_orders=0` **before** orders are generated. The per-order/concurrency gate therefore runs against zero, and order envelopes are enforced separately. This is not necessarily unsafe, but the "target_orders" parameter is misleading and the concurrency check at this point cannot see the planned additions.
- `_check_daily_loss` auto-initializes the baseline to current equity when the persisted audit is CLEAN. This interacts with `DailyLossTracker` and means a restart at a loss restarts the daily-loss clock from the lower equity — a silent limit reset unless the persisted audit restores the correct baseline. The intended path is replay-based restoration (`RESTORED`), but the fallback is permissive.
- `require_sl_on_positions=false` in production config. `_check_position_protection` uses `p.get("sl", 0) == 0`; therefore `None`, negative, and non-numeric SL values are treated as **protected**. Three xfailed tests document this (`tests/unit/live/test_stop_loss_policy.py::TestInvalidDataGap`). No production order is currently submitted with an invalid SL by the normal path, but the gate is unable to catch one.
- `_check_daily_loss` and protection gate results are CRITICAL and `has_critical → BLOCKED` (verified in enforcement).

## 6. Containment layer (strength, with a caveat)

- `scripts/start_trading.sh` starts the safety supervisor **on by default** with `--live`, and `configs/r4_safety.enabled` exists → `live_actions_enabled()` returns true.
- Supervisor sets/repairs catastrophic stops and can close tickets; ATR is computed from local `data/mt5/{sym}m_D1.csv` (files exist for the production symbols checked: AUDUSD, XAUUSD, US30), with a 1% floor when ATR is unavailable.
- Single-instance `ProcessSupervisor` for the loop; separate PID/health for the supervisor.
- Reconciliation HALT stops trading; corrupted risk audit fails closed.

Caveats:

- the supervisor is an **additional** layer; it does not make the Gate-6 SL semantics correct;
- it relies on local CSV history that may be stale;
- `--no-safety` and `--dry-run` paths change the guarantee, and nothing in the dashboard flags "safety supervisor disabled".

## 7. Dashboard truth defects (Medium)

| Function | Defect |
|---|---|
| `get_account_state` | Calls `mt5.shutdown()` **before** `mt5.positions_get()` (line 626) → `unrealized_pnl` is always 0. |
| `get_account_state` | `daily_loss_remaining` is set to `max_daily_loss` and never reduced by `daily_pnl`. |
| `get_system_health` | Does not staleness-gate the `alive` flag; a stale `loop_health.json` with `alive=true` can read as healthy. |
| `get_reconciliation_status` | Derives "CLEAN" from SL-protection presence; never reads the intent ledger; wrong filename (see §2). |
| `_empty_account_state` | Returns `equity=0`, `balance=0` with `freshness=UNKNOWN`; acceptable if the UI renders "unknown", dangerous if it renders "$0". |

Operational-state evidence of the underlying accounting gap: `reports/r4_loop/runtime_state.json` (2026-10-29) contains `daily_start = 5107.83` **and** `daily_loss.baseline_equity = 18177.0` in the same record, with `peak_equity = 18176.81`; `last_equity.json` (2026-09-27) records `equity = 5117.15`. Two notions of starting equity coexist, and the ~3.5x equity change has no capital-event record. Separately, `last_health.json` reports `alive=true` dated 2026-09-27 — a direct instance of the staleness defect below.

## 8. Config enforcement gaps (Medium)

Documented in config, not consumed by the live loop:

- `execution.max_absolute_weight_error` — documented as an execution veto in `configs/production/config.toml` ("SKIPPED_MIN_LOT and no order is submitted"), but the code records it and states in a comment that weight distortion is **not** an execution veto (`scripts/r4_rebalance_loop.py:801-839`). The delivered behaviour is intentional; the config claim is false.
- `execution.max_chase_attempts`, `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency`.
- `rebalance_frequency` (documented intent; CANONICAL policy trades whenever the plan is non-empty).

Config loading also silently ignores unknown keys (each section uses `from_dict` with `.get()`); a typo in a safety key is not fatal.

## 9. Failure and recovery behavior

Positive:

- reconnect requires a live `account_info()` read, not just a successful initialize;
- after reconnect, `on_reconnect → submit_reconciliation → request_resume` sequence is enforced;
- `HALTED` recovery state prevents trading;
- risk audit replay restores peak equity and daily-loss baseline, and `CORRUPTED` fails closed;
- refusal to start is printed to stdout and deliberately not written to `decisions.jsonl` (prevents masking a dead loop).

Negative:

- no durable post-trade reconciliation, so an ambiguous send is unresolved until the next cycle;
- no alerting on "safety supervisor disabled" or "reconciliation never persisted";
- state files lack schema versions; a format change silently becomes a parse failure (caught inconsistently).

## 10. Operational safety rating

| Area | Rating |
|---|---|
| Pre-trade risk gates | Good, with SL-validation gap |
| Execution robustness | Weak–Medium |
| Reconciliation | **Unsound** (tautological, not persisted) |
| Durable audit | **Absent from live path** |
| Containment/backstop | Good |
| Observability truth | Weak |

**No evidence was found that the system is currently trading unsafely at its present size.** The gap is evidentiary and accounting: it cannot prove what it did or that broker and internal state agree.
