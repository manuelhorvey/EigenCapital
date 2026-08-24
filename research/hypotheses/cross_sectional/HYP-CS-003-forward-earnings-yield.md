# HYP-CS-003 — Forward Earnings Yield

```text
hypothesis_id:        HYP-CS-003
title:                Trailing and forward earnings yields positively predict
                      cross-sectional returns, with forward yield dominant when
                      estimates are reliable
hypothesis_family:    cross_sectional
status:               UNVALIDATED
trial_group_default:  HYP-CS-003/yield-variant-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 value table)
```

## Claim

Assets cheap on earnings (high E/P; higher still on forward E/P) outperform
expensive assets over 6-18 months.

## Economic Rationale

Classic value premium: prices temporarily depart from fundamental value through
overreaction/herding; convergence compensates the patient. Forward variants add
information about earnings trajectory that trailing multiples miss.

## Expected Mechanism

Quintile sorts on E/P variants show monotonic spreads; forward E/P improves
separation in coverage-rich universes; both degrade in recessions as trailing
earnings go stale.

## Universe

Profitable equities only (E/P undefined/negative for loss-makers — exclusion
documented); sector-relative variant per HYP-MR-003 machinery available.

## Required Data

Trailing + consensus-forward EPS (point-in-time), adjusted prices.

## Candidate Features

- `eps_ttm / price`
- `eps_fwd_12m / price` (consensus)
- Sector-relative z-scores of both

## Candidate Parameters (declares trial search space)

- variant: {trailing, forward, composite}
- holding: {126, 252} days

## Expected Failure Modes

- Value-trap concentration in structurally declining industries
- Estimate staleness/revision noise in forward variants
- Deep-value leg dominated by low-quality names (quality interaction again)

## Falsification Criteria

Reject if ANY of:
- Spread CI includes 0 after costs out-of-sample
- Forward variant fails to improve on trailing where coverage is sufficient
  (its specific claim)
- Non-monotone across quintiles

## Transaction Cost Sensitivity

Low-moderate.

## Capacity Considerations

Moderate-high.
