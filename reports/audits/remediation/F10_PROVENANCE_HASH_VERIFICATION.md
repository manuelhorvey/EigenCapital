# F-10 — Research Provenance Hash Verification on Load

**Status:** `VERIFIED WITH LIMITATIONS` (hash verification implemented; artifact restoration `BLOCKED` on raw matrix)
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `23552ad`
**Severity:** High · **Phase:** P1
**Date:** 2026-11-01

---

## 1. Finding

`ExperimentRepository.load()` never verified the stored `provenance_hash` — it read JSON and constructed a record, so tampered or corrupt research records could be silently loaded and treated as valid evidence. The finding also notes absent R1–R6 artifact directories and the unresolvable `git_commit fda2468`.

## 2. Correction

`src/eigencapital/research/experiments/repository.py`:

- `load()` now verifies the stored `provenance_hash` before returning a record, **fail closed**:
  - Missing hash → `ExperimentError` (refuse to load unverified record).
  - Mismatched hash → `ExperimentError` (record may be tampered/corrupt).
  - Malformed/non-dict JSON → `ExperimentError`.
  - Incomplete fields → `ExperimentError`.
- `save()` now always writes a valid `provenance_hash` before persisting (recomputed deterministically over all fields except the hash itself, mirroring `ExperimentRegistry.create()`), so anything saved through the repository is verifiable on load.
- `save()`/`delete()` use a raw JSON read for their immutability status check only (not provenance verification), so legacy mutable records remain overwritable/deletable; `load()` remains the verified public entry point.
- Added `_read_raw_json()` and `_verify_provenance_on_load()` helpers.

## 3. Files changed

- `src/eigencapital/research/experiments/repository.py`
- `tests/unit/research/experiments/test_registry.py` (7 new tests)

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/research/experiments/test_registry.py -q` | **36 passed** (29 pre-existing + 7 new) |
| `pytest tests/unit/research -q` | **798 passed** |
| Full suite `tests/unit tests/property tests/integration tests/failure_injection` | **3746 passed, 2 skipped** |

New coverage:
- Load verifies valid provenance hash.
- Load rejects tampered hash.
- Load rejects tampered data field.
- Load rejects missing hash.
- Load rejects malformed JSON.
- Load rejects non-dict JSON.
- Save writes a valid, recomputable provenance hash.

## 5. Limitations (noted, not hidden)

- **Hash verification cannot recreate missing historical evidence.** The R1–R6 artifact directories and the raw per-period return matrix for `EXP-000002` remain absent; a hash check only proves that stored content matches its recorded hash, not that absent evidence existed or was valid. Artifact restoration and the EXP-000002 hash verification remain **BLOCKED** on the raw matrix being made available.
- The dataset manifest (38 instruments) vs experiment claim (42) vs production allowance (37) discrepancy is not resolved by this change; it remains a separate data-governance issue.
- Historical research records saved before this change without a provenance hash will be rejected by `load()` (fail closed) — they must be regenerated through `registry.create()` / `save()` to obtain a verifiable hash.
- No historical experiment record was edited or restated.

## 6. What this does not establish

- Independent review has not occurred.
- Research verdicts are not re-derived; this only restores the integrity check on stored records.
- Capital-readiness decision unchanged.

## 7. Closure decision

`VERIFIED WITH LIMITATIONS`. Not `CLOSED`. Remaining: independent review; artifact restoration blocked on raw matrix.
