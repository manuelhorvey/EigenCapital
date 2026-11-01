# EC-AUDIT-006 — Unit 5: Research Trial Ledger Provenance

**Status:** `PARTIALLY VERIFIED — IDENTITY/CONFIG/DATASET VERIFIED; RESULT ARTIFACT, CODE COMMIT, AND HASH REPRODUCIBILITY GAPS`
**Branch:** `audit/ec-remediation-001`
**Based on:** `84e7b2f` (Unit 4 HEAD)
**Date:** 2026-10-31
**Scope:** read-only verification. No trial record, report, or historical evidence was created, edited, or deleted.

---

## 1. Objective

Verify, for the persisted research trial ledger:

1. trial identity and registration;
2. timestamps;
3. source-data binding;
4. configuration binding;
5. result evidence;
6. lineage.

**Do not invent missing records and do not rewrite historical evidence.** Where
evidence is absent, it is recorded as a gap, not filled.

---

## 2. Surfaces inspected

| Surface | Path |
|---|---|
| Persisted experiment record | `research/experiments/registry/EXP-000002.json` |
| Registry / repository code | `src/eigencapital/research/experiments/{registry,repository}.py` |
| Execution ledger (in-memory) | `src/eigencapital/research/execution/ledger.py` |
| Provenance hashing | `src/eigencapital/core/provenance.py` |
| Trial metadata model | `src/eigencapital/core/models/trial_metadata.py` |
| Preregistration | `research/hypotheses/HYP-R4-REB-001-rebalance-frequency.md` |
| Result narrative | `docs/research/R4_REBALANCE_FREQUENCY.md` |
| Program trial-slot ledger | `reports/research_program/program_status.json` |
| Dataset manifest | `data/mt5/R5_data_manifest.json` |
| Intraday ledger | `docs/research/INTRADAY_RESEARCH_LEDGER.md` |

Only one persisted experiment record exists: **EXP-000002**. There is no
persisted `ExecutionLedger` file anywhere in the tree.

---

## 3. Verified

### 3.1 Identity and registration — VERIFIED (internally consistent)

- `EXP-000002` parses as a valid `ExperimentRecord`.
- `hypothesis_id = HYP-R4-REB-001`; the preregistration exists at
  `research/hypotheses/HYP-R4-REB-001-rebalance-frequency.md`.
- `trial_metadata` validates as `TrialMetadata`:
  - `trial_group_id = R4-REB-MATRIX-V1`
  - `trial_index = 1`
  - `trials_in_family = 8`
  - `hypothesis_family = rebalance_frequency`
  - `selection_method = pre_registered_matrix_no_search`
- The preregistration declares exactly **8 trials** in one family, matching
  `trials_in_family = 8`.
- `status = COMPLETED`, `test_frozen = true`, `rejection_reason = ""`.

### 3.2 Configuration binding — VERIFIED

- `strategy_config_hash = aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`
  equals the current `R4ConfigManifest().compute_identity()` exactly.
- `strategy_version = R4.0`, `strategy_id = risk_conditioned_continuation`.

### 3.3 Source-data binding — VERIFIED (indirect chain)

- `dataset_hash = 563812796b6d12a95648d27405113515934d1ff0dd6c4eb371fcfaf0704e26c6`
  equals `sha256(data/mt5/R5_data_manifest.json)` exactly.
- The manifest itself verifies:
  - 38/38 `per_file_prefixes` match the current `data/mt5/*_D1.csv` files;
  - recomputed `combined_sha256` = `3d10cf9322bda6cd9f5d4966a53e4d8d3a6563a748cb25e685bdf54157b898f1`
    equals the frozen value.
- Therefore the chain is:
  `EXP-000002.dataset_hash → sha256(manifest file) → manifest.combined_sha256 → 38 CSVs`.
- **Caveat:** `dataset_hash` is the *manifest file* hash, not the dataset
  `combined_sha256`. The field name is broader than its content. The binding is
  valid but indirect.

### 3.4 Provenance hash — REPRODUCIBLE ONLY VIA LIFECYCLE RECONSTRUCTION

- Stored completion hash:
  `1b81b107a4d512f2f6f26a3872e6000e064004fccedc93299dd3e7ee4f6e8a31`.
- Recomputing the hash from the **final on-disk record** yields
  `fbb485e28e24f1059aa1b9d94f12c7c6885dc3e41f896e0d542ab3ea519f7c14` — **mismatch**.
- The mismatch is explained, not concealed:
  - The registry computes `provenance_hash` over `to_dict()`, which **includes
    the previous `provenance_hash`** (self-referential).
  - The pre-completion freeze hash `6aa75f42...` reproduces exactly from a
    reconstructed `PRE_REGISTERED` record.
  - The stored completion hash reproduces exactly when the input is the final
    record with `provenance_hash` set to the freeze hash, `created_at =
    "2026-09-16"`, `updated_at = ""`, `status = "COMPLETED"`, and the final
    `result` block.
  - `updated_at` was written **after** the hash was computed, so it is not
    covered by the hash.
