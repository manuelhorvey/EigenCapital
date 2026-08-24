# HYP-TREND-001 — Time-Series Momentum (12-1 Month)

```text
hypothesis_id:        HYP-TREND-001
title:                Assets with positive 12-month returns excluding the most
                      recent month continue to outperform over the next 1-3 months
hypothesis_family:    trend
status:               UNVALIDATED
trial_group_default:  HYP-TREND-001/lookback-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4; Jegadeesh & Titman 1993)
```

## Claim

An asset's own past 12-1 month return positively predicts its future 1-3 month
return, in a time-series (per-asset) sense, net of costs.

## Economic Rationale

Information diffuses gradually; investors underreact to news and then
extrapolate recent performance (Hong-Lim-Stein underreaction, Barberis-Shleifer-
Vishny extrapolation). Persistent supply/demand imbalances and hedging-flow
feedback (CPPI, stop-loss clustering, vol-target rebalancing) mechanically
reinforce trends.

## Expected Mechanism

Positive serial correlation in returns at 1-12 month lags, decaying with
horizon; effect should be stronger in assets with lower liquidity/slower
information diffusion and weaker after sharp reversals.

## Universe

Liquid continuous futures or top-decile-liquidity equities; must include
delisted names historically (survivorship discipline per DATA_CONTRACT).

## Required Data

- Daily adjusted OHLCV (sufficient history for rolling 252d lookback)
- Corporate-action adjustments applied point-in-time

## Candidate Features

- `ts_ret(t, 252) - ts_ret(t, 21)` (12-1 month return)
- Volatility-normalized variant: above divided by 252d realized vol
- Sign + magnitude of the normalized score

## Candidate Parameters (declares trial search space)

- lookback: {126, 189, 252} days
- skip: {0, 21} days
- holding period: {21, 63} days
- position scaling: {binary sign, vol-targeted}

## Expected Failure Modes

- Regime flip in high-volatility mean-reverting markets (crisis rebounds)
- Signal decay to zero post-publication era
- Overlap between "momentum crashes" and portfolio drawdown constraints
- Look-ahead via unadjusted split/dividend data

## Falsification Criteria

Reject if ANY of:
- Post-cost Sharpe of the long side fails to exceed buy-and-hold benchmark at
  95% confidence under purged walk-forward CV
- Monotonicity across lookback values is absent (edge is parameter luck)
- t-stat of mean IC < 2.0 across out-of-sample folds

## Transaction Cost Sensitivity

Moderate. Holding periods of 1-3 months imply low turnover; but stress-test at
baseline and extreme cost levels per RESEARCH_ENGINE_CONTRACT. Edge must survive
`stress`, not merely `optimistic`.

## Capacity Considerations

High capacity if implemented on liquid futures; equity implementation capacity
bounded by ADV participation limits of bottom-quintile-liquidity names.

## Notes

Trial family spans every lookback/skip/holding combination tested. Selection
from the grid MUST record `selection_method = best_validation_sharpe` and the
final `trials_in_family`.
