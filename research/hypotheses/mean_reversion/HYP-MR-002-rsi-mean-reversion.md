# HYP-MR-002 — RSI(14) Overbought/Oversold Mean Reversion

```text
hypothesis_id:        HYP-MR-002
title:                Assets with RSI(14) above 70 underperform and below 30
                      outperform over the subsequent short horizon
hypothesis_family:    mean_reversion
status:               UNVALIDATED
trial_group_default:  HYP-MR-002/threshold-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 4 + Appendix TA-Lib)
```

## Claim

The classical oscillator thresholds identify locally stretched moves that mean
revert within days-to-weeks, net of costs, when applied systematically across a
cross-section rather than chart-wise.

## Economic Rationale

Short-horizon overextension reflects transient order-flow imbalance rather than
information; as imbalance exhausts, prices revert toward equilibrium. RSI is a
compact normalization of the up/down move asymmetry over the lookback window.

## Expected Mechanism

Conditional forward returns: E[r | RSI > 70] < E[r | RSI < 30] over {5, 10} day
horizons; effect should be evaluated as a conditional overlay, not standalone alpha.

## Universe

Liquid equities/futures where short-horizon trading is cost-feasible.

## Required Data

Daily OHLCV (RSI uses closes only).

## Candidate Features

- `RSI(14)` via standard Wilder smoothing (TA-Lib-equivalent definition pinned
  in feature spec)
- Continuous variant: `(50 - RSI) / 50` as signed intensity (avoids threshold
  discreteness)

## Candidate Parameters (declares trial search space)

- lookback: {9, 14, 21}
- thresholds: {(30/70), (20/80)} or continuous form
- horizon: {5, 10} days

## Expected Failure Modes

- In strong trends RSI pins at extremes while price keeps going (the classic
  failure mode — trend-regime interaction must be tested, e.g., conditioning on
  longer-term trend sign)
- Parameter luck across threshold grid (multiple-testing discipline applies)

## Falsification Criteria

Reject if ANY of:
- No significant spread between extreme-RSI buckets after baseline costs under
  purged walk-forward CV
- Effect fails to survive regime split (works only in one regime → reclassify
  as regime-conditional candidate, weaker claim)
- Grid results non-monotone/no coherent structure (parameter mining artifact)

## Transaction Cost Sensitivity

Very high at daily frequency; likely viable only as an execution-timing overlay
on existing positions rather than standalone. State which framing is tested.

## Capacity Considerations

Low standalone; irrelevant if adopted as timing overlay.
