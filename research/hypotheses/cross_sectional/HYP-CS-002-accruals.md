# HYP-CS-002 — Accruals (Earnings Quality, Negative)

```text
hypothesis_id:        HYP-CS-002
title:                High total accruals relative to assets predict negative abnormal
                      returns (earnings-management signal)
hypothesis_family:    cross_sectional
status:               UNVALIDATED
trial_group_default:  HYP-CS-002/accrual-definition-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 quality table;
                      Sloan-style accrual anomaly)
```

## Claim

Firms with high accruals (income far above cash flow) subsequently underperform:
accrual-heavy earnings are lower-quality and mean-revert.

## Economic Rationale

Accruals are the primary lever of earnings management and also proxy for
accounting estimates of growth; both interpretations imply overpriced earnings
that disappoint. The market underweights the reliability difference between
cash-backed and accrual-backed earnings.

## Expected Mechanism

Quintile sort on accruals/assets: monotonic negative relation to forward
returns; strongest in high-discretion accrual components.

## Universe

Non-financial equities (accrual definitions distort for banks/insurers);
point-in-time fundamentals mandatory.

## Required Data

Balance sheet + cash flow statement history with publication timestamps.

## Candidate Features

- `(net_income - operating_cash_flow) / total_assets`
- Balance-sheet vs cash-flow-statement accrual definitions (both tested)

## Candidate Parameters (declares trial search space)

- definition: {cash-flow-based, balance-sheet-based}
- rebalance: annual at filing + reporting lag
- buckets: {quintile}

## Expected Failure Modes

- Look-ahead via filing timestamps (top risk; conservative lag required)
- Post-publication decay of the anomaly is documented in literature
- Interaction with quality/value tilts (increment must be shown)

## Falsification Criteria

Reject if ANY of:
- No significant decrement for top-accrual quintile after conservative
  publication lagging
- Effect absent out-of-sample (literature decay confirmed)
- No increment after quality controls

## Transaction Cost Sensitivity

Low (annual refresh).

## Capacity Considerations

Moderate-high; fundamental data availability bounds it.
