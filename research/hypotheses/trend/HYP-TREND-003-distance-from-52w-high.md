# HYP-TREND-003 — Distance From 52-Week High

```text
hypothesis_id:        HYP-TREND-003
title:                Proximity to the 52-week high predicts continuation; distance
                      below it predicts underperformance
hypothesis_family:    trend
status:               UNVALIDATED
trial_group_default:  HYP-TREND-003/window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4; anchored
                      anchoring/52w-high literature, George & Hwang 2004)
```

## Claim

The percent distance between current price and its trailing 52-week high is a
negative predictor of next-period returns: near-high assets continue,
far-below-high assets lag.

## Economic Rationale

Anchoring bias: investors reference the salient 52-week high, underreact to good
news near the anchor (reluctance to bid through it) and dispose of winners
further below it. The anchor, not the return path, mediates the effect.

## Expected Mechanism

Cross-sectional spread: top-quintile proximity outperforms bottom quintile;
effect should survive controls for raw momentum (it is an anchor effect, not a
return effect).

## Universe

Equities with ≥ 252 trading days of history; excludes IPOs inside the window.

## Required Data

Daily adjusted closes.

## Candidate Features

- `close / max(close, 252d) - 1`
- Rank-normalized version
- Days-since-52w-high as auxiliary

## Candidate Parameters (declares trial search space)

- window: {189, 252, 315} days
- weighting: {equal, rank}

## Expected Failure Modes

- Redundancy with 12-1 momentum (correlated but mechanistically distinct —
  testable via double-sort)
- Breakdown in crash regimes where "near high" is empty set-wide

## Falsification Criteria

Reject if ANY of:
- Long-short proximity spread IC t-stat < 2.0 out-of-sample
- Effect vanishes in double-sort controlling for momentum level
- Not robust across the declared window range

## Transaction Cost Sensitivity

Low-moderate: signal changes slowly (anchor moves rarely). Favorable turnover
profile.

## Capacity Considerations

Comparable to other equity tilts; no special constraints.
