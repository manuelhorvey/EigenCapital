# HYP-CS-001 — Quality Tilt (ROIC / Gross Profitability)

```text
hypothesis_id:        HYP-CS-001
title:                Firms with high return on invested capital or gross profitability
                      earn persistent positive abnormal returns
hypothesis_family:    cross_sectional
status:               UNVALIDATED
trial_group_default:  HYP-CS-001/quality-metric-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 quality;
                      Novy-Marx gross profitability, FF5 RMW)
```

## Claim

Profitability metrics (ROIC, gross profit/assets) positively predict cross-sectional
returns; the market underreacts to durable fundamental quality.

## Economic Rationale

High-quality business models compound capital and sustain cash flows; behavioral
underreaction to quality information plus institutional preference for safety
support the premium. Counter-cyclical payoff profile (quality bid up in stress).

## Expected Mechanism

Monotonic forward-return ordering across quality quintiles; negative market beta
of long-quality leg; strongest in downturns (flight to quality).

## Universe

All equities with ≥ 2 years of fundamentals history.

## Required Data

Income statement + balance sheet with publication timestamps; adjusted prices.

## Candidate Features

- `gross_profit / total_assets` (Novy-Marx)
- `nopat / invested_capital` (ROIC)
- Earnings-stability variant (time-series vol of ROE)

## Candidate Parameters (declares trial search space)

- metric: {GP/A, ROIC, composite}
- rebalance: {annual, quarterly}
- buckets: {quintile}

## Expected Failure Modes

- Redundancy with low-vol (quality names are low-vol): increment must be shown
- Accounting regime changes breaking comparability
- Value interaction: quality is expensive → combined QARP framing often the
  honest test

## Falsification Criteria

Reject if ANY of:
- Quality quintile spread CI includes 0 after costs out-of-sample
- No increment over HYP-VOL-001 controls
- Effect concentrated entirely in one accounting era (non-robust)

## Transaction Cost Sensitivity

Low (slow signal).

## Capacity Considerations

High.
