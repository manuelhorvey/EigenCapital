# EC-AUDIT-009 — Closure & Capital Readiness Gate

**Status:** `DRAFT — AMENDED FOLLOWING INDEPENDENT REVIEW; NOT ADOPTED; GATE NOT PASSED`
**Capital decision:** `CAPITAL INCREASE NOT AUTHORIZED`
**Branch:** `audit/ec-remediation-001`
**Baseline for this gate:** `f1faffe` (Units 1–7 plus gate v1)
**Date:** 2026-10-31
**Review basis:** independent document review of v1, findings F-009-01..F-009-07
plus additional row issues (Section 8)

> **Naming note.** `EC-AUDIT-001` is already the R4 identity decision record
> (`reports/audits/EC_AUDIT_001_R4_IDENTITY_DECISION_RECORD.md`). This gate uses
> `EC-AUDIT-009` to avoid overwriting it. If a separate closure series is
> intended, rename this file before adoption; the content is independent of the
> number.

---

## 1. Purpose

This is the single closure artifact for the EC-AUDIT remediation. It maps every
open finding and evidence gap to:

1. an accountable **role** (not a named individual),
2. the required **remediation**,
3. a reproducible **acceptance test** (command + invariant),
4. the **evidence location** that must be attached at sign-off.

The gate is **not** a remediation plan and does **not** authorize trading,
capital, leverage, risk-limit, or configuration changes. It exists so the next
capital-readiness decision is reproducible rather than subjective.

---

## 2. Gate decision rule

The gate distinguishes three decisions that must never collapse into one:

1. **Technical closure** — every P0 and P1 remediation acceptance criterion
   passes, at one named commit and one clean tree.
2. **Audit closure** — the evidence is reviewed and independently accepted by a
   reviewer who did not implement the remediation or produce its primary
   evidence.
3. **Capital authorization** — a separate governance decision grants permission
   to increase capital. It is **not** granted by this gate.

> A `PASS` under EC-AUDIT-009 certifies only that the listed audit closure
> criteria have been satisfied. It does not authorize capital increases, broker
> actions, leverage changes, risk-limit changes, or production deployment. Those
> actions require a separate, explicit governance decision.

Until all P0/P1 rows pass and Section 7 is signed:

- **Capital increase: NOT AUTHORIZED.**
- **Live broker changes: NOT AUTHORIZED.**
- **Leverage / risk-limit increases: NOT AUTHORIZED.**
- **Stop-loss gate stays disabled** until R-002-A is fixed, tested, and
  separately approved.

A `PASS` requires the command to exit 0 **and** the stated invariant to hold.
A test that passes only when run in isolation is recorded as `FLAKY`, not `PASS`.
The independent reviewer must declare no conflict of interest and must not be
the implementer of the row under review.

---

## 3. Closure matrix

### P0 — capital blockers

| ID | Finding / gap | Owner (role) | Required remediation | Acceptance test | Evidence | Status |
|---|---|---|---|---|---|---|
| P0-1 | C-7.1: unexplained equity step changes (+39.0%, +56.8%, +34.2%) | Finance/Ops + Data | Build `scripts/audit/equity_reconciliation.py`; classify every equity change as deposit, withdrawal, credit, adjustment, realized P&L, or floating P&L; reconcile to a broker statement; explain each of the three jumps individually with a source reference | `python scripts/audit/equity_reconciliation.py --start 2026-09-26 --end 2026-10-29 --statement <broker.csv>` → exit 0; `unexplained_steps == 0`; each jump has a classification and evidence reference; `abs(delta) < 0.01` USD | `reports/audits/equity_reconciliation_<date>.json` | OPEN |
| P0-2 | C-7.1: no capital-event ledger | Finance/Ops | Bootstrap `reports/capital_events.jsonl` from the broker statement/MT5 deal history via `DurableAudit`; record every deposit/withdrawal/credit/adjustment with timestamp, amount, currency, reference; backfill history, do not synthesize | `python scripts/audit/verify_capital_events.py` → `valid=True`; `n_records > 0`; coverage starts `2026-09-26`; opening balance matches the broker statement; reconciliation delta `< $0.01` | `reports/capital_events.jsonl` + `.mirror` + verify output | OPEN |
| P0-3 | C-7.5: no `DurableAudit` execution chain | Execution/Platform | Wire `AuditLog` (`src/eigencapital/execution/events.py`) into `scripts/r4_rebalance_loop.py` with a stable linkage schema: `decision_id` → `intent_id` → `order_id` → `fill_id`; fail closed on duplicates, missing parents, invalid transitions, or contradictory ordering; replay must reconstruct the same state | `python -m pytest tests/unit/execution/test_execution_chain_linkage.py -q` (new) → pass; `python -c "from pathlib import Path; from eigencapital.live.durable_audit import DurableAudit; v=DurableAudit(Path('reports/execution_audit.jsonl'), Path('reports/execution_audit.mirror.jsonl')).verify(); print(v); assert v.valid and v.n_records>0"` → exit 0; dry-run asserts `broker_submissions == 0` | `reports/execution_audit.jsonl` + `.mirror`; linkage/replay test output | OPEN |
| P0-4 | R-002-A: `sl == 0` treats `None`/negative/non-numeric as protected | Risk/Live | Require a finite, positive numeric SL; keep `sl == 0` critical; validate direction and price: long SL below entry/reference, short SL above, instrument tick/precision respected | `python -m pytest tests/unit/live/test_stop_loss_policy.py -q` → all pass, **0 xfailed**; the three former strict xfails pass; new direction/precision cases pass | Test output at gate commit | OPEN |

