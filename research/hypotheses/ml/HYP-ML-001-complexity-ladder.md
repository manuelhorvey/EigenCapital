# HYP-ML-001 — Complexity Ladder: Does ML Add Value Over Simple Rules?

```text
hypothesis_id:        HYP-ML-001
title:                For each validated simple signal family, increasing model
                      complexity (rule → regime-conditioning → linear → tree →
                      boosting) adds measurable out-of-sample value at least once,
                      or the family is closed with its simplest adequate form
hypothesis_family:    ml
status:               UNVALIDATED
trial_group_default:  HYP-ML-001/complexity-ladder
source:               docs/research/ml4t-extraction.md (Jansen Ch 6, 11, 12; Ch 23
                      no-free-lunch)
```

## Claim

A *methodological* claim evaluated per signal family: complexity must justify
itself out-of-sample, net of costs and multiple-testing penalties. Default
expectation is that it often does not — rejection is a valid, informative outcome.

## Economic Rationale

Financial signal-to-noise is low; flexible models fit noise unless interactions/
nonlinearities are real. The ladder exists to prevent "we used XGBoost because
the book did" — every rung must pay rent in held-out performance.

## Expected Mechanism

Identical data/folds/costs across rungs; paired comparison of OOS metrics;
complexity wins only if improvement survives deflation for added trials.

## Universe

Whichever family's signal is on the ladder (one ladder per family, separately
registered).

## Required Data

Same as the underlying hypothesis at each rung.

## Candidate Features

The base hypothesis's feature set, frozen before the ladder starts.

## Candidate Parameters (declares trial search space)

- rungs: {simple rule, regime overlay, ridge/logistic, random forest, gradient boosting}
- CV scheme fixed ex-ante (purged walk-forward)

## Expected Failure Modes

- Trial-count explosion at higher rungs (hyperparameter grids) without deflated
  accounting — the exact failure this hypothesis is designed to expose
- Subtle fold leakage favoring complex models (more capacity to exploit leaks)

## Falsification Criteria

Reject complexity (keep simpler form) if ANY of:
- No significant paired OOS improvement after cost adjustment
- Improvement fails deflated-SR correction given trials consumed
- Interpretability gate unmet (no coherent SHAP attribution consistent with the
  family's economic rationale)

## Transaction Cost Sensitivity

Evaluated per rung under identical cost model; complexity that only works gross
is rejected.

## Capacity Considerations

Per underlying family.

## Notes

GATE HYPOTHESIS for the whole `ml/` directory. No production ML strategy may
cite performance that skipped this comparison. Per governance: do not run until
Phase 1G infrastructure exists.
