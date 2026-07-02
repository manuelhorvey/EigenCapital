import logging

import numpy as np
import pandas as pd
from scipy import stats

from paper_trading.entry.decision import MarketStructureState

logger = logging.getLogger("eigencapital.features.market_structure")


class MarketStructureDetector:
    """
    Phase 1: Market Structure Detector.
    Strictly informational snapshot of market geometry.
    No entry/exit decisions or asset-specific thresholds allowed here.
    """

    def __init__(self, window: int = 50):
        self.window = window

    def detect(self, df: pd.DataFrame) -> MarketStructureState:
        """
        Computes a structural snapshot from recent price data.
        """
        if len(df) < self.window:
            return self._empty_state()

        recent = df.tail(self.window)
        close = recent["close"]
        high = recent["high"]
        low = recent["low"]
        last_close = float(close.iloc[-1])

        # 1. Trend Strength (Log-linear slope)
        log_price = np.log(close)
        x = np.arange(len(log_price))
        slope, _, _, _, _ = stats.linregress(x, log_price)

        # 2. Compression Score (Bollinger Band width / MA)
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = (4 * std20) / (ma20 + 1e-9)
        compression = float(bb_width.iloc[-1])

        # 3. Distance to Swing High/Low
        swing_high = float(high.max())
        swing_low = float(low.min())
        dist_high = swing_high / last_close - 1.0
        dist_low = last_close / swing_low - 1.0

        # 4. Volatility Regime (Rolling 10d vol / Rolling 50d vol)
        rets = close.pct_change().dropna()
        if len(rets) >= 20:
            short_vol = rets.tail(10).std()
            long_vol = rets.std()
            vol_regime = short_vol / (long_vol + 1e-9)
        else:
            vol_regime = 1.0

        # 5. Breakout Pressure (Where is price relative to recent range?)
        # 0.0 = at bottom, 1.0 = at top
        range_span = swing_high - swing_low
        pressure = (last_close - swing_low) / (range_span + 1e-9)

        return MarketStructureState(
            trend_strength=round(float(slope), 8),
            compression_score=round(compression, 6),
            distance_to_swing_high=round(dist_high, 6),
            distance_to_swing_low=round(dist_low, 6),
            volatility_regime=round(vol_regime, 4),
            breakout_pressure=round(float(pressure), 4),
        )

    def _empty_state(self) -> MarketStructureState:
        return MarketStructureState(
            trend_strength=0.0,
            compression_score=0.0,
            distance_to_swing_high=0.0,
            distance_to_swing_low=0.0,
            volatility_regime=1.0,
            breakout_pressure=0.5,
        )


if __name__ == "__main__":
    # Test with dummy data
    data = pd.DataFrame(
        {
            "close": np.linspace(100, 105, 100) + np.random.normal(0, 0.1, 100),
            "high": np.linspace(101, 106, 100),
            "low": np.linspace(99, 104, 100),
        }
    )
    detector = MarketStructureDetector(window=50)
    state = detector.detect(data)
    print("Market Structure State:")
    print(state)
