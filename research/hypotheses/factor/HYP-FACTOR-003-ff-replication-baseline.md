# HYP-FACTOR-003 — Fama-French Replication Baseline

```text
hypothesis_id:        HYP-FACTOR-003
title:                EigenCapital can replicate canonical factor constructions
                      (MKT, SMB, HML, MOM, RMW, CMA) on its own data pipeline to
                      within tolerance of published series
hypothesis_family:    factor
status:               UNVALIDATED
trial_group_default:  HYP-FACTOR-003/replication-tolerance-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 Fig 4.2; Ch 7)
```

## Claim

Not an alpha claim — an *infrastructure validation claim*: our data + feature +
portfolio layers reproduce published long-short factor returns closely enough
(correlation and tracking-error tolerances) that all other hypotheses' results
are trustworthy.

## Economic Rationale

Published factors are the field's shared ground truth; replication failures
indicate pipeline defects (survivorship, adjustment errors, timing bugs) that
would silently corrupt every in-house result.

## Expected Mechanism

Construct factors per published recipes on EigenCapital data; compare to
published series (or to each other across data vendors): correlation > 0.9,
annualized tracking error within declared tolerance.

## Universe

Per recipe (e.g., size/value breakpoints on the full historical universe with
delisted names included).

## Required Data

Full point-in-time equity universe incl. delistings; fundamentals; risk-free
rate; benchmark series.

## Candidate Features

Standard factor construction formulas as published.

## Candidate Parameters (declares trial search space)

- breakpoint scheme: {NYSE-only, full-universe}
- weighting: {value-weight, equal-weight}
- vendor comparison: {single, dual}

## Expected Failure Modes

- Survivorship bias inflating SMB/HML legs
- Corporate-action adjustment errors distorting momentum most (it is
  return-level sensitive)
- Universe membership drift

## Falsification Criteria

Reject (and block Phase-1G sign-off) if ANY of:
- Correlation with reference series < threshold under declared tolerances
- Systematic bias (one-sided tracking error) indicating a pipeline bug
- Momentum factor unreproducible while others pass (adjustment bug signature)

## Transaction Cost Sensitivity

N/A (measurement hypothesis, not a trading rule). No live deployment intended.

## Capacity Considerations

N/A.

## Notes

This is the gate hypothesis for the whole library: it validates the measuring
instrument before any instrument reading is trusted.
