# HYP-SA-001 — Cointegration Pairs (Engle-Granger)

```text
hypothesis_id:        HYP-SA-001
title:               Pairs selected by Engle-Granger cointegration on a training
                      window exhibit mean-reverting spreads tradeable out-of-sample
hypothesis_family:    statistical_arbitrage
status:               UNVALIDATED
trial_group_default:  HYP-SA-001/pair-selection-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 9 stat-arb section)
```

## Claim

Log-price pairs that cointegrate in-sample (EG two-step: unit-root residual of
OLS hedge) continue to mean-revert enough, after costs, to fund a spread-trading
rule out-of-sample.

## Economic Rationale

Pairs share common risk drivers (same industry, same underlying commodity,
cross-listings); the residual captures temporary idiosyncratic dislocations that
arbitrage capital closes. The *economic link*, not the statistical test alone,
must justify each pair.

## Expected Mechanism

Spread z-score exceeds entry threshold → position; reversion to exit threshold
→ close. Positive expectancy requires genuine shared trend, not spurious
correlation — hence selection discipline is part of the claim.

## Universe

Same-industry equity pairs with fundamental linkage documented per pair;
liquidity floor both legs.

## Required Data

Adjusted daily prices (both legs); sector membership history; borrow for short leg.

## Candidate Features

- EG residual ADF statistic (selection)
- Spread half-life via OU fit (tradeability filter)

## Candidate Parameters (declares trial search space)

- entry z: {2.0, 2.5, 3.0}; exit z: {0.5, 1.0}
- estimation window: {252, 504} days
- max half-life filter: {20, 40} days

## Expected Failure Modes

- Structural break: cointegration is regime-dependent; breaks destroy spreads
  (stop-loss mandatory; break detection part of design)
- Data-mined pairs without economic links fail first out-of-sample
- Short-leg borrow cost/callaway risk

## Falsification Criteria

Reject if ANY of:
- Portfolio of EG-selected pairs fails to beat cost-adjusted zero under purged
  walk-forward CV across multiple formation windows
- Performance concentrated in few lucky pairs rather than breadth (fundamental-law
  check)
- Half-life instability: selected pairs' half-lives non-stationary

## Transaction Cost Sensitivity

High: frequent round trips. Per-pair breakeven analysis mandatory.

## Capacity Considerations

Low-moderate; pair-level capacity = min(leg ADVs) × participation.
