from dataclasses import dataclass


@dataclass
class MarketStructureState:
    """Structural snapshot of the market. Purely informational, no decision logic."""

    trend_strength: float
    compression_score: float
    distance_to_swing_high: float
    distance_to_swing_low: float
    volatility_regime: float
    breakout_pressure: float
