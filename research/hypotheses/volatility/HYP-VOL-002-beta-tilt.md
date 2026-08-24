# HYP-VOL-002 — Beta-Constrained Tilt (BAB-Lite)

```text
hypothesis_id:        HYP-VOL-002
title:                A beta-weighted long-low-beta / short-high-beta portfolio earns
                      positive alpha unexplained by market exposure
hypothesis_family:    volatility
status:               UNVALIDATED
trial_group_default:  HYP-VOL-002/beta-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 low-risk anomaly;
                      Frazzini-Pedersen leverage-constraint channel)
```

## Claim

Betting-against-beta style spreads earn positive risk-adjusted returns because
leverage-constrained investors overweight high-beta assets.

## Economic Rationale

Constraint-driven demand: investors limited in leverage reach for return via
high-beta names, depressing their future returns; unconstrained capital can
harvest the spread by leveraging the low-beta leg.

## Expected Mechanism

Alpha of beta-sorted spread after controlling for market beta = 0 exposure;
strongest where funding constraints bind most (retail-heavy universes).

## Universe

Broad equities; requires borrow feasibility assessment for high-beta leg.

## Required Data

Adjusted prices; benchmark series for beta estimation.

## Candidate Features

- Trailing 252d beta vs benchmark
- Shrunk beta (Blume adjustment) variant to counter estimation error

## Candidate Parameters (declares trial search space)

- window: {252}
- buckets: {quintile}
- leverage scheme: {beta-neutral, vol-neutral}

## Expected Failure Modes

- Beta estimation noise dominates sorting at short windows
- Funding cost of leveraging low-vol leg ignored → phantom edge
- Crisis behavior: both legs' correlation → 1

## Falsification Criteria

Reject if ANY of:
- Spread alpha CI includes 0 after explicit funding-cost modeling
- Effect vanishes under shrinkage-corrected betas (estimation artifact)
- Crisis-period drawdown breaches portfolio-layer constraints

## Transaction Cost Sensitivity

Low-moderate; funding costs dominate transaction costs here.

## Capacity Considerations

High on the long leg; borrow-dependent on the short leg.
