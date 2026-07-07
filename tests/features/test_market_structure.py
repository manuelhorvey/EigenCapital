"""Tests for features/market_structure — MarketStructureDetector."""

import numpy as np
import pandas as pd

from features.market_structure import MarketStructureDetector


class TestMarketStructureDetector:
    def test_default_window(self):
        detector = MarketStructureDetector()
        assert detector.window == 50

    def test_custom_window(self):
        detector = MarketStructureDetector(window=100)
        assert detector.window == 100

    def test_insufficient_data_returns_empty_state(self):
        df = pd.DataFrame({"close": [100, 101], "high": [102, 103], "low": [99, 100]})
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert state.trend_strength == 0.0
        assert state.volatility_regime == 1.0
        assert state.breakout_pressure == 0.5

    def test_detect_returns_all_fields(self):
        rng = np.random.RandomState(42)
        n = 200
        df = pd.DataFrame({
            "close": 100 + np.cumsum(rng.randn(n) * 0.5),
            "high": 100 + np.cumsum(rng.randn(n) * 0.5) * 1.01,
            "low": 100 + np.cumsum(rng.randn(n) * 0.5) * 0.99,
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert hasattr(state, "trend_strength")
        assert hasattr(state, "compression_score")
        assert hasattr(state, "distance_to_swing_high")
        assert hasattr(state, "distance_to_swing_low")
        assert hasattr(state, "volatility_regime")
        assert hasattr(state, "breakout_pressure")

    def test_trend_strength_positive_for_upward_sloping(self):
        df = pd.DataFrame({
            "close": np.linspace(100, 110, 200),
            "high": np.linspace(101, 111, 200),
            "low": np.linspace(99, 109, 200),
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert state.trend_strength > 0

    def test_trend_strength_negative_for_downward_sloping(self):
        df = pd.DataFrame({
            "close": np.linspace(110, 100, 200),
            "high": np.linspace(111, 101, 200),
            "low": np.linspace(109, 99, 200),
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert state.trend_strength < 0

    def test_breakout_pressure_near_one_at_high(self):
        df = pd.DataFrame({
            "close": np.linspace(100, 110, 200),
            "high": np.linspace(101, 111, 200),
            "low": np.linspace(99, 109, 200),
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        # Price near top of range → breakout_pressure close to 1
        assert state.breakout_pressure > 0.5

    def test_volatility_regime_is_positive(self):
        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "close": 100 + np.cumsum(rng.randn(200) * 0.5),
            "high": 100 + np.cumsum(rng.randn(200) * 0.5) * 1.01,
            "low": 100 + np.cumsum(rng.randn(200) * 0.5) * 0.99,
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert state.volatility_regime >= 0

    def test_compression_score(self):
        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "close": 100 + np.cumsum(rng.randn(200) * 0.5),
            "high": 100 + np.cumsum(rng.randn(200) * 0.5) * 1.01,
            "low": 100 + np.cumsum(rng.randn(200) * 0.5) * 0.99,
        })
        detector = MarketStructureDetector(window=50)
        state = detector.detect(df)
        assert state.compression_score >= 0
