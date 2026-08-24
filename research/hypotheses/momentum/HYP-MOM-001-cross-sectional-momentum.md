# HYP-MOM-001 — Cross-Sectional Momentum Deciles

```text
hypothesis_id:        HYP-MOM-001
title:                Ranking assets by prior 12-1 month return yields monotonic
                      forward-return spreads across deciles (winner-minus-loser > 0)
hypothesis_family:     momentum
status:               UNVALIDATED
trial_group_default:  HYP-MOM-001/decile-skip-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4; Fama-French WML)
```

## Claim

The cross-sectional winner-minus-loser (WML) spread — top vs bottom tercile/decile
of 12-1 returns — earns positive risk-adjusted returns net of costs.

## Economic Rationale

Behavioral under-/over-reaction operating cross-sectionally: capital flows chase
recent relative winners; institutional mandates and attention biases delay
arbitrage. Distinct from HYP-TREND-001's claim: this is relative (market-neutral
by construction), not directional per asset.

## Expected Mechanism

Decile portfolios formed monthly on trailing 12-1 return; spread return of top
minus bottom decile should be positive with t-stat ≥ 3 historically in-sample,
≥ 2 required out-of-sample here.

## Universe

Broad equity universe with historical membership tracking; sector balance checked.

## Required Data

Adjusted daily prices; index membership history for survivorship-safe universes.

## Candidate Features

- 12-1 return rank
- Sector-neutralized rank (group demeaning)

## Candidate Parameters (declares trial search space)

- formation: {126, 252} days, skip {0, 21}
- buckets: {5, 10}
- rebalance: {21} days

## Expected Failure Modes

- Momentum crashes (sharp negative skew of loser leg rebounds in crises)
- Crowding/post-publication decay
- Small-cap illiquidity inflating gross but not net spread

## Falsification Criteria

Reject if ANY of:
- Out-of-sample WML Sharpe CI includes 0 after baseline costs
- Monotonicity across buckets absent
- Skew/drawdown profile violates portfolio-layer risk limits even pre-sizing

## Transaction Cost Sensitivity

High: monthly full-decile rebalance of both legs. Turnover-adjusted edge is the
honest metric; report rank autocorrelation and mean turnover with every result.

## Capacity Considerations

Large-cap implementation feasible; small-cap legs capacity-limited.
