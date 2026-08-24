# HYP-MR-001 — Short-Term Reversal (1-Month)

```text
hypothesis_id:        HYP-MR-001
title:                Assets with the worst prior-month returns outperform the best
                      prior-month performers over the next month (cross-sectional
                      reversal)
hypothesis_family:    mean_reversion
status:               UNVALIDATED
trial_group_default:  HYP-MR-001/window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 short-term reversal)
```

## Claim

At ~1 month horizon, cross-sectional returns reverse: past losers beat past
winners. This is the mirror of momentum at shorter horizon and is claimed as a
liquidity-compensation effect, not a contradiction of HYP-MOM-001.

## Economic Rationale

Short-horizon reversal compensates liquidity providers for absorbing
non-informational order flow; bid-ask bounce and price impact mechanically
induce negative autocorrelation that persists until flow normalizes.

## Expected Mechanism

Negative serial covariance at monthly frequency concentrated in illiquid names
and high-turnover periods; should weaken or vanish in the most liquid decile.

## Universe

Broad equities; liquidity stratification mandatory (the claim is
liquidity-linked and must be tested within strata).

## Required Data

Adjusted daily prices; volume/turnover for stratification.

## Candidate Features

- Prior 21-day return rank (inverted)
- Liquidity-stratified variant

## Candidate Parameters (declares trial search space)

- window: {5, 10, 21} days
- rebalance: {5, 21} days

## Expected Failure Modes

- Gross edge consumed by turnover (reversal signals churn fast)
- Microstructure artifacts if unadjusted prices used
- Regime dependence around crises (reversal strengthens — good) vs momentum
  bursts (bad)

## Falsification Criteria

Reject if ANY of:
- Post-cost spread CI includes zero under baseline costs
- Effect absent within the most-liquid stratum AND present only there gross
  (would indicate pure microstructure artifact rather than tradeable premium)

## Transaction Cost Sensitivity

Severe — highest-cost hypothesis in the library. Cost stress tests are
mandatory, not optional.

## Capacity Considerations

Low; execution overlay framing preferred.
