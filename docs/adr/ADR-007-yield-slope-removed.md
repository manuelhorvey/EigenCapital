# ADR-007: Removed yield_slope and real_yield_10y From XLF Feature Set

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.
>
> **OBSOLETE** — XLF removed from portfolio. Note: yield_slope and real_yield_10y are still computed system-wide for other assets (e.g., macro_filters in registry.py); the removal was XLF-specific. real_yield_delta_63 remains in active use for GC.

**Status:** Accepted

## Context

The initial XLF feature set included `yield_slope` (10y-2y spread) and `real_yield_10y` (TIPS-adjusted 10-year yield) as macro features. These have strong theoretical justification: the yield slope directly impacts bank net interest margins, and real yields affect financial asset valuations. However, during the 2023-2024 period, these features remained at persistently bearish levels despite XLF rallying 12.7% in 2023 and 27.7% in 2024. The yield curve was deeply inverted (negative slope) and real yields were at multi-year highs — both signals that the XLF model interpreted as bearish. The model could not escape its short bias because the macro features providing "bearish" context were not wrong, they were persistently wrong for the forward return.

## Decision

Remove `yield_slope` and `real_yield_10y` from the XLF feature set. Replace with `2y_yield_delta_63` (63-day change in 2-year yield, capturing rate expectations direction rather than level). The remaining features for XLF are: `rate_diff`, `2y_yield_delta_63`, `xlf_mom_63`, `xlf_vs_spy_63`. The replacement feature captures the direction of rate change (expectations) rather than the level (environment).

## Alternatives Considered

- **Keeping yield_slope with learned negative weight:** The model was already learning negative weights (correctly) but the magnitude of the signal was overwhelming the momentum features.
- **Using yield_slope regime context instead of raw value:** Binning yield_slope into regimes (steep, flat, inverted) was considered but adds complexity without addressing the root issue — level-based features cannot distinguish between a persistent inversion that will continue and one that will normalize.
- **Adding more features to dilute yield_slope impact:** Tested; the macro head's fixed 0.45 weight means the yield signal always contributes regardless of other features.

## Consequences

**Positive:** The 2023 signal flipped from wrong short bias to correct long after the replacement. The 2y_yield_delta_63 feature captures whether rates are accelerating or decelerating — rate expectations direction is more informative than rate levels for equity sectors. The 4-feature set (2 macro + 2 momentum) is minimal and interpretable.

**Negative:** Loss of level information: the absolute steepness of the yield curve and the real rate level contain information about financial repression and monetary stance. A regime where the yield curve un-inverts rapidly (steepening from negative to positive) would be a major signal that delta-based features would miss because the delta from deeply inverted to flat is smaller than from flat to steep.

## Evidence

2023 XLF rally: +12.7%. Model with yield_slope + real_yield_10y: persistent short bias, PF=0.90, net negative return. Model with 2y_yield_delta_63 replacement: PF=1.23, correctly captured the transition from tightening to pause. The delta feature captured the rate of change in rate expectations, which is the actual trading mechanism (markets price what will happen, not what is happening).
