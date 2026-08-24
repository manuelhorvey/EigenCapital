# HYP-SA-004 — Bayesian Rolling-Hedge Pairs

```text
hypothesis_id:        HYP-SA-004
title:                Modeling pair hedge ratios as time-varying (Bayesian rolling
                      regression) improves spread stationarity and net performance
                      vs fixed-hedge pairs
hypothesis_family:    statistical_arbitrage
status:               UNVALIDATED
trial_group_default:  HYP-SA-004/hedge-model-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 10 Bayesian rolling
                      regression for pairs trading)
```

## Claim

Treating the hedge ratio as a latent slowly-varying parameter with posterior
uncertainty — rather than a fixed OLS coefficient — produces more stationary
spreads and better out-of-sample pair P&L than HYP-SA-001's static hedge.

## Economic Rationale

Relative fundamentals and float evolve; the true hedge ratio drifts. Fixed
hedges accumulate misspecification that manifests as fake "dislocations" traded
at a loss. Bayesian updating tracks drift while penalizing overreaction via
prior shrinkage, and posterior uncertainty can gate trade sizing.

## Expected Mechanism

Sequential posterior over (alpha_t, beta_t); standardized residual under current
posterior is the trading signal; wide posteriors widen effective thresholds
(trade less when uncertain).

## Universe

Same pair universe as HYP-SA-001 for paired comparison.

## Required Data

Adjusted prices both legs.

## Candidate Features

- Posterior mean/quantiles of beta_t
- Residual z-score under dynamic hedge
- Posterior-width gating signal

## Candidate Parameters (declares trial search space)

- prior scale: {weak, informative}
- forgetting/window: {63, 126}
- uncertainty gate: {none, quantile}

## Expected Failure Modes

- Hedge chasing: adaptive beta turns noise into trades (gate must prevent)
- Computational cost at scale
- Improvement exists in-sample only (regime artifact)

## Falsification Criteria

Reject if ANY of:
- No out-of-sample improvement vs static-hedge control on identical pairs
- Improvement not robust across declared prior scales
- Turnover increase consumes the gross improvement

## Transaction Cost Sensitivity

High; must be evaluated against the static control net.

## Capacity Considerations

As HYP-SA-001.
