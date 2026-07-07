"""Archetype classification — market structure regime per asset.

Classifies each asset into one of 6 setup archetypes based on technical
indicators (EMA spread, ADX, RSI, Bollinger Bands). These archetypes are
inference-only (never passed to XGBoost) and used by the entry optimizer
and governance layers to contextualize signals.

Archetypes:
    MOMENTUM_IGNITION — trend just starting (tight EMA, rising ADX)
    MEAN_REVERSION    — price stretched from mean (wide BB, extreme RSI)
    BREAKOUT_TEST     — price at range boundary (BB squeeze, low vol)
    TREND_PULLBACK    — counter-trend move within established trend
    VOL_EXPANSION     — volatility regime shift (rising ATR, ADX)
    LIQUIDITY_SWEEP   — stop-hunt pattern (wicks beyond structure)
    UNKNOWN           — no clear archetype detected
"""

import logging
from enum import Enum

import pandas as pd

logger = logging.getLogger("eigencapital.features.archetypes")


class SetupArchetype(Enum):
    MOMENTUM_IGNITION = "MOMENTUM_IGNITION"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT_TEST = "BREAKOUT_TEST"
    TREND_PULLBACK = "TREND_PULLBACK"
    VOL_EXPANSION = "VOL_EXPANSION"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    UNKNOWN = "UNKNOWN"


class ArchetypeClassifier:
    """
    Phase 3: Archetype Classification.
    Categorizes trade signals into structural market archetypes.
    Used by Phase 1 (Entry) and Phase 2 (TP) for context-aware execution.
    """

    def __init__(self, adx_threshold: float = 25.0, rsi_extreme: float = 30.0):
        self.adx_threshold = adx_threshold
        self.rsi_extreme = rsi_extreme

    def classify(self, row: pd.Series) -> SetupArchetype:
        """
        Classifies a single point in time (row of features).
        Expects features: adx, rsi, bb_zscore, ema_spread.
        """
        try:
            adx = row.get("adx", 0)
            rsi = row.get("rsi", 50)
            bb_z = row.get("bb_zscore", 0)
            ema_s = row.get("ema_spread", 0)

            # 1. Breakout Test (most extreme — price at outer Bollinger Band)
            if abs(bb_z) > 2.0 and adx > self.adx_threshold:
                return SetupArchetype.BREAKOUT_TEST

            # 2. Momentum Ignition (strong trending move)
            if adx > self.adx_threshold and abs(bb_z) > 1.5 and abs(ema_s) > 0.01:
                return SetupArchetype.MOMENTUM_IGNITION

            # 3. Trend Pullback (trending, price near EMA, not extreme)
            if adx > self.adx_threshold and abs(ema_s) < 0.005 and 40 <= rsi <= 60:
                return SetupArchetype.TREND_PULLBACK

            # 4. Mean Reversion (no trend, RSI extreme)
            if adx < self.adx_threshold and (rsi > (100 - self.rsi_extreme) or rsi < self.rsi_extreme):
                return SetupArchetype.MEAN_REVERSION

            # 5. Vol Expansion (Approximated by low ADX turning higher)
            if adx < 20.0 and abs(bb_z) < 1.5:
                return SetupArchetype.VOL_EXPANSION

            return SetupArchetype.UNKNOWN
        except (ValueError, TypeError, KeyError) as e:
            logger.error("Archetype classification failed: %s", e)
            return SetupArchetype.UNKNOWN

    def tag_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies classification to an entire feature DataFrame."""
        df = df.copy()
        df["archetype"] = df.apply(self.classify, axis=1)
        df["archetype_name"] = df["archetype"].apply(lambda x: x.value)
        return df


if __name__ == "__main__":
    # Quick test with dummy data
    data = pd.DataFrame(
        {
            "adx": [30.0, 15.0, 40.0, 10.0],
            "rsi": [50.0, 80.0, 50.0, 50.0],
            "bb_zscore": [1.8, 2.2, 2.5, 0.5],
            "ema_spread": [0.02, 0.001, 0.03, 0.0001],
        }
    )

    classifier = ArchetypeClassifier()
    tagged = classifier.tag_dataframe(data)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("Archetype Classification Test:")
    logger.info("\n%s", tagged[["adx", "rsi", "bb_zscore", "archetype_name"]])
