# EC Audit Remediation — Status 002 (Units 0–7)

**Status:** `COMPLETE THROUGH UNIT 7 — CAPITAL INCREASE NOT AUTHORIZED`
**Branch:** `audit/ec-remediation-001`
**Base:** `9efb1c9`
**Date:** 2026-10-31

---

## 1. Scope

This status supersedes `EC_AUDIT_REMEDIATION_STATUS_001.md`. It covers the full
authorized sequence: preflight (Unit 0), R4 identity (Unit 1), stop-loss policy
(Unit 2), test attestation (Unit 3), live-process attestation (Unit 4), research
trial ledger provenance (Unit 5), operational hardening (Unit 6), and capital
readiness (Unit 7).

No live broker action, capital movement, configuration change, or destructive git
operation was performed. The pre-existing stash
`stash@{0}: WIP on fix/findings-resolution: d77d5ef` was preserved.

---

## 2. Commits

| Unit | Commit | Subject |
|---|---|---|
| 1 | `40382f8` | R4 signal-fidelity tests and identity decision record |
| 2 | `8d0e102` | Stop-loss policy verification and tests |
| 3 | `4861dc3` | Test attestation and remediation status 001 |
| 4 | `84e7b2f` | Live-process attestation guidance and runbook paths |
| 5 | `dc5e64b` | Research trial ledger provenance verification |
| 6 | `b71c5cf` | Terminal supervisor state and atomic health write |
| 7 | *(this commit)* | Capital readiness assessment and status 002 |

---

## 3. Deliverables

### Unit 1 — R4 identity (`EC-AUDIT-001`)

- `tests/unit/test_r4_signal_fidelity.py` (11 tests).
- `docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`, `docs/architecture/CONFIGURATION_INVENTORY.md` corrected.
- `reports/audits/EC_AUDIT_001_R4_IDENTITY_DECISION_RECORD.md`: `APPROVED — ALTERNATIVE A`.
- Finding: the live signal divisor is `0.50`; `vol_target_annual = 0.10` is declared but unused.

### Unit 2 — Stop-loss policy (`EC-AUDIT-002`)

- `tests/unit/live/test_stop_loss_policy.py` (14 passed, 3 strict xfail for R-002-A).
- `docs/production/FAILURE_RECOVERY_MATRIX.md` row 13 corrected.
- `reports/audits/EC_AUDIT_002_STOP_LOSS_POLICY_VERIFICATION.md`.
- Finding: production sets `require_sl_on_positions = false`; **R-002-A remains open**.

### Unit 3 — Test attestation (`EC-AUDIT-004`)

- `reports/audits/EC_AUDIT_004_TEST_ATTESTATION.md`.
- Segmented evidence: 3,626 passed, 2 skipped, 3 xfailed across segments.
- Monolithic run operator-aborted; not claimed as passing.

### Unit 4 — Live-process attestation (`EC-AUDIT-005`)

- `docs/production/LIVE_PROCESS_ATTESTATION.md` (6-question model, 8-step procedure).
- `docs/production/OPERATIONS_RUNBOOK.md` paths corrected.
- `reports/audits/EC_AUDIT_005_LIVE_PROCESS_ATTESTATION_GUIDANCE.md` (F-4-1..F-4-6).
- Findings: status-file staleness, optional T=0, absent `DurableAudit` stores, duplicate-loop exit 75.

### Unit 5 — Research provenance (`EC-AUDIT-006`)

- `reports/audits/EC_AUDIT_006_RESEARCH_TRIAL_LEDGER_PROVENANCE.md`.
- Verified: dataset hash chain, `strategy_config_hash`, freeze hash.
- Gaps G-5-1..G-5-10: unverifiable completion hash, missing report artifact,
  unresolvable commit, empty strategy artifact hash, no lineage, trial-count split
  (6 vs 14), symbol mismatch (42/38/37).

### Unit 6 — Operational hardening (`EC-AUDIT-007`)

- `src/eigencapital/live/supervisor.py`: `release()` writes `stopped` (preserving
  `frozen`) and writes `loop_health.json` atomically.
- 4 new tests in `tests/unit/test_supervisor.py`.
- `docs/production/PRODUCTION_EVIDENCE_INDEX.md` labels `decisions.jsonl` as
  non-tamper-evident and corrects `loop.log → loop_stdout.log`.
- `docs/production/LIVE_PROCESS_ATTESTATION.md` updated for the new behavior.
- `reports/audits/EC_AUDIT_007_OPERATIONAL_HARDENING.md`.
- Higher-risk items (R-4-B, R-4-D, R-5-A..G) deferred with rationale.

### Unit 7 — Capital readiness (`EC-AUDIT-008`)

- `reports/audits/EC_AUDIT_008_CAPITAL_READINESS_ASSESSMENT.md`.
- **Verdict: `NOT READY — CAPITAL INCREASE NOT AUTHORIZED`.**
- Blockers: no capital-event ledger; unexplained equity step changes
  (+39%, +56.8%, +34.2%); stale T=0; SL gate disabled; non-tamper-evident
  execution audit; unverifiable research provenance; inconsistent runtime state;
  absolute (non-scaled) risk limits.

---

## 4. Final verification

| Check | Result |
|---|---|
| `pytest tests/unit/test_supervisor.py tests/unit/test_r4_single_instance.py tests/unit/test_crash_recovery.py tests/unit/test_restart_recovery_certification.py` | 54 passed |
| `pytest tests/unit/live tests/unit/production_qual tests/integration tests/property` | 669 passed, 1 skipped, 3 xfailed, 2 property timing failures |
| `pytest tests/property` (isolated) | 10 passed |
| `ruff check .` | pass |
| `ruff format --check .` | 593 files already formatted |
| `mypy src/` | 310 files, no issues |
| `git diff --check` | pass |

The two property failures are `DeadlineExceeded`-class timing flakes under
combined load; both pass in isolation and in the property-only run. They are
recorded as a test-suite sensitivity, not a code regression. The monolithic suite
remains operator-aborted and is not claimed as passing.

---

## 5. Open items

| ID | Item | State |
|---|---|---|
| R-002-A | Invalid SL treated as protected when policy requires SL | **Open** — do not fix without separate authorization |
| R-4-B | `decisions.jsonl` not tamper-evident | Documented; deferred |
| R-4-D | No single machine-readable attestation command | Deferred |
| R-5-A..G | Provenance redesign, artifact persistence, append-only enforcement | Deferred |
| C-7.1 | No capital-event ledger | **Blocker for capital increase** |
| C-7.2 | Stale T=0 attestation | **Blocker** |
| C-7.3 | SL protection disabled / R-002-A | **Blocker** |
| C-7.5 | No `DurableAudit` execution chain | **Blocker** |
| C-7.7 | Risk limits not capital-scaled | **Blocker** |
| — | Phase 2 baseline lock not captured (skip) | Open |
| — | Property tests sensitive to load | Documented |

---

## 6. Conclusion

Units 0–7 are complete as scoped. The remediation corrected documentation,
added regression tests, verified the research dataset chain, hardened the
supervisor's terminal-state behavior, and produced an evidence-based capital
readiness assessment. The assessment **does not authorize a capital increase**;
the conditions for reconsideration are listed in `EC_AUDIT_008`.

R-002-A remains open and must not be silently marked resolved.
