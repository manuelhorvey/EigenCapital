# HYP-BRK-002 — Volatility-Normalized Range Expansion

```text
hypothesis_id:        HYP-BRK-002
title:                Breakouts accompanied by volatility-normalized range expansion
                      (true range >> recent norm) continue; unconfirmed breaks fail
hypothesis_family:    breakout
status:               UNVALIDATED
trial_group_default:  HYP-BRK-002/expansion-ratio-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 9 rolling stats +
                      Appendix volatility indicators)
```

## Claim

Conditioning any level-break signal on range expansion normalized by recent ATR
separates genuine regime shifts from noise — confirmed breaks continue,
unconfirmed breaks revert.

## Economic Rationale

Regime transitions require order-flow conviction; range expansion is its price
signature. Normalizing by recent volatility makes the test regime-invariant.

## Expected Mechanism

Two-way split of breakouts by expansion ratio: continuation concentrated in the
high-expansion bucket; reversion in the low bucket. The spread between buckets is
the hypothesis.

## Universe

Same as HYP-BRK-001 (paired evaluation).

## Required Data

Daily OHLCV (needs highs/lows for true range).

## Candidate Features

- `TR(t) / ATR(n)` at breakout events
- Directional confirmation: close location within bar range

## Candidate Parameters (declares trial search space)

- ATR lookback: {14, 20}
- ratio threshold: {1.25, 1.5, 2.0}
- horizon: {5, 10, 21} days

## Expected Failure Modes

- Correlation with news events → gap risk beyond modeled costs
- Threshold grid mining without structure (monotonicity required)

## Falsification Criteria

Reject if ANY of:
- High-vs-low expansion bucket return spread CI includes 0
- Effect not monotone across declared ratio thresholds
- Increment over unconditional HYP-BRK-001 absent (redundant conditioning)

## Transaction Cost Sensitivity

As HYP-BRK-001.

## Capacity Considerations

As HYP-BRK-001.