- **Conclusion:** the record was not fabricated; the hash is internally
  consistent with the registry algorithm at completion time, but it is **not
  independently verifiable from the artifact alone**. A verifier must
  reconstruct the lifecycle state, and `updated_at` can change without
  detection.

### 3.5 Timestamps

- `created_at = "2026-09-16"` — date only, no time or timezone.
- `updated_at = "2026-09-16T06:21:14.808375+00:00"` — full ISO-8601 UTC.
- `updated_at` post-dates the completion hash (see 3.4).

---

## 4. Gaps (recorded, not filled)

| ID | Gap | Evidence |
|---|---|---|
| G-5-1 | **Result report absent.** `result.report_path = reports/r4_rebalance_research/rebalance_report_20260916_052051.json` does not exist; `report_sha256` cannot be verified. | `find` returns no `rebalance_report*` anywhere |
| G-5-2 | **Code commit unresolvable.** `git_commit = fda24682d38f96f2083e1ce74e6d3cac7dc3bdbb` is not an object in this repository. | `git cat-file -t` → "could not get object info" |
| G-5-3 | **Provenance hash not independently verifiable** (self-referential; `updated_at` outside hash). | Section 3.4 |
| G-5-4 | **`strategy_artifact_hash` empty** — strategy implementation code is not hashed. | Record field `""` |
| G-5-5 | **Lineage is prose-only.** `parent_experiment_id = ""`; the link to EXP-000001 exists only in `docs/research/R4_REBALANCE_FREQUENCY.md`. | Record field `""`; prose reference |
| G-5-6 | **`created_at` lacks time/timezone.** | `"2026-09-16"` |
| G-5-7 | **Two disjoint trial-accounting surfaces.** `program_status.json` reports `slots_consumed = 6` (R2-B1, R3-B1, R4-B1, R4-B2, R5-B1, R6-B1) and does **not** include `R4-REB-MATRIX-V1` (8 trials). | Parsed program status |
| G-5-8 | **ExecutionLedger is in-memory only.** No persisted execution ledger exists; `scripts/audit/counterfactuals.py` expects `reports/r4_economics_audit/trial_ledger.json`, which is absent. | `ledger.py`; missing file |
| G-5-9 | **Repository contradicts "append-only".** `ExperimentRepository` exposes `save()` (overwrite) and `delete()`; only the in-memory `ExecutionLedger.append()` rejects duplicates. | `repository.py:37,65` |
| G-5-10 | **Symbol-count discrepancy.** `result.sample` says "42 symbols"; the bound manifest covers **38** instruments; production config lists **37** allowed symbols. Unresolved. | Record vs manifest vs config |

---

## 5. What this does and does not establish

**Establishes:**

- EXP-000002 is a real, schema-valid, frozen, completed record tied to a real
  preregistration and the frozen R4 configuration identity.
- The dataset snapshot it points to is byte-intact (38/38 prefixes and the
  combined hash match).
- The stored completion hash is reproducible by reconstructing the lifecycle
  state, so it is not arbitrary.

**Does not establish:**

- That the reported results are correct or reproducible: the result report is
  absent (G-5-1).
- That the code state at experiment start is known: the commit is unresolvable
  (G-5-2).
- That the record is tamper-evident: the hash is self-referential and excludes
  `updated_at` (G-5-3).
- That the whole research programme's multiple-testing count is complete: two
  ledgers are disjoint (G-5-7).

---

## 6. Recommendations (not implemented)

| ID | Recommendation | Owner unit |
|---|---|---|
| R-5-A | Persist a result-report copy (or a content-addressed artifact) alongside the registry record so `report_sha256` is verifiable | Unit 6 candidate |
| R-5-B | Make `provenance_hash` non-self-referential and exclude mutable fields (`updated_at`), then re-verify existing records without rewriting them | Unit 6 candidate |
| R-5-C | Record a resolvable code commit (or archive the tree) for each experiment | Unit 6 candidate |
| R-5-D | Populate `strategy_artifact_hash` with the strategy implementation hash | Unit 6 candidate |
| R-5-E | Encode `parent_experiment_id` for the EXP-000001 → EXP-000002 lineage | Unit 6 candidate |
| R-5-F | Reconcile the program trial-slot ledger with `R4-REB-MATRIX-V1`, or explicitly document the two-program boundary | governance |
| R-5-G | Make the "append-only" claim enforceable (remove `delete`, use content-addressed records) | Unit 6 candidate |

No recommendation was applied under Unit 5.

---

## 7. Conclusion

Trial identity, registration, configuration binding, and dataset integrity are
verified. The result artifact, the code commit, and independent hash
verifiability are **not** verified and are recorded as gaps G-5-1..G-5-10. No
missing record was invented and no historical evidence was rewritten. R-002-A
remains open.
