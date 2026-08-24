# HYP-SA-002 — Johansen Multi-Asset Cointegration

```text
hypothesis_id:        HYP-SA-002
title:                Johansen's likelihood-ratio framework extends tradeable
                      mean-reversion beyond pairs to small baskets (k = 3-5)
hypothesis_family:    statistical_arbitrage
status:               UNVALIDATED
trial_group_default:  HYP-SA-002/rank-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 9 cointegration tests)
```

## Claim

Baskets whose VECM rank structure (Johansen trace/max-eigen tests) indicates r
cointegrating relations support basket-level spread trades with positive net
expectancy out-of-sample, generalizing HYP-SA-001.

## Economic Rationale

Same shared-driver logic as pairs, but baskets diversify idiosyncratic noise of
single legs and exploit multi-asset structural links (sector ETF vs constituents,
cross-listed complexes).

## Expected Mechanism

Cointegrating vector from Johansen defines basket weights; residual spread
traded as OU process with entry/exit thresholds; breadth across many baskets is
the edge carrier.

## Universe

Small same-sector baskets with documented economic linkage.

## Required Data

Adjusted prices for all legs; sector membership history.

## Candidate Features

- Trace / max-eigen statistics at ranks {1, 2}
- Residual half-life filter

## Candidate Parameters (declares trial search space)

- basket size: {3, 4, 5}
- estimation window: {252, 504}
- entry/exit z: {(2.0, 0.5), (2.5, 1.0)}

## Expected Failure Modes

- Rank-test overfitting in finite samples (size distortion of the tests)
- Weight instability → rebalancing churn
- Compounding leg-count × cost burden

## Falsification Criteria

Reject if ANY of:
- Basket portfolio fails to beat cost-adjusted zero out-of-sample
- No improvement over pair-based HYP-SA-001 on comparable risk (its specific claim)
- Rank selections unstable across adjacent windows

## Transaction Cost Sensitivity

High — worse than pairs by construction (more legs per unit of signal).

## Capacity Considerations

Low-moderate.
