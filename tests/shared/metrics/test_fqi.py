"""Tests for shared/metrics/fqi.py."""

from __future__ import annotations

import pandas as pd
import pytest

from shared.metrics.fqi import compute_fqi, compute_fqi_from_df


class TestComputeFqi:
    def test_perfect_fill(self):
        assert compute_fqi(1.0, gap_fill=False, partial_fill=False, latency_bars=0) == 1.0

    def test_zero_fill_ratio(self):
        assert compute_fqi(0.0) == 0.0

    def test_gap_fill_penalty(self):
        result = compute_fqi(1.0, gap_fill=True)
        assert result == pytest.approx(0.50)

    def test_partial_fill_penalty(self):
        result = compute_fqi(1.0, partial_fill=True)
        assert result == pytest.approx(0.70)

    def test_latency_penalty(self):
        result = compute_fqi(1.0, latency_bars=10)
        assert result == pytest.approx(0.50)

    def test_combined_penalties(self):
        result = compute_fqi(0.8, gap_fill=True, partial_fill=True, latency_bars=5)
        expected = 0.8 * 0.50 * 0.70 * 0.75  # 0.8 * 0.5 * 0.7 * 0.75 = 0.21
        assert result == pytest.approx(expected)

    def test_custom_penalties(self):
        result = compute_fqi(1.0, gap_fill=True, gap_penalty=0.80, partial_penalty=0.50)
        assert result == pytest.approx(0.20)

    def test_latency_clamps_to_zero(self):
        result = compute_fqi(1.0, latency_bars=30)
        assert result == 0.0

    def test_clamps_to_zero(self):
        result = compute_fqi(-0.5)
        assert result == 0.0

    def test_clamps_to_one(self):
        result = compute_fqi(2.0)
        assert result == 1.0


class TestComputeFqiFromDf:
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = compute_fqi_from_df(df)
        assert result == {}

    def test_missing_fill_col(self):
        df = pd.DataFrame({"asset": ["EURUSD"]})
        result = compute_fqi_from_df(df)
        assert result == {}

    def test_single_asset(self):
        df = pd.DataFrame(
            {
                "asset": ["EURUSD", "EURUSD", "EURUSD"],
                "friction_fill_qty_ratio": [1.0, 0.8, 1.0],
                "friction_gap_fill": [False, False, True],
                "friction_partial_fill": [False, True, False],
                "friction_latency_bars": [0, 1, 0],
            }
        )
        result = compute_fqi_from_df(df, min_trades=3)
        assert "EURUSD" in result
        assert 0 < result["EURUSD"] <= 1
