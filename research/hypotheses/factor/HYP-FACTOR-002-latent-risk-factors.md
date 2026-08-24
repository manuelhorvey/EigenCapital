# HYP-FACTOR-002 — Data-Driven Risk Factors as Controls

```text
hypothesis_id:        HYP-FACTOR-002
title:                A small set of PCA-extracted return components explains the
                      majority of cross-sectional variance and suffices as the risk
                      model for evaluating every other hypothesis in this library
hypothesis_family:    factor
status:               UNVALIDATED
trial_group_default:  HYP-FACTOR-002/component-count-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 13 PCA risk factors;
                      Ch 7 Fama-Macbeth complement)
```

## Claim

~10 principal components capture ≈ 60% of equity return variance; using them as
the risk-control regression in hypothesis evaluation yields the same alpha
verdicts as published factor controls — validating a fully in-house evaluation stack.

## Economic Rationale

Risk factors are latent drivers of co-movement; PCA recovers them without
labeling debates. If latent controls reproduce published-control verdicts, the
research engine is self-sufficient and immune to vendor factor discontinuities.

## Expected Mechanism

Scree "elbow" at low component count; alpha verdicts of HYP-CS/MOM/VOL families
under latent-factor controls match verdicts under FF-style controls on identical
folds.

## Universe

Broad equities with strict missingness/winsorization discipline.

## Required Data

Adjusted daily returns (universe-wide).

## Candidate Features

- Component scores per period; loadings matrix snapshot per window

## Candidate Parameters (declares trial search space)

- n_components: {5, 10, 15}
- window: {504} days

## Expected Failure Modes

- Latent factors absorb part of a genuine alpha (over-controlling) → false rejects
- Instability of component identity across windows complicates attribution
- Small-cap coverage gaps biasing the covariance estimate

## Falsification Criteria

Reject if ANY of:
- Explained-variance target unreachable on our data (pipeline quality issue)
- Verdict disagreement rate vs published-control arm above tolerance
- Loadings non-stationary enough to make attribution meaningless

## Transaction Cost Sensitivity

N/A (measurement/infrastructure hypothesis).

## Capacity Considerations

N/A.

## Notes

Second gate hypothesis alongside HYP-FACTOR-003: together they validate the
evaluation instrument from both directions (published + latent).
