# HYP-MOM-003 — Analyst Revision Breadth

```text
hypothesis_id:        HYP-MOM-003
title:                Net analyst earnings-revision breadth (up minus down revisions)
                      positively predicts next-quarter relative performance
hypothesis_family:    momentum
status:               UNVALIDATED
trial_group_default:  HYP-MOM-003/revision-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 sentiment table)
```

## Claim

The difference between upward and downward earnings-estimate revisions, as a
share of total revisions over the trailing quarter, predicts positive forward
returns.

## Economic Rationale

Slow diffusion of fundamental information through the analyst coverage channel:
revisions cluster as analysts anchor on prior forecasts; the market underreacts
to the information content embedded in systematic revision direction.

## Expected Mechanism

Breadth signal leads fundamentals with a lag; effect concentrates around and
after earnings announcements; decays within one to two quarters.

## Universe

Equities with active analyst coverage; coverage count itself recorded (signal
undefined for zero-coverage names — exclusion documented, not silent).

## Required Data

- Historical consensus estimates and revisions (point-in-time! vendor timestamps
  adjusted to publication per DATA_CONTRACT — this hypothesis is unusually
  look-ahead-prone)
- Prices for evaluation

## Candidate Features

- `(up_revisions - down_revisions) / total_revisions` over {21, 63} days
- Revision magnitude-weighted variant

## Candidate Parameters (declares trial search space)

- window: {21, 63} days
- min coverage: {3, 5} analysts

## Expected Failure Modes

- Point-in-time violations from vendor backfilled timestamps (top risk)
- Coverage bias correlates with size/value exposures
- Signal crowded among institutional flows

## Falsification Criteria

Reject if ANY of:
- Effect disappears when estimates are lagged to conservative publication dates
- IC t-stat < 2.0 out-of-sample after baseline costs
- Returns fully explained by size/value/momentum controls (no increment)

## Transaction Cost Sensitivity

Moderate-high: quarterly-ish refresh but event-clustered turnover.

## Capacity Considerations

Limited by coverage universe; mid/large-cap biased. Document explicitly.
