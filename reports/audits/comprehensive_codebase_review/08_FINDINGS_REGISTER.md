# Findings Register

Findings are recorded against the reviewed commit `6a7e77f`. **No finding is marked closed, fixed, or accepted.** Prior-audit mappings are noted for traceability only.

Severity is defined for **capital readiness**:

- **Critical** — absence of a control required to account for capital or reconstruct execution.
- **High** — a control exists but is incorrect/unwired in a way that invalidates a safety or evidence claim.
- **Medium** — material correctness/operability defect with a bounded workaround.
- **Low** — hygiene or defence-in-depth.

## Summary table

| ID | Severity | Finding | Prior mapping | Evidence class |
|---|---|---|---|---|
| F-01 | Critical | No independent equity/capital reconciliation | P0-1 | Code-verified |
| F-02 | Critical | Capital-event ledger not wired into live path | P0-2 | Code-verified |
| F-03 | Critical | Durable decision→intent→order→fill chain absent from live path | P0-3 | Code-verified |
| F-04 | High | Stop-loss gate treats invalid SL as protected; gate optional | P0-4 | Code-verified + test |
| F-05 | High | Reconciliation compares broker state to itself | P1-5 | Code-verified |
| F-06 | High | Reconciliation result never persisted; dashboard reads a different file | P1-5 | Code-verified |
| F-07 | Medium | Advertised `max_absolute_weight_error` veto is not implemented (deliberate code choice; config still claims it) | — | Code-verified |
| F-08 | High | PBO structurally constant 1.0 | — | Runtime-verified |
| F-09 | High | Holm/BH correction invalid (Holm anti-conservative) | — | Runtime-verified |
| F-10 | High | Research provenance/artifacts not reproducible | P1-2 | Code + document |
| F-11 | High | Live signal includes the forming D1 bar | — | Code-verified |
| F-12 | Medium | Execution robustness gaps (filling, deviation, partial fills, timeouts, idempotency, chase) | — | Code-verified |
| F-13 | Medium | Execution/rebalance config fields unconsumed | — | Code-verified |
| F-14 | Medium | Dashboard state misreports account/risk/health/reconciliation | — | Code-verified |
| F-15 | Medium | Predictable default dashboard key; auth bypass env | — | Code-verified |
| F-16 | Medium | Risk-gate call semantics and daily-loss baseline fallback | — | Code-verified |
| F-17 | Medium | Audit chain unkeyed; event-ID counter race | — | Code-verified |
| F-18 | Medium | Backtest fill model unsuitable for scaling evidence | — | Code-verified |
| F-19 | Medium | CI/supply-chain hardening gaps | P1-7 (partial) | Code-verified |
| F-20 | Medium | Experiment registry mutable; no enforced promotion path | — | Code-verified |
| F-21 | Medium | Simulation executors importable in production package | — | Code-verified |
| F-22 | Medium | No schema/versioning for operational state files | — | Code-verified |
| F-23 | Low | Documentation drift; governing specs absent | — | Code-verified |
| F-24 | Low | Dashboard repeat file reads; in-memory rate limit | — | Code-verified |

---

## F-01 — No independent equity/capital reconciliation (Critical, P0-1)

**Evidence:** `scripts/r4_rebalance_loop.py` computes `equity` from `account_info()` and uses it for sizing and daily-loss checks, but never compares it to an internally maintained equity ledger. No capital-event, deposit/withdrawal, or balance-history record is consulted. `reports/r4_loop/runtime_state.json` (2026-10-29) shows `daily_start = 5107.83` and `daily_loss.baseline_equity = 18177.0` in the same record, with `peak_equity = 18176.81`; `last_equity.json` (2026-09-27) records `equity = 5117.15`. The ~3.5x equity change between those dates has no capital-event record. `reports/audits/EC_AUDIT_009_P0_1_EQUITY_RECONCILIATION.md` independently records P0-1 as `BLOCKED — BROKER STATEMENT REQUIRED; P0-1 NOT PASSED`; the reconciliation tool is diagnostic only and is not wired to the live loop.

**Impact:** no way to distinguish trading P&L from deposits, withdrawals, broker corrections, or a stale/incorrect baseline. Daily-loss protection can be evaluated against a baseline that does not correspond to the current capital base.

