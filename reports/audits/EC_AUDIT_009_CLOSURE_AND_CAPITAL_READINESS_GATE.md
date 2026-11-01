# EC-AUDIT-009 — Closure & Capital Readiness Gate

**Status:** `DRAFT — GATE NOT PASSED`
**Capital decision:** `CAPITAL INCREASE NOT AUTHORIZED`
**Branch:** `audit/ec-remediation-001`
**Baseline for this gate:** `fc59b99` (Units 1–7)
**Date:** 2026-10-31

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
3. a reproducible **acceptance test** (command + pass criterion),
4. the **evidence location** that must be attached at sign-off.

The gate is **not** a remediation plan and does **not** authorize trading,
capital, leverage, risk-limit, or configuration changes. It exists so the next
capital-readiness decision is reproducible rather than subjective.

---

## 2. Gate decision rule

The gate passes only when **all P0 and P1 rows are `PASS`**, each with evidence
produced at one named commit and one clean tree, and an independent reviewer has
signed Section 7. Until then:

- **Capital increase: NOT AUTHORIZED.**
- **Live broker changes: NOT AUTHORIZED.**
- **Leverage / risk-limit increases: NOT AUTHORIZED.**
- **Stop-loss gate stays disabled** until R-002-A is fixed, tested, and
  separately approved.

A `PASS` requires the command to exit 0 **and** the stated invariant to hold.
A test that passes only when run in isolation is recorded as `FLAKY`, not `PASS`.

---

## 3. Closure matrix

### P0 — capital blockers

| ID | Finding / gap | Owner (role) | Required remediation | Acceptance test | Evidence | Status |
|---|---|---|---|---|---|---|
| P0-1 | C-7.1: unexplained equity step changes (+39.0%, +56.8%, +34.2%) | Finance/Ops + Data | Build `scripts/audit/equity_reconciliation.py`; classify every equity change as deposit, withdrawal, credit, adjustment, or realized P&L; reconcile to broker statement | `python scripts/audit/equity_reconciliation.py --start 2026-09-26 --end 2026-10-29 --statement <broker.csv>` → exit 0, `unexplained_steps == 0`, `abs(delta) < 0.01` | `reports/audits/equity_reconciliation_<date>.json` | OPEN |
| P0-2 | C-7.1: no capital-event ledger | Finance/Ops | Persist `reports/capital_events.jsonl` via `DurableAudit` (SHA-256 chain); record every deposit/withdrawal/credit/adjustment with timestamp, amount, currency, reference | `python scripts/audit/verify_capital_events.py` → `valid=True`, `n_records > 0`, reconciliation delta `< $0.01` | `reports/capital_events.jsonl` + `.mirror` + verify output | OPEN |
| P0-3 | C-7.5: no `DurableAudit` execution chain | Execution/Platform | Wire `AuditLog` (`src/eigencapital/execution/events.py`) into `scripts/r4_rebalance_loop.py` so every decision → intent → fill is appended durably; keep `decisions.jsonl` as secondary | Run one dry-run cycle; `python -c "from pathlib import Path; from eigencapital.live.durable_audit import DurableAudit; v=DurableAudit(Path('reports/execution_audit.jsonl'), Path('reports/execution_audit.mirror.jsonl')).verify(); print(v); assert v.valid and v.n_records>0"` → exit 0 | `reports/execution_audit.jsonl` + `.mirror`; linkage test | OPEN |
| P0-4 | R-002-A: `sl == 0` treats `None`/negative/non-numeric as protected | Risk/Live | Change classification to require a finite, positive numeric SL; keep `sl == 0` critical; add explicit tests for `None`, negative, string, `NaN` | `python -m pytest tests/unit/live/test_stop_loss_policy.py -q` → 17 passed, **0 xfailed**; the three currently xfailed tests pass | Test output at gate commit | OPEN |

### P1 — readiness blockers

