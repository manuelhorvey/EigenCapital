# F-08 — PBO / CSCV Correction

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION` (re-derivation of affected research values is blocked)
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `6e707ca`
**Severity:** High · **Category:** statistics
**Date:** 2026-11-01

---

## 1. Finding

`compute_pbo` reported a structurally constant `PBO = 1.0`. With 12 candidate
summaries it returned `pbo=1.0, overfit_count=6, total_partitions=6`, and the
research record cites `PBO 1.000 (16/16)`.

## 2. Root cause

The implementation was not CSCV. It selected `best_is_idx` from the training
half and then checked whether that index appeared in the **disjoint** test
half:

```python
train = indices[:split]
test = indices[split:]
...
best_is_idx = train_is[0][0]
...
if best_is_idx not in [i for i, _ in test_oos[:...]]:
    overfit_count += 1
```

Because `train` and `test` are disjoint, `best_is_idx` can never appear in the
test ranking. The condition is always true, so `overfit_count ==
total_partitions` and `pbo == 1.0` for every input that passes the candidate
minimum. The value carries no information in either direction.

## 3. Correction

`compute_pbo` now implements Combinatorially Symmetric Cross-Validation:

- Split the performance history into an even number of contiguous blocks.
- Enumerate every combination of half the blocks as IS and the complement as
  OOS (deterministically capped by `n_partitions`).
- Compute a per-candidate statistic on each side (`sharpe` by default,
  `mean` supported).
- Select the IS-best candidate; compute its average OOS rank (1 = worst,
  N = best); form `omega = rank/(N+1)` and `logit = log(omega/(1-omega))`.
- Count the partition as overfit when `logit <= 0` (OOS rank at or below the
  median). `PBO = overfit_count / total_partitions`.

Inputs:

- `performance_matrix`: periods × candidates (preferred).
- `candidate_results` entries carrying a per-period `returns` series
  (convenience form).
- Summary-only `in_sample_sharpe` / `out_of_sample_sharpe` pairs can no longer
  produce a value: they return `method="UNSUPPORTED_INPUT"`,
  `sufficient_experiments=False`, and an explicit message. Feeding a single
  split to a cross-validation estimator was the original category error.

`PBOResult` gains `method` and `n_blocks`; existing fields are preserved.

## 4. Files changed

- `src/eigencapital/analytics/validation/pbo.py`
- `src/eigencapital/analytics/validation/validator.py` (type + docstring)
- `tests/unit/analytics/test_pbo.py`

## 5. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/analytics/test_pbo.py -q` | **18 passed** |
| `pytest tests/unit/analytics -q` | **191 passed** |
| `pytest tests/unit/analytics tests/unit/research -q` | **974 passed** |

Environment: Python 3.14.8, pytest 9.1.1.

Added coverage:

- Regression: the old always-1.0 case now returns `0.0` when the IS-best is
  also OOS-best.
- Known full-overfitting reversal case returns `1.0`.
- Default block selection, partition cap, determinism.
- Per-candidate return-series input matches the equivalent matrix.
- Ragged series/matrix, non-finite values, odd blocks, too many blocks, and
  unknown statistics fail closed.
- Summary-only input returns `UNSUPPORTED_INPUT` and no partition count.

**Full-suite verification is pending.** The post-F-08 CI-equivalent run
(`tests/unit tests/property tests/integration tests/failure_injection`) was
started twice and aborted by the operator; it is not claimed as passed for this
tree. The last complete run, `3662 passed, 2 skipped, 3 xfailed`, predates the
F-08 change.

## 6. Affected research values

The old implementation's output is invalid as a PBO estimate. Claims that
depend on it must be restated or withdrawn; none were edited in this commit.

| Location | Claim | Disposition |
|---|---|---|
| `docs/research/R3_PARAMETER_STABILITY.md` | `PBO 1.000 (16/16)` | **INVALID as PBO** — artifact of the fixed split. The descriptive observation "best-IS was worst-OOS in all 16 constructed partitions" may be retained only as a description of that non-CSCV construction, not as an overfitting probability. |
| `docs/research/RESEARCH_PROGRAM_STATUS.md` | R3 summary cites `PBO 1.000` | **Restatement required** |
| `reports/research_program/program_status.json` | `key_finding` / `evidence` cite `PBO 1.000` | **Restatement required** |

Re-derivation requires the raw per-period returns for the R3 grid candidates
(1,500 points). No such matrix is present under `reports/`; the only R3
artifacts are the narrative and `CAMPAIGN_R3_RESULTS.json`, which does not
carry a PBO matrix. Re-derivation is therefore **BLOCKED** on source data and
overlaps F-10 (missing artifacts). No replacement PBO value was invented.

## 7. What this does not establish

- No independent reviewer has verified the CSCV implementation.
- The corrected estimator has not been applied to R3/R4 research; existing
  PBO claims are not yet restated.
- Passing synthetic-matrix tests is not evidence that any strategy is not
  overfit.
- This change does not alter R4, risk limits, broker behaviour, or capital.

## 8. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`. Remaining:
independent review, full-suite run on the final tree, raw-data re-derivation
or formal withdrawal of the affected PBO claims.