**P0-1 accounting invariant (defined).** For each interval:

```
broker_equity(t) = opening_balance
                 + deposits - withdrawals
                 + realized_pnl
                 + credits - fees
                 + floating_pnl
delta = broker_equity(t) - reconstructed_equity(t)
```

Currency is USD. Balance and equity are reported separately. Floating P/L must
not be booked as realized P/L. Fees, swaps and credits are itemised. Rounding
policy: compare at cent precision; `abs(delta) < 0.01`.

**P0-2 bootstrap rule (defined).** Effective start `2026-09-26`; opening balance
from the broker statement at that date; source of truth is the broker statement
plus MT5 deal history. Historical transactions must be backfilled. An empty or
synthetic-only ledger is invalid.

**P0-3 linkage invariant (defined).** Each execution decision has a stable unique
identifier; every intent references its originating decision; every order
references its intent; every fill references its order. Duplicate identities,
missing parents, invalid transitions, contradictory event ordering, and replay
divergence fail closed. A dry-run must prove no broker submission occurred.

**P0-4 SL validity (defined).** A positive value alone is insufficient: the stop
must be on the valid side of the entry/current-price reference for the position
direction and must respect instrument precision/tick size and price constraints.

### P1 — readiness blockers

| ID | Finding / gap | Owner (role) | Required remediation | Acceptance test | Evidence | Status |
|---|---|---|---|---|---|---|
| P1-1 | C-7.2 / F-4-4 / R-4-C: stale T=0 (newest 2026-09-30; 96 `t0_validated` events all against September snapshots) | Production Qual + Governance | Capture a fresh campaign-specific T=0; document the policy outcome: absent T=0 warns and proceeds, present-but-mismatched T=0 aborts, unless a separately approved policy change supersedes this; add tests for both paths | `python scripts/r4_generate_t0.py --campaign-id <id>` (read-only broker, no orders) → new `T0_*.json`; absent-snapshot test asserts warning + proceed; mismatched-snapshot test asserts abort; policy decision recorded | New `reports/r4_qualification/T0_*.json`; test output; policy note | OPEN |
| P1-2 | G-5-1..G-5-10 / R-5-A..G: research provenance | Research | Persist report artifact + hash; make provenance non-self-referential; record a resolvable commit; populate `strategy_artifact_hash` with the immutable artifact hash (code + config + data manifest); encode root semantics (`parent_experiment_id` may be empty only for an explicitly marked root); reconcile trial slots; enforce append-only; resolve 42/38/37 symbol count | `python scripts/audit/verify_experiment.py --id EXP-000002` → all checks pass, including root/child semantics; `python -m pytest tests/unit/research/experiments -q` → pass | Verifier output + updated `research/experiments/registry/EXP-000002.json` | OPEN |
| P1-3 | C-7.8: property timing flakes | Test Infra | Diagnose the intermittent property failures (the previously known one is a Hypothesis `DeadlineExceeded`); set an explicit deadline or remove the global deadline; record root cause, environment, load profile, and seed behavior | `for i in 1 2 3; do python -m pytest tests/property -q || exit 1; done` → 3 consecutive 10/10 runs under the recorded profile; if root cause is not identified, status remains `FLAKY` | Three complete run logs + root-cause/environment note | OPEN |
| P1-4 | Unit 3: Phase 2 baseline lock not captured (skip) | Production Qual | Run the existing capture script with a defined campaign identity; do not silently overwrite an existing baseline | `python scripts/capture_phase2_baseline.py` → `reports/phase2_baseline.json` containing campaign ID and commit; existing baseline not overwritten without explicit `--force` and approval; `python -m pytest tests/unit/production_qual/test_phase2_parity.py::TestPhase2BaselineLock -q` → 2 passed, 0 skipped | Baseline file + test output | OPEN |
| P1-5 | C-7.6: operational-state inconsistencies | Live Ops | Reconcile `supervisor_state.json` vs `loop_health.json`; `runtime_state.daily_start` vs `daily_baseline.equity`; `diag.active_positions` vs actual positions; disposition every `intent_discrepancy`; document `t0_mismatch`, `frozen`, `quarantine`; sample all compared state at one observation timestamp | Read-only audit script asserts: dead PID never shows `running`; `daily_start == baseline_equity` (or documented delta); `active_positions == len(positions)`; zero unexplained discrepancies in a fresh cycle; transient states documented | Audit script output + run log | OPEN |
| P1-6 | C-7.7: absolute, non-scaled risk limits | Risk + Finance | **Design and approval only** — assess whether current frozen R4 limits are appropriate for the deployed capital and propose a scaling policy. Do **not** change production configuration or risk limits under this gate; any change requires separate governance approval and is out of scope | Design doc + approval record; no production config change in the gate commit; `git diff` shows no risk-policy change | Policy design doc + approval record | OPEN |
| P1-7 | Unit 3: monolithic suite operator-aborted | Test Infra | Run the full suite to completion in CI with a recorded baseline | CI job records collection count, pass/skip/xfail counts, warning policy, timeout, Python version, and commit; zero unexpected failures; every skip/xfail explained; no silently deselected tests | CI log + `--collect-only` count at gate commit | OPEN |