**Acceptance criteria:**
1. Persisted equity ledger with append-only entries `(timestamp, broker_equity, broker_balance, source, hash)`.
2. Each cycle compares broker equity to the ledger's expected equity and records the delta.
3. Daily-loss baseline is derived from the ledger and is immutable within a trading day.
4. Any unexplained delta > tolerance produces an alert and blocks new entries.

## F-02 — Capital-event ledger not wired (Critical, P0-2)

**Evidence:** `src/eigencapital/production_qual/event_ledger.py` defines `EventLedger` and typed events including credit/debit-style categories. Grep across `src/` and `scripts/` finds no construction or use outside the `production_qual` package itself.

**Impact:** the system cannot reconstruct capital movements. This is the accounting spine required for any external audit or capital scaling.

**Acceptance criteria:** ledger instantiated in the live loop; capital events written with correlation IDs; `get_trade_chain()` demonstrably returns a full chain for a live cycle.

## F-03 — Durable execution chain absent (Critical, P0-3)

**Evidence:** no import of `AuditLog` (`execution/events.py`) or `DurableAudit` (`live/durable_audit.py`) in `scripts/r4_rebalance_loop.py`; `DurableAudit` appears only in `live/campaign.py`. `execute_orders` uses `(symbol, side)` in an in-memory set, scoped per cycle.

**Impact:** no durable `decision_id → intent_id → order_id → fill_id`; ambiguous sends and restarts cannot be reconstructed or safely deduplicated.

**Acceptance criteria:** every decision, intent, submission, fill, rejection, and reconciliation result appended to one hash-chained log keyed by cycle/decision ID; a restart re-reads open intents and resolves them against the broker before submitting anything new.

## F-04 — Stop-loss validation and gate (High, P0-4)

**Evidence:** `live/risk_enforcement.py:415-430` uses `p.get("sl", 0) == 0`; `None`, negative, or non-numeric values therefore pass. `require_sl_on_positions = false` in production. `tests/unit/live/test_stop_loss_policy.py::TestInvalidDataGap` has 3 xfails documenting the gap.

**Impact:** Gate 6 cannot be relied upon as an "every position is protected" assertion. The catastrophic-SL supervisor mitigates but does not replace this check.

**Acceptance criteria:** `sl is None`, `sl <= 0`, `sl >= price` for longs (and `<= price` for shorts), and non-numeric values all count as unprotected → BLOCK. Tests un-xfailed. Gate enablement remains an explicit operator decision (not changed by this review).

## F-05 — Tautological reconciliation (High, P1-5)

**Evidence:** `scripts/r4_rebalance_loop.py:1680-1705`. `BrokerState.positions` and `InternalState.positions` are both constructed from `pos_list`.

**Impact:** position count/quantity/side/ticket mismatches can never be detected. Reconciliation status is not evidence of agreement.

**Acceptance criteria:** `InternalState` derived from persisted confirmed fills; test that a broker-only position, a missing position, and a quantity delta each yield `MISMATCH`/`HALT`.

## F-06 — Reconciliation persistence failure (High, P1-5)

**Evidence:** lines 1740-1766. `cycle_counter` is always `0`; `last_cycle` initializes to `0`; write condition `0 != 0` is false, so nothing is ever appended. Dashboard reads `reconciliation_state.json` (`dashboard_state.py:1013`); the loop targets `reconciliation_state.jsonl`.

**Impact:** no durable reconciliation history; dashboard reconciliation panel cannot show engine truth.

**Acceptance criteria:** a real monotonically increasing cycle ID; one record per cycle (or per state change); dashboard and loop agree on path and schema; test asserts a file exists after a cycle.

## F-07 — Advertised weight-error veto not implemented (Medium)

**Evidence:** `config.py:173` defines `max_absolute_weight_error = 0.05`. `configs/production/config.toml:202-204` states that a breach means "the position is SKIPPED_MIN_LOT and no order is submitted". `scripts/r4_rebalance_loop.py:801-839` records the error in `weight_error_by_symbol` and `weight_deviation.jsonl`; the code comment explicitly says weight distortion "is not an execution veto when the broker volume fits the risk envelope". `is_feasible` checks only `0 < executable_notional <= MAX_POSITION_USD`.

**Impact:** the system deliberately submits orders that the config documents as skipped. This is a config/documentation false-assurance defect, not an unknown code bug. Exposure is still bounded by the per-position notional cap. If the intended policy really is "record only", the config text must say so.

