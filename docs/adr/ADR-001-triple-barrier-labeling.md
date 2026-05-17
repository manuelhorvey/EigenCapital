# ADR-001: Triple Barrier Labeling Over Simple Directional Labels

**Status:** Accepted

## Context

The system needed a labeling methodology to train a multiclass XGBoost classifier (BUY / NEUTRAL / SELL). Initial experiments used simple forward-return directional labels: +1 if price N bars ahead is higher, -1 if lower. This produced ~33% win rate for the classifier — indistinguishable from random across all threshold configurations. The problem was that a) fixed-horizon labels ignore path-dependent stop-outs, b) binary labels collapse magnitude information, and c) the label does not correspond to how a trader actually exits a position.

## Decision

Adopt triple barrier labeling with volatility-scaled barriers (pt_sl=2.0, vertical barrier=20 bars for paper trading, 10 for daily research). Barriers are placed at ±2 standard deviations of exponentially weighted volatility (EWM span=100). Labels: +1 when upper barrier hit first (profit take), -1 when lower barrier hit first (stop loss), 0 when vertical barrier expires. The labeling uses pandas `expanding().apply()` with early termination logic.

## Alternatives Considered

- **Fixed-horizon forward returns:** Produced ~33% win rate, no configuration improved this.
- **Meta-labeling overlay:** Considered as a second-stage filter but deferred — the primary label noise needed fixing first.
- **CPV (Critical Path Volume) labeling:** Too complex for the current data frequency; may revisit for intraday.
- **Fractional barrier (pt_sl=[1,2]):** Asymmetric barriers were tested but the classifier developed directional bias. Symmetric 2.0 produces balanced label distributions.

## Consequences

**Positive:** Labels correspond to actual trade economics (volatility-adjusted profit targets and stop losses). The classifier learns path-dependent exit conditions, not just endpoint direction. The 0 class (vertical barrier expiry) provides a natural "no trade" signal that has proven useful for confidence calibration.

**Negative:** Triple barrier is computationally intensive for large datasets (expanding window path search). The 20-bar vertical barrier means the model cannot learn positions longer than ~1 month. Labels are non-deterministic with respect to raw price — same price path can produce different labels in different volatility regimes.

## Evidence

The 4-feature XGBoost trained on triple barrier labels achieved Sharpe 0.65 average across 2019-2024 walk-forward. The 11.08% average annual return confirmed that triple barrier labeling transmits economically meaningful signal. Simple directional models on the same feature set never exceeded Sharpe 0.25.
