# HYP-VOL-001 — Low-Volatility Anomaly

```text
hypothesis_id:        HYP-VOL-001
title:                Bottom-volatility-quintile equities earn higher risk-adjusted
                      returns than high-volatility quintiles over long horizons
hypothesis_family:    volatility
status:               UNVALIDATED
trial_group_default:  HYP-VOL-001/vol-metric-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 volatility anomaly;
                      Ang et al. 2006)
```

## Claim

Realized low-volatility assets outperform high-volatility assets risk-adjusted —
the empirical inversion of CAPM's prediction — net of costs, over multi-year
horizons.

## Economic Rationale

Lottery preference (overpayment for skew/vol), representativeness bias, and
leverage constraints (rational agents cannot lever low-vol, so its premium
persists). Benchmark-driven managers prefer lottery-like names for tracking-error
reasons.

## Expected Mechanism

Monotonic decay of risk-adjusted returns across vol quintiles; asymmetry driven
mainly by the catastrophic tail of the high-vol leg rather than the low-vol leg's
alpha.

## Universe

Broad equities, ≥ 1y history for vol estimation; long-only framing admissible
(shorting high-vol has borrow/cost pathologies — document which framing tested).

## Required Data

Adjusted daily prices; borrow availability if short leg included.

## Candidate Features

- Trailing {63, 126, 252}-day realized vol rank
- Idiosyncratic vol vs market model variant

## Candidate Parameters (declares trial search space)

- window: {63, 126, 252}
- rebalance: {63} days
- long-only vs long-short

## Expected Failure Modes

- Rate-regime sensitivity (low-vol tilts are duration-like)
- Value/momentum exposure smuggled in via vol ranking correlations
- Crowding of the factor post-publication

## Falsification Criteria

Reject if ANY of:
- Long-low-vol Sharpe ≤ benchmark Sharpe out-of-sample
- Monotonicity absent across quintiles
- Effect fully explained by value+momentum controls (no increment)

## Transaction Cost Sensitivity

Low (slow signal) — one of the most cost-favorable candidates in the library.

## Capacity Considerations

High for long-only tilt implementation.