**Acceptance criteria:** either implement the veto with an auditable `SKIPPED_MIN_LOT` reason, or remove the claim from config/docs and record the risk acceptance. Do not leave both.

## F-08 — PBO invalid (High)

**Evidence:** `analytics/validation/pbo.py:88-114`. Deterministic disjoint half-split; `best_is_idx` is chosen from train and then looked for in test. Runtime: 12 candidates → `pbo=1.0 (6/6)`.

**Impact:** any reported PBO of 1.0 is an artifact. The metric carries no information in either direction.

**Acceptance criteria:** CSCV implementation; unit test with a synthetic matrix whose true PBO is known; reported research values re-derived.

## F-09 — Multiple-testing correction invalid (High)

**Evidence:** `analytics/validation/multiple_testing.py:63-129` sorts the adjusted values before mapping back. Runtime: `holm([0.001,0.04,0.03]) = [0.003,0.06,0.04]` vs correct `[0.003,0.06,0.06]`; `bh(...) = [0.003,0.045,0.04]` vs correct `[0.003,0.04,0.04]`.

**Impact:** Holm can reject a hypothesis at `α=0.05` that correct Holm would retain. Any multiplicity-controlled claim is unsupported.

**Acceptance criteria:** correct step-down/step-up algorithms; property test for monotonicity and FWER/FDR bounds; affected verdicts re-run.

## F-10 — Research provenance unverifiable (High, P1-2)

**Evidence:** EXP-000002 stored `provenance_hash` does not reproduce (`1b81…` vs recomputed `e549…`/`fbb4…`); `repository.load()` never verifies. `dataset_hash` corresponds to `data/mt5/R5_data_manifest.json` (38 instruments) while the experiment claims 42 and production allows 37. All six R1–R6 artifact directories cited by `reports/research_program/program_status.json` are absent; `git_commit fda2468` is unresolvable.

**Impact:** research conclusions cannot be reproduced or audited. Evidence referenced by reports does not exist in the repository.

**Acceptance criteria:** verification on load; dataset manifest tied to the actual experiment universe; artifacts present or claims withdrawn; commit reachable or provenance restated.

## F-11 — Live signal uses forming D1 bar (High)

**Evidence:** `scripts/r4_rebalance_loop.py:515` — `copy_rates_from_pos(sym, TIMEFRAME_D1, 0, bars)` includes index 0 (current incomplete bar). No bar-completion check.

**Impact:** hourly recomputation on a changing daily bar → signal churn, non-reproducible daily weights, avoidable turnover.

**Acceptance criteria:** either pin the signal to the last **closed** bar (drop index 0 until the daily close is final in the server timezone) or document and test the intended intraday-update semantics.

## F-12 — Execution robustness (Medium)

**Evidence:** `detect_filling_mode` always returns FOK; deviation `10` at line 995 and `20` at line 2564 (not `max_slippage`); ambiguous timeout breaks without broker resolution; partial fill treated as failed; no chase despite `max_chase_attempts`; per-cycle in-memory idempotency.

**Impact:** higher rejection/partial-fill risk, unresolved sends after crash, duplicated exposure on restart in edge cases.

**Acceptance criteria:** broker-capability-based filling mode; config-driven deviation; query-by-client-order-ID on ambiguity; partial-fill repair; durable dedup keys.

## F-13 — Unconsumed execution config (Medium)

**Evidence:** `max_chase_attempts`, `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency`, `rebalance_frequency` have no consumer in the live loop.

**Acceptance criteria:** enforce or remove; add a config-consumption test that every safety key is referenced by the live path.

## F-14 — Dashboard state defects (Medium)

**Evidence:** `mt5.shutdown()` before `positions_get()` (`dashboard_state.py:626`) → unrealized P&L always 0; `daily_loss_remaining` never decremented; `get_system_health` does not staleness-gate `alive`; `get_reconciliation_status` derives CLEAN from SL presence; `_empty_account_state` returns zeros. Concrete staleness instance: `reports/r4_loop/last_health.json` has `alive=true` dated 2026-09-27 while `runtime_state.json` is dated 2026-10-29.

**Impact:** operator may see a healthier or safer state than reality.

**Acceptance criteria:** correct call order; remaining loss derived from the same baseline as the risk engine; staleness TTL on health; reconciliation from the engine record; explicit UNKNOWN rendering for missing data.

## F-15 — Dashboard credentials (Medium)

