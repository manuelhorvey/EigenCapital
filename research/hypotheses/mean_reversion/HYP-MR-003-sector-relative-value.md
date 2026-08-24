# HYP-MR-003 — Sector-Relative Value Spreads

```text
hypothesis_id:        HYP-MR-003
title:                Within-sector valuation spreads mean-revert: cheap-vs-expensive
                      sector peers converge over 6-18 months
hypothesis_family:    mean_reversion
status:               UNVALIDATED
trial_group_default:  HYP-MR-003/metric-horizon-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 value + group ops)
```

## Claim

Within each sector, assets cheap on valuation multiples relative to sector peers
outperform expensive peers over 6-18 months — value operates conditionally on
comparables, not just market-wide.

## Economic Rationale

Mispricing arises from herding into sector narratives; arbitrage is easiest
against close substitutes (sector peers), so convergence is strongest within
groups. Sector-relative framing strips the sector-level beta that contaminates
raw value tilts.

## Expected Mechanism

Long cheap-quintile / short expensive-quintile within each sector; spread
converges as narrative premiums decay; stronger post-narrative-bust periods.

## Universe

Equities with sector classification history (point-in-time GICS or equivalent).

## Required Data

Adjusted prices; fundamentals (book value, earnings, EBITDA, cash flow);
historical sector membership.

## Candidate Features

- E/B, EBITDA/EV, FCF/P sector z-scores
- Composite rank across metrics

## Candidate Parameters (declares trial search space)

- metric set: {single, composite}
- bucket: {quintile}
- holding: {126, 252, 378} days

## Expected Failure Modes

- Value traps: cheapness reflecting deteriorating quality (interaction with
  HYP-CS-001 quality tilt must be examined, not assumed away)
- Long drawdowns while spread widens before converging
- Sector classification restatements breaking point-in-time discipline

## Falsification Criteria

Reject if ANY of:
- Within-sector long-short Sharpe CI includes 0 after baseline costs
- Effect fully absorbed by adding quality controls without residual increment
- Non-monotone across metric buckets

## Transaction Cost Sensitivity

Low-moderate (slow signal). Favorable.

## Capacity Considerations

Moderate-high; constrained by expensive-leg borrow availability.
