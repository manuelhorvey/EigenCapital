from dataclasses import dataclass


@dataclass
class RegimeRow:
    P_trend: float
    P_range: float
    P_volatile: float
    regime_label: str


def evaluate_regime_conviction_gate(
    regime_row: RegimeRow | None,
    model_confidence: float,
    bars_in_current_regime: int,
    regime_margin_threshold: float = 0.35,
    confidence_threshold: float = 0.50,
    min_bars_in_regime: int = 3,
) -> tuple[bool, str]:
    """
    Decides whether a signal flip is allowed based on regime conviction.
    
    Flips are allowed under the following conditions:
    1. Model confidence is high (equal to or greater than the confidence threshold).
    2. No regime data is available (default to allow flip).
    3. The current regime is TREND, it is decisive (P_trend - P_range >= regime_margin_threshold),
       and the regime has persisted for at least min_bars_in_regime.
    
    Flips are blocked in ranging or volatile/neutral markets when the model is uncertain,
    preventing churn and whipsaws.
    """
    # Normalize model confidence and threshold (percentage vs decimal)
    model_conf_decimal = model_confidence / 100.0 if model_confidence > 1.0 else model_confidence
    conf_thresh_decimal = confidence_threshold / 100.0 if confidence_threshold > 1.0 else confidence_threshold

    # High model confidence always allows flipping
    if model_conf_decimal >= conf_thresh_decimal:
        return True, "high_model_confidence"

    # If regime tracking is disabled/not populated, allow by default
    if regime_row is None:
        return True, "no_regime_data"

    # Persistent regime check
    if bars_in_current_regime < min_bars_in_regime:
        return False, f"regime_duration_insufficient ({bars_in_current_regime} < {min_bars_in_regime})"

    # Flips are only permitted in trend regimes
    if regime_row.regime_label != "trend":
        return False, f"regime_not_trend ({regime_row.regime_label})"

    # Margin check between Trend and Range probabilities
    margin = regime_row.P_trend - regime_row.P_range
    if margin < regime_margin_threshold:
        return False, f"trend_margin_insufficient ({margin:.4f} < {regime_margin_threshold:.4f})"

    return True, f"decisive_trend_regime (margin={margin:.4f})"