### P2 — post-gate / deferred

| ID | Finding / gap | Owner | Disposition | Status |
|---|---|---|---|---|
| P2-1 | R-4-D: no single machine-readable attestation command | Live Ops | Build after P1-5 stabilizes the evidence formats; output must be machine-readable and fail closed | DEFERRED |
| P2-2 | C-7.4 reassessment | Audit + independent reviewer | Re-run `EC_AUDIT_008` only after P0/P1 pass | DEFERRED |
| P2-3 | Storage-policy skip (`test_forced_unavailable_engine_raises`) | Test Infra | Environment-dependent; require explicit disposition before any final acceptance claim that depends on this behavior | DEFERRED |

### Closed by Units 1–7 (reference)

| ID | Finding | Closure | Status |
|---|---|---|---|
| U1 | R4 identity mismatch (`0.10` declared vs `0.50` divisor) | `EC_AUDIT_001` decision record, Alternative A | CLOSED |
| U2 | `FAILURE_RECOVERY_MATRIX` row 13 | Corrected | CLOSED |
| F-4-2 / R-4-A | `release()` left status `running` | Unit 6 (`b71c5cf`); historical artifact documented, not rewritten | CLOSED (forward) |
| F-4-3 / R-4-B | `decisions.jsonl` not tamper-evident | Unit 6 labeled it non-tamper-evident; hash-chaining remains optional | CLOSED (by labeling) |
| F-4-5 | Runbook path drift | Unit 4 corrected `supervisor.pid` / `loop_stdout.log` | CLOSED |
| F-4-6 | Guard-bypass modes / duplicate exit 75 | Documented in `LIVE_PROCESS_ATTESTATION.md` | CLOSED (documented) |

---

## 4. Evidence-preservation requirements

Both verification records must be retained; neither replaces the other:

1. **Unit 3 segmented evidence** at `4861dc3`: 3,626 passed, 2 skipped,
   3 xfailed across segments; monolithic run operator-aborted.
2. **Final combined evidence** at `b71c5cf` (code-identical to `fc59b99`; Unit 7
   changed audit docs only): 669 passed, 1 skipped, 3 xfailed, 2 property timing
   failures; isolated property run 10/10.

The two property failures (`test_events_are_immutable`,
`test_correlation_chains_are_complete`) are recorded as **intermittent** and must
not be described as resolved until P1-3 identifies the cause. Every gate row
must state the exact commit and `git status --porcelain` output at test time.

---

## 5. Explicit non-actions

