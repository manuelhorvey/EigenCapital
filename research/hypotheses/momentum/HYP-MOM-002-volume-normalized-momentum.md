# HYP-MOM-002 — Volume-Normalized Momentum

```text
hypothesis_id:        HYP-MOM-002
title:                Momentum normalized by return volatility and confirmed by
                      volume is more persistent than raw price momentum
hypothesis_family:    momentum
status:               UNVALIDATED
trial_group_default:  HYP-MOM-002/normalization-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 factor table)
```

## Claim

Dividing trailing total return by the standard deviation of those returns
(volatility-adjusted momentum), optionally conditioned on volume expansion,
yields a stronger, more stable cross-sectional predictor than raw momentum.

## Economic Rationale

Raw momentum conflates information arrival with risk: a high-vol asset can post
large returns without any informational edge. Vol normalization isolates
risk-adjusted drift; volume confirmation separates genuine repositioning from
low-liquidity drift that reverses.

## Expected Mechanism

Normalized-momentum ranks should show higher IC persistence (lower IC std) than
HYP-MOM-001 raw ranks on the same universe/folds — the claim is *improvement*,
verified head-to-head under identical trial accounting.

## Universe

Identical to HYP-MOM-001 (same folds for comparability).

## Required Data

Adjusted daily prices; daily volume.

## Candidate Features

- `ts_ret(t, N) / ts_std(t, N)`
- Volume-conditioned variant (above-average-volume days only)

## Candidate Parameters (declares trial search space)

- N: {126, 252}
- volume filter: {none, above-median}

## Expected Failure Modes

- Vol estimates unstable in crises distort ranks at the worst time
- Conditioning reduces breadth below viable levels (fundamental-law check)

## Falsification Criteria

Reject if ANY of:
- No statistically significant IC improvement over raw momentum on paired folds
- Improvement exists gross but not net of incremental turnover costs
- Breadth loss offsets IC gain in the IR ≈ IC·√breadth accounting

## Transaction Cost Sensitivity

Same order as HYP-MOM-001; must be evaluated as an increment against it.

## Capacity Considerations

As HYP-MOM-001.
