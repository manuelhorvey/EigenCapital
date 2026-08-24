# HYP-ML-002 — Gradient-Boosted Long-Short on Engineered Factors

```text
hypothesis_id:        HYP-ML-002
title:                Gradient boosting (LightGBM-class) aggregating the validated
                      factor set produces a cross-sectional long-short signal with
                      OOS performance increment over the equal-rank composite of
                      the same factors
hypothesis_family:    ml
status:               UNVALIDATED
trial_group_default:  HYP-ML-002/gbm-hparam-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 12 workflow)
```

## Claim

Learned factor weighting beats naive rank-average aggregation of the same inputs,
out-of-sample, net of costs, after deflation — otherwise the composite stands.

## Economic Rationale

Factors interact (momentum stronger in low-vol names; quality offsets value
traps). Trees model interactions directly; if interactions are economically real,
the learner should find them; if not, the null (composite) is correct.

## Expected Mechanism

Daily/monthly cross-sectional predictions → top/bottom quantile long-short;
SHAP attributions must be consistent with the factors' registered rationales
(interpretability gate from HYP-ML-001 applies).

## Universe

Broad equities; identical folds to the underlying validated factors.

## Required Data

Validated factor panels + forward returns under purged CV.

## Candidate Features

Frozen set of SUPPORTED-family factor values only. No unvalidated features enter.

## Candidate Parameters (declares trial search space)

- depth/leaves, learning rate, min samples — grid declared and counted before run
- ensemble: {single, mean-of-top-k-folds}

## Expected Failure Modes

- Overfit via hyperparameter search breadth (deflation mandatory)
- Regime-dependent interactions that decay
- Factor-panel leakage through overlapping label windows (purging mandatory)

## Falsification Criteria

Reject if ANY of:
- Paired OOS improvement vs rank-composite CI includes 0 net of costs
- Deflated Sharpe of best config ≤ composite's
- SHAP attribution contradicts economic rationale (black box rejected even if
  metrics pass)

## Transaction Cost Sensitivity

High: ML signals churn faster than their inputs; turnover penalty is part of
the primary metric, never an afterthought.

## Capacity Considerations

Per underlying factor universe; quantile concentration reduces breadth vs composite.

## Notes

Depends on: HYP-FACTOR-003/002 gates passed; at least one SUPPORTED factor
family; Phase 1G infrastructure live. Blocked until then per governance.
