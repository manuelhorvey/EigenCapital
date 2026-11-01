# F-20 — Experiment Registry Immutability

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `63c2cbe`
**Severity:** Medium · **Phase:** P2
**Date:** 2026-11-01

---

## 1. Finding

`ExperimentRecord` was a mutable dataclass; `repository.save()` overwrote
existing records; `repository.delete()` removed them; `_MODIFIABLE_BEFORE_FREEZE`
was dead code; no promotion path existed. Research records could be silently
overwritten or deleted, so they were not an auditable evidence log.

## 2. Correction

`src/eigencapital/research/experiments/registry.py`:

- `ExperimentRecord` is now a `frozen=True` dataclass; nested dicts
  (`parameters`, `result`, `trial_metadata`) are defensively copied on
  construction. Field assignment after construction raises
  `FrozenInstanceError`.
- Removed dead `_MODIFIABLE_BEFORE_FREEZE`.
- `create()` / `freeze_test_parameters()` / `start()` / `complete()` now
  construct a new record object (with a recomputed provenance hash) and
  replace the stored record, so the caller's previously-returned record is
  never mutated and transitions produce a new version.

`src/eigencapital/research/experiments/repository.py`:

- `save()` refuses to overwrite an existing record that is frozen or
  finalized (`status in {COMPLETED, CANDIDATE, REJECTED}` or
  `test_frozen=True`) → `ExperimentError`.
- `delete()` refuses to delete a frozen or finalized experiment →
  `ExperimentError`.
- Unfrozen (`PRE_REGISTERED`/`RUNNING`) records may still be created and
  overwritten, preserving the ability to iterate before finalization.

Supersession is expressed through `parent_experiment_id` lineage. A formal
promotion checklist (research → production) is documented as out of scope for
this programme; no research record is promoted into the live path.

## 3. Files changed

- `src/eigencapital/research/experiments/registry.py`
- `src/eigencapital/research/experiments/repository.py`
- `tests/unit/research/experiments/test_registry.py`

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/research/experiments/test_registry.py -q` | **29 passed** |
| `pytest tests/unit/research -q` | **791 passed** |

New coverage: frozen record rejects assignment; `to_dict` returns copies;
registry transitions return new records (original unchanged); save allows
overwrite of unfrozen but refuses frozen; delete allows unfrozen but refuses
frozen/finalized.

## 5. What this does not establish

- Hash verification on `repository.load()` is part of F-10 (research
  provenance), which is blocked on the missing raw artifact matrix; it is
  not yet wired here.
- A formal promotion/supersession workflow with sign-off is out of scope.
- Independent review has not occurred.

## 6. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
