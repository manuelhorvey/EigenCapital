# EC-AUDIT Remediation — Status Report 001

**Status:** `UNITS 0–3 COMPLETE — UNITS 4–7 NOT AUTHORIZED / NOT STARTED`
**Branch:** `audit/ec-remediation-001`
**Base:** `9efb1c9`
**Date:** 2026-10-31
**Scope:** offline, evidence-only remediation. No production code changed, no
live broker contacted, no credentials used.

---

## 1. Authorized scope

Only **Unit 2 (EC-AUDIT-002)** and **Unit 3 (EC-AUDIT-004)** were explicitly
authorized after Unit 1. Units 4–7 were not authorized and were not started.

| Unit | Audit | State |
|---|---|---|
| 0 | Preflight | complete |
| 1 | EC-AUDIT-001 — R4 signal identity | complete (`40382f8`) |
| 2 | EC-AUDIT-002 — stop-loss policy | complete (`8d0e102`) |
| 3 | EC-AUDIT-004 — test attestation | complete (this commit) |
| 4–7 | — | **not authorized, not started** |

---

## 2. Unit 1 — R4 signal identity (`40382f8`)

- Added `tests/unit/test_r4_signal_fidelity.py` (11 tests) pinning the live
  R4 signal against an independent golden vector derived from the documented
  formula, with mutation checks.
- Corrected `docs/DOCUMENTATION_SOURCE_OF_TRUTH.md` and
  `docs/architecture/CONFIGURATION_INVENTORY.md`.
- Established that the live divisor is `signal_vol_scale_reference = 0.50`
  (loop `compute_r4_signal`), while `vol_target_annual = 0.10` is declared but
  never consumed.
- Provenance corrected: `vol_target_annual` entered `r4_manifest.py` at
  `f5982e7` and `config.py` at `a26499f`; `d51eacb` did not introduce it.
- Decision record `reports/audits/EC_AUDIT_001_R4_IDENTITY_DECISION_RECORD.md`:
  `APPROVED — ALTERNATIVE A`, owner role = repository owner, 2026-10-31.

---

## 3. Unit 2 — Stop-loss policy verification (`8d0e102`)

- Added `tests/unit/live/test_stop_loss_policy.py`: **14 passed, 3 xfailed**
  (strict xfails for the invalid-SL gap).
- Verified the real policy flag is `require_sl_on_positions` (not
  `stop_loss_required`); production value is `false`.
- Verified Gate 6 (`RiskEnforcer._check_position_protection`) emits
  `CRITICAL` / `BlockReason.NO_SL_PROTECTION`; it does not early-exit the
  pipeline, but the loop halts new entries on any `CRITICAL`.
- Corrected row 13 of `docs/production/FAILURE_RECOVERY_MATRIX.md`.
- Recorded `reports/audits/EC_AUDIT_002_STOP_LOSS_POLICY_VERIFICATION.md`.

### Residual gap R-002-A (documented, not fixed)

`_check_position_protection` uses `p.get("sl", 0) == 0`. When the policy
requires a stop, a `None`, negative, or non-numeric SL is treated as
*protected*. Dormant in production because `require_sl_on_positions = false`.
Fixing it requires separate authorization.

---

## 4. Unit 3 — Test attestation

`reports/audits/EC_AUDIT_004_TEST_ATTESTATION.md` records the exact commands,
environment, and counts at tested commit `8d0e102`:

- Safety-critical: **501 passed, 3 xfailed**.
- Relevant regression: **308 passed, 1 skipped, 3 xfailed**.
- Full suite (segmented): **3587 + 29 + 10 = 3626 passed, 2 skipped, 3 xfailed**
  across 3631 collected tests; 0 collection errors.
- Static: ruff lint pass, ruff format pass (540 files), mypy pass (310 files),
  `git diff --check` pass.
- The monolithic `pytest tests/` run did **not** complete (operator-aborted
  twice) and is **not** claimed as a pass.
- One pre-existing Hypothesis wall-clock deadline flake
  (`test_correlation_chains_are_complete`) passes in isolation and in the
  property-only run.

---

## 5. Open items / risks

| ID | Item | Severity | State |
|---|---|---|---|
| R-002-A | Invalid SL (`None`/negative/non-numeric) treated as protected when policy requires | Medium (dormant) | documented, not fixed |
| — | Production `require_sl_on_positions = false` | Policy decision | unchanged |
| — | `vol_target_annual` declared but unused | Low | identity approved (Alt. A) |
| — | Property-test timing flake under load | Low | documented |
| — | Coverage gate (`fail_under=80`) not run in attestation | Info | not run |

---

## 6. Constraints honored

- No production code modified; only tests, docs, and audit reports.
- No live broker, credentials, or production state touched.
- Pre-existing stash `stash@{0}` preserved; no destructive git operations.
- No commit/amend/push beyond the explicitly authorized remediation commits.
