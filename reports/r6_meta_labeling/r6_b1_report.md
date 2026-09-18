# R6-B1 — Preregistered Vol-Cap Filter (OBSERVED report)

**Experiment:** R6-B1 preregistered vol-cap deterministic filter (meta-labeling baseline 1)  
**Contract:** `docs/research/R6_META_LABELING.md (R6-A contract + B1 preregistration §5)` — preregistered before any conditional label rate  
**Run:** 2026-09-17T23:42:44.641230+00:00 · CI via moving-block bootstrap (block 20, seed 42, n=1000)  
**Filter:** `take iff vol_scale < 1.0 (vol60 < VOL_SCALE_REFERENCE = 0.50); skip iff vol_scale == 1.0`

> **What this is:** a filter-quality measurement of a deterministic,
> parameter-free meta-labeling baseline against its preregistered
> success criterion.
> **What this is NOT:** a strategy verdict, a take/skip production
> decision, or a forecast. The R5 681/630 label split is an instrument
> property and is never quoted as baseline accuracy.

## Pre-execution checks

- feature availability failures: 0
- weights-identity failures (re-derived vs replica, exact): 0
- event↔round-trip correspondence: 1311 events / 1311 entry fills / 1311 round-trips → OK
- labels: 1311 labeled, 0 excluded
- WF fit: 1311 events vs 1010 geometry → OK

## Result

- taken (uncapped): **1311** events, favorable rate 0.5195
- skipped (vol-capped): **0** events, favorable rate None
- rate difference: **None**
- 90% block-bootstrap CI: [None, None]

## Verdict: **INCONCLUSIVE**

> missing evidence (empty filter class or unformable resample) — INCONCLUSIVE, never promoted to a pass.

## WF OOS slices (descriptive only)

| window | OOS events | taken | skipped | rate diff |
|---|---|---|---|---|
| 1 | 250 | 250 | 0 | n/a |
| 2 | 250 | 250 | 0 | n/a |
| 3 | 250 | 250 | 0 | n/a |
| 4 | 250 | 250 | 0 | n/a |
| 5 | 250 | 250 | 0 | n/a |
| 6 | 250 | 250 | 0 | n/a |
| 7 | 250 | 250 | 0 | n/a |
| 8 | 250 | 250 | 0 | n/a |
| 9 | 250 | 250 | 0 | n/a |
| 10 | 171 | 171 | 0 | n/a |

## Interpretation guards (frozen)

- One preregistered trial slot (R6-B1) consumed; B2 (logistic
  regression) is a separate slot gated on this design, and B3+ (more
  complex ML) stays banned absent demonstrated B2 incremental value.
- Success here does NOT promote anything: the branch bar is
  incremental OOS utility over take-every-event R4 after costs
  (contract item 6, evaluated at B2).
- Failure or INCONCLUSIVE feeds the branch-rejection criteria
  (contract item 7) — no filter tuning, no feature additions.
- Research-only: R4 production untouched.

*Artifacts: r6_b1_report.json in reports/r6_meta_labeling/.*