- No capital increase.
- No live broker changes.
- No leverage or risk-limit increase.
- No assumption that the equity jumps are trading profits.
- No promotion of research candidates based on incomplete provenance.
- No production configuration change to make the gate look complete.

---

## 6. Current verdict

**GATE NOT PASSED. CAPITAL INCREASE NOT AUTHORIZED.**

P0-1 through P0-4 and P1-1 through P1-7 are open. The next milestone is
evidence closure, not more aggressive trading.

---

## 7. Sign-off (to be completed only when all P0/P1 rows are PASS)

**Independence requirement.** The reviewer must not be the implementer of the
remediation or the producer of its primary evidence. A conflict-of-interest
declaration is required. The reviewer must inspect the evidence, not only the
gate document.

| Role | Name | Date | Commit / tree | Evidence bundle | Conflict declared |
|---|---|---|---|---|---|
| Finance/Ops | | | | | |
| Risk | | | | | |
| Research | | | | | |
| Execution/Platform | | | | | |
| Production Qual | | | | | |
| Independent reviewer | | | | | |

**Three separate decisions:**

| Decision | Result | Notes |
|---|---|---|
| Technical closure (P0/P1 acceptance criteria) | `PASS` / `FAIL` | |
| Audit closure (independent evidence acceptance) | `ACCEPTED` / `REJECTED` | |
| Capital authorization | **NOT GRANTED BY THIS GATE** | Requires separate governance decision |

A `PASS` under EC-AUDIT-009 does not authorize capital increases, broker actions,
leverage changes, risk-limit changes, or production deployment.

---

## 8. Review disposition (v1 → v2)

**Review scope limitation.** The reviewer inspected the gate document, not the
repository at `f1faffe`; the findings below are document-level review findings,
not independently reproduced implementation defects.

| Review finding | Severity | Disposition | Where addressed |
|---|---|---|---|
| F-009-01: P0-3 dry-run acceptance too weak; no decision→intent→order→fill linkage | Critical | Strengthened | P0-3 row + linkage invariant |
| F-009-02: P0-2 ledger bootstrap ambiguous (`n_records > 0` insufficient) | Critical | Amended | P0-2 row + bootstrap rule |
| F-009-03: P0-1 `delta` undefined; realized vs floating P/L conflated | High | Amended | P0-1 row + accounting invariant |
| F-009-04: P1-1 policy outcome not a clear pass condition | High | Amended | P1-1 row |
| F-009-05: P1-6 risks changing frozen production policy | Critical | Amended | P1-6 row (design-only; no change under this gate) |
| F-009-06: P1-7 full-suite baseline underspecified | High | Amended | P1-7 row |
| F-009-07: independent sign-off lacks independence definition | High | Amended | Section 2 + Section 7 |
| P0-4: positive SL does not establish validity | High | Strengthened | P0-4 row + SL validity rule |
| P1-2: root-experiment semantics and immutable artifact hash | High | Clarified | P1-2 row |
| P1-3: three clean runs do not prove absence of flakiness | High | Clarified | P1-3 row |
| P1-4: baseline capture may overwrite silently | Medium | Clarified | P1-4 row |
| P1-5: state comparisons may be transient | Medium | Clarified | P1-5 row |
| P2-1: attestation output should be machine-readable/fail-closed | Medium | Recorded | P2-1 row |
| P2-3: storage-policy skip needs explicit disposition | Medium | Recorded | P2-3 row |
| Structural: distinguish technical closure, audit closure, capital authorization | Critical | Added | Section 2 + Section 7 |

**Preserved decisions:** the T=0 distinction (absent → warning; mismatched →
abort), the capital prohibition, the intermittent property-failure record, and
the separate retention of Unit 3 and final combined evidence.

**Review disposition:** `ACCEPTED AS DRAFT CLOSURE FRAMEWORK; AMENDMENTS
INCORPORATED; NOT ADOPTED`.

---

## 9. Adoption status and next steps

**Status:** `DRAFT — AMENDED; NOT ADOPTED; GATE NOT PASSED`.

Do not implement P0/P1 fixes merely because the gate has been reviewed. Execute
remediation one finding at a time, preserving the frozen R4 strategy and
requiring separate authorization for any risk-policy or production change.

Suggested order, based on trust impact:

1. Equity and capital-event reconciliation (P0-1, P0-2).
2. Durable execution decision-to-fill linkage (P0-3).
3. R-002-A stop-loss validation (P0-4).

Then proceed to the P1 readiness blockers. Capital authorization remains a
separate governance decision after technical and audit closure.
