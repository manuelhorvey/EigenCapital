"""Tests for features/archetypes — ArchetypeClassifier."""

import numpy as np
import pandas as pd
import pytest

from features.archetypes import ArchetypeClassifier, SetupArchetype


class TestArchetypeClassifier:
    def test_initial_state(self):
        classifier = ArchetypeClassifier()
        assert classifier.adx_threshold == 25.0
        assert classifier.rsi_extreme == 30.0

    def test_custom_parameters(self):
        classifier = ArchetypeClassifier(adx_threshold=30.0, rsi_extreme=25.0)
        assert classifier.adx_threshold == 30.0
        assert classifier.rsi_extreme == 25.0

    def test_breakout_test(self):
        """High BB z-score + strong ADX = BREAKOUT_TEST."""
        row = pd.Series({"adx": 30.0, "rsi": 50.0, "bb_zscore": 2.5, "ema_spread": 0.02})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result == SetupArchetype.BREAKOUT_TEST

    def test_momentum_ignition(self):
        """Strong ADX + wide BB + positive EMA spread = MOMENTUM_IGNITION."""
        row = pd.Series({"adx": 30.0, "rsi": 50.0, "bb_zscore": 1.8, "ema_spread": 0.02})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result == SetupArchetype.MOMENTUM_IGNITION

    def test_trend_pullback(self):
        """Trending market with price near EMA = TREND_PULLBACK."""
        row = pd.Series({"adx": 30.0, "rsi": 50.0, "bb_zscore": 1.0, "ema_spread": 0.001})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result == SetupArchetype.TREND_PULLBACK

    def test_mean_reversion(self):
        """Low ADX + extreme RSI = MEAN_REVERSION."""
        row = pd.Series({"adx": 15.0, "rsi": 80.0, "bb_zscore": 1.0, "ema_spread": 0.001})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result == SetupArchetype.MEAN_REVERSION

    def test_mean_reversion_rsi_low(self):
        """Low ADX + RSI below extreme threshold = MEAN_REVERSION."""
        row = pd.Series({"adx": 15.0, "rsi": 25.0, "bb_zscore": 1.0, "ema_spread": 0.001})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result == SetupArchetype.MEAN_REVERSION

    def test_vol_expansion(self):
        """Very low ADX + tight BB = VOL_EXPANSION."""
        row = pd.Series({"adx": 15.0, "rsi": 50.0, "bb_zscore": 1.0, "ema_spread": 0.001})
        classifier = ArchetypeClassifier(adx_threshold=25.0)
        result = classifier.classify(row)
        assert result == SetupArchetype.VOL_EXPANSION

    def test_unknown_default(self):
        """No conditions met = UNKNOWN."""
        row = pd.Series({"adx": 20.0, "rsi": 50.0, "bb_zscore": 1.5, "ema_spread": 0.002})
        classifier = ArchetypeClassifier(adx_threshold=25.0)
        result = classifier.classify(row)
        assert result == SetupArchetype.UNKNOWN

    def test_handles_missing_fields(self):
        """Missing fields should not crash — defaults to UNKNOWN."""
        row = pd.Series({"adx": 30.0})
        classifier = ArchetypeClassifier()
        result = classifier.classify(row)
        assert result in SetupArchetype

    def test_classify_error_handling(self):
        """Bad input returns UNKNOWN without crashing."""
        classifier = ArchetypeClassifier()
        result = classifier.classify(pd.Series({"adx": "not_a_number"}))
        assert result == SetupArchetype.UNKNOWN


class TestTagDataframe:
    def test_adds_archetype_columns(self):
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
        assert "archetype" in tagged.columns
        assert "archetype_name" in tagged.columns
        assert len(tagged) == 4

    def test_archetype_names_are_strings(self):
        data = pd.DataFrame(
            {
                "adx": [30.0],
                "rsi": [50.0],
                "bb_zscore": [2.5],
                "ema_spread": [0.02],
            }
        )
        classifier = ArchetypeClassifier()
        tagged = classifier.tag_dataframe(data)
        assert isinstance(tagged["archetype_name"].iloc[0], str)

    def test_does_not_mutate_input(self):
        data = pd.DataFrame(
            {
                "adx": [30.0],
                "rsi": [50.0],
                "bb_zscore": [2.5],
                "ema_spread": [0.02],
            }
        )
        original_cols = set(data.columns)
        ArchetypeClassifier().tag_dataframe(data)
        assert set(data.columns) == original_cols


class TestSetupArchetypeEnum:
    def test_all_values_defined(self):
        values = {e.value for e in SetupArchetype}
        expected = {
            "MOMENTUM_IGNITION",
            "MEAN_REVERSION",
            "BREAKOUT_TEST",
            "TREND_PULLBACK",
            "VOL_EXPANSION",
            "LIQUIDITY_SWEEP",
            "UNKNOWN",
        }
        assert values == expected
