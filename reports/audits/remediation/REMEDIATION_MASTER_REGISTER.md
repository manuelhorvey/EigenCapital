# Remediation Master Register

**Programme:** Comprehensive Codebase Review remediation
**Source of truth:** `reports/audits/comprehensive_codebase_review/findings_register.json` (24 findings: 3 Critical, 7 High, 12 Medium, 2 Low)
**Baseline commit:** `250f3cb` (merge of PR #1) — branch `audit/p0-remediation-001`
**Baseline state:** `9b5c635` (F-01/F-02 investigation + proposed criteria)
**Capital-readiness decision:** **NOT AUTHORIZED — unchanged**
**Register updated:** 2026-11-01

Status legend: `OPEN`, `INVESTIGATING`, `BLOCKED`, `READY FOR IMPLEMENTATION`, `IN PROGRESS`, `IMPLEMENTED`, `AWAITING VERIFICATION`, `VERIFIED`, `CLOSED`, `REOPENED`, `DEFERRED — FORMAL APPROVAL REQUIRED`.

Severity and finding identifiers are copied unchanged from the audit register. No finding is marked `CLOSED` without acceptance evidence.

---

## Baseline verification (Phase 0)

| Check | Result |
|---|---|
| Branch / HEAD | `audit/p0-remediation-001` / `9b5c635` |
| `origin/main` | `250f3cb`; parents `9efb1c9` + `b8ef53c` |
| Intended commits reachable from `main` | `6a7e77f`, `bed32f1`, `2f7d73e`, `b8ef53c` — all yes |
| Working tree | clean at start of Phase 0 |
| Stashes | `stash@{0}` (WIP on `fix/findings-resolution`) preserved, untouched |
| PR #1 CI | merged while `test (3.11/3.12/3.13)` were `in_progress`; `frontend` passed |
| Post-merge CI on `main` | run `41277592309` on `250f3cb` — `in_progress` at baseline |
| Existing remediation | F-01/F-02 investigation only (`9b5c635`); no code remediation |

**Sequencing note.** The roadmap orders P0 items 1–7 first. F-01 remains externally blocked (broker statement); F-02 live wiring is explicitly not authorised in this phase; F-03/F-05/F-06 depend on F-02 and live-path approval. The next dependency-ready, risk-isolated unit is therefore **F-09** (pure statistical function, no live path). This is a justified deviation from numerical order, recorded here.

---

## F-01 — No independent equity/capital reconciliation
- **Severity:** Critical · **Phase:** P0
- **Evidence:** `scripts/r4_rebalance_loop.py` uses `account_info().equity` directly; no internal equity ledger; `runtime_state.json` has `daily_start=5107.83` and `daily_loss.baseline_equity=18177.0`; `last_equity.json=5117.15`; `EC_AUDIT_009_P0_1_EQUITY_RECONCILIATION.md` is `BLOCKED — BROKER STATEMENT REQUIRED`.
- **Root cause:** Broker equity is treated as both measurement and control base; no cash-flow classification.
- **Affected:** `scripts/r4_rebalance_loop.py`, `src/eigencapital/live/risk_enforcement.py`, `reports/r4_loop/*`.
- **Remediation:** Append-only equity/capital ledger; per-cycle broker-vs-ledger delta; baseline derived from ledger; unexplained-delta block.
- **Dependencies:** Broker statement (2026-09-26 → 2026-10-29, USD) is a hard blocker for historical acceptance. F-02 ledger plumbing.
- **Acceptance:** As §5 of `P0_F01_F02_INVESTIGATION_AND_ACCEPTANCE.md`; `unexplained_steps == 0`, `unexplained_jumps == 0`, closing delta < $0.01.
- **Tests:** Ledger replay, delta-block, restart baseline, backfill idempotency; historical acceptance requires the statement.
- **Status:** `BLOCKED` — external broker statement required.
- **Commit / evidence:** `9b5c635` (investigation only). P0-1 not passed.
- **Closure:** Pending.

## F-02 — Capital-event ledger not wired into live path
- **Severity:** Critical · **Phase:** P0
- **Evidence:** `production_qual/event_ledger.py` defines `EventLedger`; no construction in `src/` or `scripts/` outside `production_qual`.
- **Root cause:** Ledger implemented as a research primitive but never integrated.
- **Affected:** `src/eigencapital/production_qual/event_ledger.py`, live loop.
- **Remediation:** Typed, append-only, hash-chained ledger with broker refs, correlation IDs, replay, fail-closed handling; fixture implementation first.
- **Dependencies:** F-01 for capital-event semantics; **separate approval for live-path wiring**.
- **Acceptance:** §6 of `P0_F01_F02_INVESTIGATION_AND_ACCEPTANCE.md`.
- **Tests:** Append/replay determinism, tamper detection, duplicate/restart idempotency, unknown-type rejection, currency mismatch, corrupted-ledger fail-closed, wiring regression.
- **Status:** `BLOCKED` — live wiring requires approval; fixture work `READY FOR IMPLEMENTATION`.
- **Commit / evidence:** `9b5c635` (criteria only).
- **Closure:** Pending.

## F-03 — Durable decision-intent-order-fill chain absent
- **Severity:** Critical · **Phase:** P0
- **Evidence:** No `AuditLog`/`DurableAudit` import in the live loop; `DurableAudit` only in `live/campaign.py`; in-memory `(symbol, side)` dedup.
- **Root cause:** Execution provenance is process-local; restart loses intent state.
- **Affected:** `scripts/r4_rebalance_loop.py`, `live/durable_audit.py`, `execution/events.py`.
- **Remediation:** Cycle/decision IDs; durable intent-before-send; resolve open intents on restart; one hash-chained log.
- **Dependencies:** F-02, F-17; live-path approval.
- **Acceptance:** Every decision/intent/submit/fill/reject/reconcile chained by cycle and decision ID; restart resolves open intents before new orders.
- **Tests:** Restart-during-ambiguous-send, duplicate suppression, chain completeness.
- **Status:** `BLOCKED` — depends on F-02 and live-path approval.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-04 — Stop-loss gate treats invalid SL as protected and is optional
- **Severity:** High · **Phase:** P0
- **Evidence:** `live/risk_enforcement.py:415-430` uses `p.get('sl', 0) == 0`; `require_sl_on_positions=false`; 3 xfails in `test_stop_loss_policy.py`.
- **Root cause:** Falsy/absent SL and non-numeric values collapse to "valid"; gate is optional.
- **Affected:** `live/risk_enforcement.py`, `tests/unit/live/test_stop_loss_policy.py`.
- **Remediation:** Treat `None`, `<=0`, wrong-side, non-numeric as unprotected → BLOCK; un-xfail tests. **Do not enable the gate**; enablement stays an operator decision.
- **Dependencies:** none for validation semantics.
- **Acceptance:** Four invalid classes BLOCK; xfails removed; gate enablement unchanged.
- **Tests:** Parametrised invalid SL classes; valid long/short SL passes; gate-disabled path unchanged.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `18e254b`; `reports/audits/remediation/F04_STOP_LOSS_VALIDATION.md`. 27 targeted, 480 live/edge tests passed; three strict xfails removed.
- **Closure:** Pending independent review. Gate remains disabled.

## F-05 — Reconciliation compares broker state to itself
- **Severity:** High · **Phase:** P0
- **Evidence:** `r4_rebalance_loop.py:1680-1705` builds `BrokerState` and `InternalState` from the same `pos_list`.
- **Root cause:** No independent internal position truth.
- **Affected:** live loop, `reconciliation/engine.py`.
- **Remediation:** Build `InternalState` from persisted confirmed fills.
- **Dependencies:** F-03 (durable fills), F-02.
- **Acceptance:** Broker-only, missing, quantity-delta cases produce MISMATCH/HALT.
- **Tests:** Three mismatch cases plus matched case.
- **Status:** `BLOCKED` — depends on F-03/F-02.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-06 — Reconciliation result never persisted; dashboard reads different file
- **Severity:** High · **Phase:** P0
- **Evidence:** `r4_rebalance_loop.py:1740-1766` `cycle_counter` always 0, append skipped; dashboard reads `reconciliation_state.json`, loop writes `.jsonl`.
- **Root cause:** Cycle identity absent; producer/consumer path drift.
- **Affected:** live loop, `dashboard/services/dashboard_state.py`.
- **Remediation:** Monotonic cycle ID; one record per cycle/change; unify path/schema.
- **Dependencies:** F-03 cycle ID, F-22.
- **Acceptance:** File exists after a cycle; dashboard reads the same record.
- **Tests:** Cycle-write assertion; path/schema contract test.
- **Status:** `BLOCKED` — depends on F-03/F-22.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-07 — Advertised `max_absolute_weight_error` veto not implemented
- **Severity:** Medium · **Phase:** P1
- **Evidence:** `config.py:173`; `configs/production/config.toml:202-204`; loop records error but comment says not an execution veto.
- **Root cause:** Documentation/config claim outlives implementation.
- **Affected:** config, `scripts/r4_rebalance_loop.py`.
- **Remediation:** Enforce as veto with audited reason **or** remove claim with written risk acceptance — requires decision.
- **Dependencies:** Technical decision record (changes order submission behaviour or documentation contract).
- **Acceptance:** Claim matches behaviour; test proves chosen option.
- **Tests:** Breach blocks with reason (option A) or config/doc assertion (option B).
- **Status:** `DEFERRED — FORMAL APPROVAL REQUIRED`.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-08 — PBO structurally constant 1.0
- **Severity:** High · **Phase:** P1
- **Evidence:** `pbo.py:88-114` single disjoint split; best IS chosen from train and cannot appear in test; runtime 12 candidates → `pbo=1.0`, `6/6`.
- **Root cause:** Not CSCV; train/test membership is fixed and disjoint.
- **Affected:** `analytics/validation/pbo.py`, research verdicts citing PBO.
- **Remediation:** Implement CSCV over all balanced splits; rank-based logit; known-answer test; re-derive affected values.
- **Dependencies:** none for implementation; research re-run depends on F-09 and F-10.
- **Acceptance:** Known-PBO synthetic matrix reproduces expected value; partitions balanced; no candidate leaks across sides.
- **Tests:** Known matrix, symmetric matrix, deterministic seeds, invalid input, insufficient experiments.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`; research re-derivation `BLOCKED` on raw return matrices.
- **Commit / evidence:** `6e707ca`; `reports/audits/remediation/F08_PBO_CSCV_CORRECTION.md`. 18 targeted, 191 analytics, 974 analytics+research tests passed. Full CI-equivalent run on the post-F-08 tree pending.
- **Closure:** Pending independent review, full-suite confirmation, and restatement/withdrawal of the R3 PBO claim.

## F-09 — Holm/BH multiple-testing correction invalid
- **Severity:** High · **Phase:** P1
- **Evidence:** `multiple_testing.py:63-129` sorts adjusted values before mapping back; runtime `holm([0.001,0.04,0.03])=[0.003,0.06,0.04]` (correct `[0.003,0.06,0.06]`); `benjamini_hochberg(...)=[0.003,0.045,0.04]` (correct `[0.003,0.04,0.04]`).
- **Root cause:** Monotonicity enforced on the multiset of adjusted values, then mapped by rank, breaking rank↔index correspondence.
- **Affected:** `analytics/validation/multiple_testing.py`; callers in `research/factor_lab`, `research/parameter_stability`, `scripts/run_r4_b2_pairs.py`.
- **Remediation:** Holm forward cumulative max over rank; BH backward cumulative min over rank; input validation; hand-calculated and property tests.
- **Dependencies:** none.
- **Acceptance:** Hand-calculated values match; monotonicity/bounds hold; invalid inputs fail closed; affected verdicts re-run.
- **Tests:** Hand calc, order preservation, monotonicity, FWER/FDR bound properties, invalid p-values, non-mutation.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `174b5a1`; `reports/audits/remediation/F09_MULTIPLE_TESTING_CORRECTION.md`. 32 targeted, 176 analytics, 88 caller, 3662 full-suite tests passed.
- **Closure:** Pending independent review and re-run of affected research verdicts.

## F-10 — Research provenance not reproducible
- **Severity:** High · **Phase:** P1
- **Evidence:** `EXP-000002` provenance hash mismatch; `repository.load()` never verifies; dataset manifest 38 vs claim 42 vs production 37; six R1–R6 artifact directories absent; `git_commit fda2468` unresolvable.
- **Root cause:** Provenance fields are written but not enforced; artifacts not retained.
- **Affected:** `research/experiment_repository.py` (load path), manifests, reports.
- **Remediation:** Verify hash on load; align universe manifest; restore artifacts or withdraw claims; resolve/restate commit.
- **Dependencies:** External artifacts (may be unrecoverable) → partial.
- **Acceptance:** Load rejects tampered hash; manifest matches experiment universe; every cited artifact present or claim withdrawn.
- **Tests:** Tampered-hash rejection; manifest/universe consistency.
- **Status:** `READY FOR IMPLEMENTATION` (verification); artifact restoration `BLOCKED`.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-11 — Live signal includes the forming D1 bar
- **Severity:** High · **Phase:** P1
- **Evidence:** `r4_rebalance_loop.py:515` `copy_rates_from_pos(sym, TIMEFRAME_D1, 0, bars)` includes index 0; no completion filter.
- **Root cause:** Positional lookback treats the current, incomplete daily bar as closed.
- **Affected:** live signal input.
- **Remediation:** Pin to last closed bar (or document/test intraday semantics); no R4 maths change.
- **Dependencies:** none; behaviour-affecting but explicitly authorised by the audit.
- **Acceptance:** Deterministic test proves a forming bar cannot enter the signal; completed-bar output unchanged for a closed-bar fixture.
- **Tests:** Injected forming bar; closed-bar fixture; restart/dedup.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `c91a8d9`; `reports/audits/remediation/F11_FORMING_BAR.md`. 3 forming-bar tests + 35 loop/t0 + 69 signal/reconnect tests passed.
- **Closure:** Pending independent review and production re-check of the staleness nuance.

## F-12 — Execution robustness gaps
- **Severity:** Medium · **Phase:** P1
- **Evidence:** FOK always; deviations 10/20 hard-coded; ambiguous timeout breaks; partial fill = failure; no chase; in-memory idempotency.
- **Root cause:** Execution path lacks broker-capability negotiation and durable intent state.
- **Affected:** `scripts/r4_rebalance_loop.py`, order submission.
- **Remediation:** Capability-based filling, config deviation, resolve ambiguous sends by client ID, partial-fill repair, durable dedup.
- **Dependencies:** F-03; **approval required** for broker-behaviour changes (filling mode/deviation).
- **Acceptance:** Each gap has a test; no duplicate exposure after simulated restart.
- **Tests:** Partial fill, ambiguous timeout, capability matrix, dedup replay.
- **Status:** `DEFERRED — FORMAL APPROVAL REQUIRED` for behaviour-changing parts; durable dedup `READY` after F-03.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-13 — Execution/rebalance config fields unconsumed
- **Severity:** Medium · **Phase:** P1
- **Evidence:** no consumers for `max_chase_attempts`, `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency`, `rebalance_frequency`.
- **Root cause:** Config evolved ahead of implementation.
- **Affected:** config, live loop.
- **Remediation:** Enforce or remove each field; config-consumption test for every safety key. Decision required per field.
- **Dependencies:** F-07 decision; technical decision record for removed/enforced limits.
- **Acceptance:** Every safety key has a consumer test or is removed with acceptance.
- **Tests:** Config-consumption contract test.
- **Status:** `DEFERRED — FORMAL APPROVAL REQUIRED`.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-14 — Dashboard misreports account/risk/health/reconciliation
- **Severity:** Medium · **Phase:** P1
- **Evidence:** `dashboard_state.py:626` calls `mt5.shutdown()` before `positions_get()`; daily-loss remaining never decremented; no health staleness; reconciliation derived from SL presence; stale `last_health.json` `alive=true`.
- **Root cause:** Dashboard reconstructs state instead of reading engine truth.
- **Affected:** `dashboard/services/dashboard_state.py`.
- **Remediation:** Correct MT5 call order; derive remaining loss from engine baseline; staleness TTL; read engine reconciliation record; explicit UNKNOWN.
- **Dependencies:** F-06 for reconciliation record; F-01 for baseline.
- **Acceptance:** Dashboard values match engine artefacts; stale data renders UNKNOWN.
- **Tests:** Fake MT5 order-of-calls; staleness; reconciliation source; remaining-loss arithmetic.
- **Status:** `READY FOR IMPLEMENTATION` (read-only dashboard).
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-15 — Predictable default dashboard key and auth bypass
- **Severity:** Medium · **Phase:** P1
- **Evidence:** default `dev-key-change-in-production`; `DASHBOARD_DISABLE_AUTH=1`; `?token=` WebSocket acceptance; `VITE_API_KEY` embedded in frontend.
- **Root cause:** Development defaults usable in production; key material shipped to browser.
- **Affected:** `dashboard/api/app.py`, `dashboard/streaming/events.py`, `scripts/start_dashboard.sh`.
- **Remediation:** Fail closed in production on missing/default key; remove query-token; loud warning when auth disabled.
- **Dependencies:** none.
- **Acceptance:** Production startup refuses default/missing key; query token rejected; warning emitted.
- **Tests:** Startup guard, token transport, auth-disabled warning.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `e0fec4c`; `reports/audits/remediation/F15_DASHBOARD_AUTH.md`. Fail-closed (503) when unconfigured; query token removed; dev requires explicit opt-in. 157 dashboard tests pass.
- **Closure:** Pending independent review.

## F-16 — Risk-gate call semantics / daily-loss baseline fallback
- **Severity:** Medium · **Phase:** P1
- **Evidence:** `check_all(target_orders=0)` before order generation; `_check_daily_loss` auto-initialises baseline when audit is CLEAN.
- **Root cause:** Gate sees no orders; baseline can silently reset.
- **Affected:** live loop, `live/risk_enforcement.py`.
- **Remediation:** Pass actual planned count; require `RESTORED` baseline or refuse trading.
- **Dependencies:** F-02 ledger.
- **Acceptance:** Gate receives actual count; missing baseline refuses trading.
- **Tests:** Call-count assertion; baseline-state matrix.
- **Status:** `BLOCKED` — depends on F-02 ledger.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-17 — Audit chain unkeyed; event IDs can race
- **Severity:** Medium · **Phase:** P2
- **Evidence:** `durable_audit.py` plain SHA-256, no key; `AuditLog` counter rebuilt by replay.
- **Root cause:** Tamper-evidence without a secret is only integrity-against-accident.
- **Affected:** `live/durable_audit.py`, `execution/events.py`.
- **Remediation:** HMAC with off-repo key; allocate sequence under file lock; export head digest off-host.
- **Dependencies:** F-03; key-management decision.
- **Acceptance:** Tamper without key detected; concurrent appends produce unique contiguous sequence.
- **Tests:** HMAC verification, concurrent append, head export.
- **Status:** `DEFERRED — FORMAL APPROVAL REQUIRED` (key management).
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-18 — Backtest fill model unsuitable for scaling evidence
- **Severity:** Medium · **Phase:** P2
- **Evidence:** fixed `tick_size=0.25`, `quantity=1.0`; close fills; static spread/slippage; no margin/financing/liquidation/partial fills; `trade_count = fill_events // 2`.
- **Root cause:** Simplified research model lacks instrument metadata and broker costs.
- **Affected:** `backtest/engine.py`, research reports.
- **Remediation:** Instrument metadata, risk sizing, intrabar stops/gaps, broker cost model, disclosed limitations.
- **Dependencies:** Decision on research scope; changes research output.
- **Acceptance:** Metadata-driven tick/contract; sizing by risk; limitations disclosed.
- **Tests:** Metadata fixtures, gap/stop cases, cost reconciliation.
- **Status:** `DEFERRED — FORMAL APPROVAL REQUIRED` (research-scope decision).
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-19 — CI and supply-chain hardening gaps
- **Severity:** Medium · **Phase:** P2
- **Evidence:** actions by tag; no `permissions`; unpinned runtime deps; no vulnerability scan; `fail_ci_if_error=false`; matrix 3.11–3.13 vs local 3.14.8.
- **Root cause:** CI not hardened; Python support undefined.
- **Affected:** `.github/workflows/ci.yml`, dependency manifests.
- **Remediation:** SHA-pin actions; read-only permissions; lockfile/hashes; `pip-audit`; explicit 3.14 decision.
- **Dependencies:** none.
- **Acceptance:** Workflow passes with hardened settings; audit job runs.
- **Tests:** CI run evidence.
- **Status:** `IMPLEMENTED — AWAITING VERIFICATION`.
- **Commit / evidence:** `678433b`; `reports/audits/remediation/F19_CI_HARDENING.md`. Actions SHA-pinned; `permissions: contents: read`; 3.14 added to matrix; pip-audit step added. Lockfile/hashes follow-up tracked.
- **Closure:** Pending green Actions run and lockfile/hashes generation.

## F-20 — Experiment registry mutable; no promotion path
- **Severity:** Medium · **Phase:** P2
- **Evidence:** mutable `ExperimentRecord`; `save()` overwrites; `delete()`; dead `_MODIFIABLE_BEFORE_FREEZE`; no promotion code.
- **Root cause:** Registry modelled as mutable storage, not an evidence log.
- **Affected:** experiment repository.
- **Remediation:** Immutable content-addressed records; append-only supersession; promotion checklist enforced or scoped out.
- **Dependencies:** F-10 hash verification.
- **Acceptance:** Overwrite/delete impossible; supersession chain readable; promotion documented/enforced.
- **Tests:** Immutability, supersession, delete rejection.
- **Status:** `READY FOR IMPLEMENTATION`.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-21 — Simulation executors importable in production package
- **Severity:** Medium · **Phase:** P2
- **Evidence:** `SIMULATED_EVIDENCE` and hard-coded executors in production modules, referenced only by tests.
- **Root cause:** Test doubles shipped in production namespace.
- **Affected:** research/alpha executors.
- **Remediation:** Move under `tests/` or raise at import unless test flag; test cannot be selected outside tests.
- **Dependencies:** none.
- **Acceptance:** Production import cannot select simulated executor.
- **Tests:** Import/selection guard.
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `7db75db`; `reports/audits/remediation/F21_SIMULATION_EXECUTORS.md`. Import guard raises without test flag; build-time exclusion of eigencapital.research* documented. 785 research tests pass.
- **Closure:** Pending independent review.

## F-22 — Operational state files have no schema/version
- **Severity:** Medium · **Phase:** P2
- **Evidence:** `reports/r4_loop/*` JSON/JSONL unversioned; readers use `.get()` defaults; inconsistent naming.
- **Root cause:** Files grew as ad-hoc persistence.
- **Affected:** live loop, dashboard readers.
- **Remediation:** Version field; readers reject unknown versions; one documented owner per file.
- **Dependencies:** F-06 path unification.
- **Acceptance:** Every operational file versioned; unknown version fails closed.
- **Tests:** Version-reader matrix; unknown-version rejection.
- **Status:** `READY FOR IMPLEMENTATION` after F-06 path contract.
- **Commit / evidence:** none.
- **Closure:** Pending.

## F-23 — Documentation drift and absent governing specs
- **Severity:** Low · **Phase:** P3
- **Evidence:** loop comments say 1500/8 vs actual 5000/20; `SYSTEM_SPECIFICATION.md`, `domain_contracts.md` absent; EC-AUDIT-009 draft.
- **Root cause:** Docs not maintained with code; referenced specs never existed.
- **Affected:** comments, audit docs.
- **Remediation:** Fix comments; mark absent specs as historical references; state adopted gate explicitly.
- **Dependencies:** none.
- **Acceptance:** Comment values match code; absent specs labelled; gate status explicit.
- **Tests:** Doc/code consistency check (grep-based).
- **Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`.
- **Commit / evidence:** `55ebb33` (comment fix); `reports/audits/remediation/F23_DOCUMENTATION_DRIFT.md`. Loop comments now match config; absent specs labelled historical; EC-AUDIT-009 stated as not adopted / gate not passed.
- **Closure:** Pending independent review.

## F-24 — Dashboard repeat reads and in-memory rate limiting
- **Severity:** Low · **Phase:** P3
- **Evidence:** REST handlers re-read files; per-IP limiter is in-memory dict; 5 s broadcaster.
- **Root cause:** No shared snapshot cache; multi-worker unsafe.
- **Affected:** dashboard API/streaming.
- **Remediation:** Shared snapshot cache; document single-worker or external limiter.
- **Dependencies:** F-14 (state reads).
- **Acceptance:** One snapshot per broadcast interval; single-worker constraint documented.
- **Tests:** Cache reuse; limiter behaviour.
- **Status:** `READY FOR IMPLEMENTATION` after F-14.
- **Commit / evidence:** none.
- **Closure:** Pending.

---

## Dependency-ready queue

| Order | Unit | Findings | Rationale |
|---|---|---|---|
| 1 | Statistical correction: Holm/BH | F-09 | **DONE** — `174b5a1`, awaiting independent verification |
| 2 | Statistical correction: CSCV PBO | F-08 | **DONE** — `6e707ca`; re-derivation blocked on raw matrices |
| 3 | CI hardening | F-19 | **DONE** — `678433b`; no runtime behaviour |
| 4 | Documentation truth | F-23 | **DONE** — `e96b4e5`; zero behavioural risk |
| 5 | Simulation executor isolation | F-21 | **DONE** — `7db75db`; import-surface hardening |
| 6 | Dashboard auth hardening | F-15 | **DONE** — `e0fec4c`; security, no trading path |
| 7 | Dashboard truth | F-14, F-24 | Read-only consumer fixes |
| 8 | Experiment immutability | F-20 (with F-10 hash check) | Research evidence integrity |
| 9 | Forming-bar input | F-11 | **DONE** — `c91a8d9`; R4 maths unchanged |
| 10 | Stop-loss validation | F-04 | **DONE** — `18e254b`; gate still disabled |
| 11 | Execution/ledger P0 items | F-02 fixture, F-05, F-06, F-16, F-03 | Requires F-02 design + live-path approval |
| 12 | Decisions required | F-07, F-12, F-13, F-17, F-18 | Technical decision records / approval |
| 13 | Externally blocked | F-01 | Broker statement |

## Programme decisions held constant

- R4 strategy mathematics, lookbacks, thresholds, sizing, caps, universe, regime, and rebalance frequency unchanged.
- No capital increase, leverage change, broker configuration change, or live-order placement.
- Stop-loss gate remains disabled; only validation semantics are in scope.
- No production risk limits changed.
- No finding closed without recorded verification evidence.
