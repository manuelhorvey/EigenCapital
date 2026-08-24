# HYP-TREND-002 — Price Acceleration

```text
hypothesis_id:        HYP-TREND-002
title:                The change in the volatility-adjusted price trend slope
                      (acceleration) predicts short-horizon outperformance
hypothesis_family:    trend
status:               UNVALIDATED
trial_group_default:  HYP-TREND-002/slope-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 factor table)
```

## Claim

Assets whose volatility-adjusted trend slope is *increasing* (second derivative
positive) outperform assets with flat or decelerating trends over the following
month, beyond what trend level alone predicts.

## Economic Rationale

Acceleration proxies the arrival rate of positive information exceeding the
market's absorption speed — a direct observable of underreaction dynamics.
Level-of-trend captures past drift; acceleration captures its change, i.e.,
fresh diffusion still in progress.

## Expected Mechanism

Slope computed by OLS of log price on time over a long window (≈1y) vs short
window (≈3m); their difference, normalized by realized vol, ranks assets. Top
decelerile should underperform top accelerators even at equal trend level
(testable via double-sort on level).

## Universe

Liquid equities or futures; same point-in-time adjustments as HYP-TREND-001.

## Required Data

Daily adjusted closes; realized vol series.

## Candidate Features

- `slope_long - slope_short`, vol-normalized
- Rank of acceleration within universe

## Candidate Parameters (declares trial search space)

- long window: {189, 252} days
- short window: {42, 63} days
- horizon: {21} days

## Expected Failure Modes

- Noise amplification: second differences are noisier than levels; may require
  smoothing (candidate: Kalman filter per extraction doc)
- Redundancy with momentum: if orthogonalized alpha ≈ 0, reject as non-incremental

## Falsification Criteria

Reject if ANY of:
- No significant increment over trend-level control in double-sort (the
  hypothesis claims *increment*, not existence)
- IC unstable across folds (sign flips)
- Edge consumed by costs at `baseline` cost model

## Transaction Cost Sensitivity

Higher than HYP-TREND-001: faster signal movement. Turnover analysis mandatory
(rank autocorrelation reported alongside every result).

## Capacity Considerations

Moderate; same bounds as trend family generally.