| ID | Finding / gap | Owner (role) | Required remediation | Acceptance test | Evidence | Status |
|---|---|---|---|---|---|---|
| P1-1 | C-7.2 / F-4-4 / R-4-C: stale T=0 (newest 2026-09-30; 96 `t0_validated` events all against September snapshots) | Production Qual + Governance | Capture a fresh T=0 for the current campaign; decide whether missing T=0 must fail closed (policy decision) | `python scripts/r4_generate_t0.py --campaign-id <id>` (read-only broker, no orders) → new `T0_*.json`; startup emits `t0_validated`; policy decision recorded | New `reports/r4_qualification/T0_*.json`; `decisions.jsonl` `t0_validated`; policy note | OPEN |
| P1-2 | G-5-1..G-5-10 / R-5-A..G: research provenance | Research | Persist report artifact + hash; make provenance non-self-referential; record resolvable commit; populate `strategy_artifact_hash` and `parent_experiment_id`; reconcile trial slots; enforce append-only; resolve 42/38/37 symbol count | `python scripts/audit/verify_experiment.py --id EXP-000002` → all checks pass; `python -m pytest tests/unit/research/experiments -q` → pass | Verifier output + updated `research/experiments/registry/EXP-000002.json` | OPEN |
| P1-3 | C-7.8: property timing flakes | Test Infra | Diagnose the intermittent property failures (the previously known one is a Hypothesis `DeadlineExceeded`); set an explicit deadline or remove the global deadline; record root cause | `for i in 1 2 3; do python -m pytest tests/property -q || exit 1; done` → 3 consecutive 10/10 runs under the recorded load profile | Three run logs + root-cause note | OPEN |
| P1-4 | Unit 3: Phase 2 baseline lock not captured (skip) | Production Qual | Run the existing capture script | `python scripts/capture_phase2_baseline.py` → `reports/phase2_baseline.json`; `python -m pytest tests/unit/production_qual/test_phase2_parity.py::TestPhase2BaselineLock -q` → 2 passed, 0 skipped | Baseline file + test output | OPEN |
| P1-5 | C-7.6: operational-state inconsistencies | Live Ops | Reconcile `supervisor_state.json` vs `loop_health.json`; `runtime_state.daily_start` vs `daily_baseline.equity`; `diag.active_positions` vs actual positions; disposition every `intent_discrepancy`; document `t0_mismatch`, `frozen`, `quarantine` | Read-only audit script asserts: dead PID never shows `running`; `daily_start == baseline_equity` (or documented delta); `active_positions == len(positions)`; zero unexplained discrepancies in a fresh cycle | Audit script output + run log | OPEN |
| P1-6 | C-7.7: absolute, non-scaled risk limits | Risk + Finance | Write a capital-scaling policy: proportional daily-loss and position limits, equity floor, max deployment; add config validation test | Policy doc approved; `python -m pytest tests/unit/test_config_consistency.py -q` includes a test that limits scale with equity | Policy doc + test output | OPEN |
| P1-7 | Unit 3: monolithic suite operator-aborted | Test Infra | Run the full suite to completion in CI (not an interactive terminal) | CI job runs `python -m pytest tests/` → pass; attach job URL/log | CI log at gate commit | OPEN |

### P2 — post-gate / deferred

| ID | Finding / gap | Owner | Disposition | Status |
|---|---|---|---|---|
| P2-1 | R-4-D: no single machine-readable attestation command | Live Ops | Build after P1-5 stabilizes the evidence formats | DEFERRED |
| P2-2 | C-7.4 reassessment | Audit + independent reviewer | Re-run `EC_AUDIT_008` only after P0/P1 pass | DEFERRED |
| P2-3 | Storage-policy skip (`test_forced_unavailable_engine_raises`) | Test Infra | Environment-dependent; record as accepted or add a forced-unavailable fixture | DEFERRED |

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

| Role | Name | Date | Commit / tree | Evidence bundle |
|---|---|---|---|---|
| Finance/Ops | | | | |
| Risk | | | | |
| Research | | | | |
| Execution/Platform | | | | |
| Production Qual | | | | |
| Independent reviewer | | | | |

Gate result: `PASS` / `FAIL` (circle one). Capital decision: `AUTHORIZED` /
`NOT AUTHORIZED` (circle one, subject to separate governance approval).