**Evidence:** default `dev-key-change-in-production` in `dashboard/api/app.py`, `streaming/events.py`, and `scripts/start_dashboard.sh`; `DASHBOARD_DISABLE_AUTH=1` bypass; `?token=` legacy; docs endpoints open; loopback bind. The start script also exports `VITE_API_KEY`, so the key is compiled into the frontend and is available to any client that can load the UI — the key is a perimeter control, not per-user authorization.

**Acceptance criteria:** fail closed in production when key is missing/default; remove query-token acceptance; log a loud warning when auth is disabled.

## F-16 — Risk gate semantics (Medium)

**Evidence:** `check_all(target_orders=0)` before order generation (`scripts/r4_rebalance_loop.py`, gate block); `_check_daily_loss` auto-initializes baseline when audit is CLEAN (`risk_enforcement.py:353+`).

**Impact:** concurrency gate cannot see planned orders; daily-loss baseline can silently reset on restart.

**Acceptance criteria:** call with the actual planned order count; baseline must come from the persistent ledger (`RESTORED`) or refuse to trade.

## F-17 — Audit chain limitations (Medium)

**Evidence:** `durable_audit.py` uses unkeyed SHA-256 over `prev_hash|seq|payload`; `AuditLog` event counter reconstructed by replay.

**Acceptance criteria:** HMAC with external key; monotonic sequence allocated under the existing file lock; periodic head digest exported off-host.

## F-18 — Backtest realism (Medium)

**Evidence:** `backtest/engine.py` fixed tick 0.25, 1 contract, close fill, static costs, no margin/liquidation/partials; `trade_count` approximated.

**Acceptance criteria:** per-instrument contract/tick metadata; size from risk; intrabar stop/gap handling; cost model from broker specs; disclose limits in any report using it.

## F-19 — CI/supply chain (Medium)

**Evidence:** Actions by tag; no `permissions:`; unpinned deps; no dependency audit; Coverage upload non-blocking; CI max Python 3.13 while local is 3.14.

**Acceptance criteria:** SHA-pinned actions; read-only default permissions; lockfile/hashes for operational installs; `pip-audit`; decide whether 3.14 is supported and test it.

## F-20 — Experiment registry mutability and no promotion path (Medium)

**Evidence:** `ExperimentRecord` is a mutable dataclass; `repository.save()` overwrites; `delete()` exists; `_MODIFIABLE_BEFORE_FREEZE` is dead code. No code promotes research into production.

**Impact:** evidence can be altered post hoc; there is also no formal gate from research to live (production uses frozen constants directly).

**Acceptance criteria:** immutable records with content-addressed IDs; append-only supersession; explicit promotion checklist enforced in code or stated as out of scope.

## F-21 — Simulation executors latent (Medium)

**Evidence:** `SIMULATED_EVIDENCE`/hardcoded executors are importable production modules, used only by tests today.

**Acceptance criteria:** move under `tests/`, or raise at import unless a test flag is set; add a test asserting they cannot be selected in a non-test context.

## F-22 — Unversioned operational state (Medium)

**Evidence:** `reports/r4_loop/*` JSON/JSONL files have no schema version; readers use `.get()` defaults; naming inconsistent.

**Acceptance criteria:** each file has a version field; readers reject unknown versions; one owner per file documented.

## F-23 — Documentation drift / missing specs (Low)

**Evidence:** inline comments claim 1500/8 vs actual 5000/20; `SYSTEM_SPECIFICATION.md` and `domain_contracts.md` do not exist; `EC-AUDIT-009` is draft/not adopted.

**Acceptance criteria:** fix comments; mark nonexistent specs as historical references; state the adopted gate explicitly.

## F-24 — Dashboard scalability (Low)

**Evidence:** REST handlers re-read many files per request; rate limit is in-memory per process; 5 s broadcaster.

**Acceptance criteria:** snapshot cache shared with the broadcaster; document single-worker requirement.

---

## Positive observations (not findings)

- Single-instance claim + exit 75; refusal deliberately not written to the watchdog trail.
- Reconnect requires a live account read; `on_reconnect → reconciliation → resume`.
- Corrupted risk audit fails closed; reconciliation HALT stops trading.
- Catastrophic-SL supervisor on by default with an explicit flag file.
- Constant-time credential comparison; masked WebSocket stream.
- 3,644 tests; property suite stable over 3 runs; `ruff`/`mypy` clean.
- Frozen-signal fidelity guard test.
