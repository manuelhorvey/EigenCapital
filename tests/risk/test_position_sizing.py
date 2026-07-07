"""Tests for risk/position_sizing — position size calculation."""

import numpy as np
import pandas as pd

import pytest

from risk.position_sizing import calculate_position_size


class TestCalculatePositionSize:
    def test_returns_signal_times_multiplier(self):
        df = pd.DataFrame({
            "signal": [1.0, -1.0, 0.0],
            "risk_multiplier": [0.5, 0.8, 1.0],
        })
        sizes = calculate_position_size(df)
        assert list(sizes) == [0.5, -0.8, 0.0]

    def test_all_positive_signals(self):
        df = pd.DataFrame({
            "signal": [0.5, 1.0, 0.75],
            "risk_multiplier": [1.0, 1.0, 1.0],
        })
        sizes = calculate_position_size(df)
        assert list(sizes) == [0.5, 1.0, 0.75]

    def test_custom_base_risk_and_account_value(self):
        df = pd.DataFrame({
            "signal": [1.0],
            "risk_multiplier": [0.5],
        })
        sizes = calculate_position_size(df, base_risk=0.02, account_value=50000)
        assert list(sizes) == [0.5]

    def test_empty_dataframe(self):
        df = pd.DataFrame({"signal": [], "risk_multiplier": []})
        sizes = calculate_position_size(df)
        assert sizes.empty

    def test_default_parameters(self):
        df = pd.DataFrame({
            "signal": [1.0, -0.5],
            "risk_multiplier": [1.0, 1.0],
        })
        sizes = calculate_position_size(df)
        assert list(sizes) == [1.0, -0.5]

    def test_risk_multiplier_scales_proportionally(self):
        df = pd.DataFrame({
            "signal": [1.0, 1.0, 1.0],
            "risk_multiplier": [0.5, 1.0, 2.0],
        })
        sizes = calculate_position_size(df)
        assert list(sizes) == [0.5, 1.0, 2.0]
