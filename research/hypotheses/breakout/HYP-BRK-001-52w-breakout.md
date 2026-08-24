# HYP-BRK-001 — 52-Week High Breakout Continuation

```text
hypothesis_id:        HYP-BRK-001
title:                Closes above the prior 52-week high are followed by positive
                      drift over the subsequent month, net of costs
hypothesis_family:    breakout
status:               UNVALIDATED
trial_group_default:  HYP-BRK-001/confirm-horizon-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 9 rolling stats +
                      Ch 4 % off high complement)
```

## Claim

New 52-week-high events mark transitions to persistent upward regimes; the
event, not merely proximity (HYP-TREND-003), carries continuation.

## Economic Rationale

At new highs, no holder is underwater → resistance from loss-realization supply
is absent; attention/salience draws incremental flow; underreaction extends the
move as information diffuses.

## Expected Mechanism

Event-study drift: conditional forward returns after breakout events exceed
unconditional returns over {5..21} days; effect decays with horizon.

## Universe

Liquid equities/futures; ≥ 252d history per name at event time.

## Required Data

Adjusted daily OHLCV.

## Candidate Features

- Event indicator: `close > max(close, 252d lagged)`
- Confirmation filters: volume expansion, close strength in day range

## Candidate Parameters (declares trial search space)

- lookback: {189, 252} days
- confirmation: {none, volume, close-location}
- holding: {10, 21} days

## Expected Failure Modes

- False breaks in choppy regimes (whipsaw cluster near range tops)
- Gap entries paying up badly vs modeled fills
- Overlap with momentum exposure (increment over HYP-MOM-001 must be shown if
  claimed as separate sleeve rather than entry timing for trend)

## Falsification Criteria

Reject if ANY of:
- Post-event drift CI includes unconditional mean after baseline costs
- Drift absent in the most-liquid stratum (microstructure artifact signature)
- No improvement over simple trend-following entry rules it would replace

## Transaction Cost Sensitivity

Moderate-high (event-driven entries cluster).

## Capacity Considerations

Moderate; event concentration creates simultaneous-entry crowding risk.
