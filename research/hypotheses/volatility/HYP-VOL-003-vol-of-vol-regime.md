# HYP-VOL-003 — Volatility-of-Volatility Regime Signal

```text
hypothesis_id:        HYP-VOL-003
title:                The stability of implied/realized volatility itself (vol-of-vol)
                      conditions the performance of other signals; unstable-vol
                      regimes invert or mute trend-following edges
hypothesis_family:    volatility
status:               UNVALIDATED
trial_group_default:  HYP-VOL-003/regime-definition-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 VIX/S&P inverse
                      correlation, Ch 9 volatility forecasting)
```

## Claim

Regimes defined by vol-of-vol (or VIX level + change) modulate other hypotheses'
performance — specifically that trend/momentum edges concentrate in stable-vol
regimes. This is a *conditioning* hypothesis evaluated as an overlay.

## Economic Rationale

Unstable volatility marks information-shock regimes where underreaction-based
edges are overwhelmed by flow and forced de-risking; stable-vol regimes favor
gradual diffusion dynamics that momentum monetizes.

## Expected Mechanism

Split out-of-sample folds by ex-ante regime indicator: signal ICs/Sharpes differ
significantly across regimes; regime assignment uses no concurrent information.

## Universe

Whatever underlying hypothesis is being conditioned (paired evaluation).

## Required Data

Realized vol series; optionally VIX/implied proxy.

## Candidate Features

- Rolling std of realized vol over {21, 63} days
- VIX level × change grid

## Candidate Parameters (declares trial search space)

- regime window: {21, 63}
- split rule: {median, tercile}

## Expected Failure Modes

- Data snooping in regime definition (regimes chosen to flatter the conditioned
  signal — must be defined ex-ante and frozen)
- Too few regime observations for significance

## Falsification Criteria

Reject if ANY of:
- Regime-conditional differences CI includes 0 on held-out folds
- Improvement does not survive frozen ex-ante regime definition
- Regime classification itself unstable (high flip frequency without payoff)

## Transaction Cost Sensitivity

Depends entirely on the conditioned hypothesis.

## Capacity Considerations

N/A (overlay).
