# EC-AUDIT-007 — Unit 6: Operational Hardening

**Status:** `COMPLETE — TWO BOUNDED HARDENING ITEMS IMPLEMENTED; HIGHER-RISK ITEMS DEFERRED`
**Branch:** `audit/ec-remediation-001`
**Based on:** `dc5e64b` (Unit 5 HEAD)
**Date:** 2026-10-31

---

## 1. Scope decision

Unit 6 was authorized to "keep separate from Units 4–5 and define its scope after
those findings are available." The Unit 4–5 findings produced four operational
and seven research-provenance recommendations. This unit implements only the
items that are **low-risk, behavior-preserving, and independently testable**:

| ID | Item | Decision |
|---|---|---|
| H-6.1 | `ProcessSupervisor.release()` must persist a terminal state and write health atomically | **Implemented** |
| H-6.2 | Evidence index must label `decisions.jsonl` as non-tamper-evident and correct stale log paths | **Implemented** |
| R-4-B | Hash-chain `decisions.jsonl` | Deferred — changes the audit data format |
| R-4-D | Single machine-readable attestation command | Deferred — new tooling, separate design |
| R-5-A..G | Provenance redesign, artifact persistence, append-only enforcement | Deferred — changes research record semantics |

**No trading behavior, R4 identity, risk envelope, or historical evidence was
modified.** R-002-A remains open.

---

## 2. H-6.1 — Supervisor terminal-state consistency

### Problem (from Unit 4, F-4-2)

`ProcessSupervisor.release()` removed `supervisor.pid` and wrote
`loop_health.json` with `alive: false`, but left `supervisor_state.json` with
`"status": "running"`. An operator or dashboard reading only the status field
could conclude a released process was still live. The health write was also
non-atomic.

### Change

`src/eigencapital/live/supervisor.py::release()` now:

1. removes the PID file (unchanged);
2. rewrites `supervisor_state.json` with a terminal status:
   - `"stopped"` for a normal release;
   - `"frozen"` is **preserved** (a deliberate terminal state must not be
     masked by a clean exit);
3. writes `loop_health.json` atomically via temp file + `fsync` + `os.replace`,
   matching `mark_healthy()`.

`claim_instance()` already overwrites the state with `"running"`, so a fresh
claim is unaffected.

### Tests added (`tests/unit/test_supervisor.py`)

- `test_release_marks_state_stopped`
- `test_release_preserves_frozen_status`
- `test_claim_after_release_resets_status_to_running`
- `test_release_without_claim_writes_dead_health`

Result: `tests/unit/test_supervisor.py` + `tests/unit/test_r4_single_instance.py`
= **35 passed**.

### Compatibility

The dashboard's supervisor dimension treats `alive=false` + non-`running`
status as `HALTED / "Supervisor not responding"`, which is the correct
interpretation of a released instance. No dashboard change was required.

---

## 3. H-6.2 — Evidence labeling and path correction

`docs/production/PRODUCTION_EVIDENCE_INDEX.md` now states:

- `reports/r4_loop/decisions.jsonl` is **append-only but not hash-chained**;
  tamper evidence must come from the `DurableAudit` stores
  (`reports/execution_audit.jsonl`, `reports/campaigns.jsonl` and mirrors).
- the operational log is `loop_stdout.log` (launcher-dependent;
  `r4_daily.sh` writes `runs/YYYY-MM-DD.log`), not the nonexistent `loop.log`.
- `supervisor_state.json` is listed with its terminal-on-release semantics.

`docs/production/LIVE_PROCESS_ATTESTATION.md` was updated so the Unit 4
staleness pitfall reflects the new behavior while still warning that **older
artifacts** may contain a stale `running` status.

---

## 4. Verification

| Check | Result |
|---|---|
| `pytest tests/unit/test_supervisor.py tests/unit/test_r4_single_instance.py` | 35 passed |
| `ruff check` on changed Python files | pass |
| `ruff format --check` on changed Python files | pass |
| `mypy src/eigencapital/live/supervisor.py` | pass |

No full-suite run was performed in this unit; the change is confined to
`ProcessSupervisor.release()` and its tests. Unit 7 records the final
verification state.

---

## 5. Deferred items and rationale

- **R-4-B (hash-chain `decisions.jsonl`)**: would change the on-disk audit
  format and require migration/verification of existing ledgers. It needs its
  own design and authorization.
- **R-4-D (attestation command)**: new tooling; better specified after the
  evidence formats stabilize.
- **R-5-A..G (provenance)**: the Unit 5 finding that the provenance hash is
  self-referential cannot be fixed by editing historical records. A forward
  fix changes how future hashes are computed and how records are verified; it
  needs explicit authorization and a migration note.
- **Append-only enforcement**: `ExperimentRepository` still exposes
  `save()`/`delete()`; removing them changes the registry lifecycle API.

---

## 6. Residual risks

| ID | Risk | State |
|---|---|---|
| R-002-A | Invalid SL treated as protected when policy requires SL | **Open** |
| R-4-B | `decisions.jsonl` is not tamper-evident | Documented |
| R-5-B | Provenance hash not independently verifiable | Documented |
| R-5-G | "Append-only" ledger is not enforced by the repository API | Documented |

---

## 7. Conclusion

Unit 6 resolves the concrete status-file inconsistency and closes the evidence-
labeling gap without changing trading behavior or historical records. The
remaining hardening items are recorded as deferred, with reasons, rather than
silently applied.
