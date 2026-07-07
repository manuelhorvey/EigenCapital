"""Tests for shared/metrics/eis.py."""

from __future__ import annotations

import pandas as pd
import pytest

from shared.metrics.eis import compute_eis, compute_eis_from_df


class TestComputeEis:
    def test_perfect_execution(self):
        eis = compute_eis(0.0, 0.0, 1.0, False, False, 0)
        assert eis == pytest.approx(1.0)

    def test_max_slippage(self):
        eis = compute_eis(50.0, 0.0, 1.0, False, False, 0)
        # w_slippage * (1 - 1.0) + w_fill * 1.0 + w_latency * 1.0 = 0 + 0.35 + 0.25 = 0.60
        assert eis == pytest.approx(0.60, abs=0.01)

    def test_max_latency(self):
        eis = compute_eis(0.0, 0.0, 1.0, False, False, 10)
        # fqi = 1.0 * 1.0 * 1.0 * (1 - 0.05*10) = 0.50
        # w_slippage * 1.0 + w_fill * 0.50 + w_latency * (1-1.0) = 0.40 + 0.175 + 0 = 0.575
        assert eis == pytest.approx(0.575, abs=0.01)

    def test_full_friction(self):
        eis = compute_eis(50.0, 50.0, 0.0, True, True, 10)
        # fqi = 0 * 0.5 * 0.7 * 0.5 = 0
        # eis = 0.40 * 0 + 0.35 * 0 + 0.25 * 0 = 0
        assert eis == 0.0

    def test_custom_weights(self):
        eis = compute_eis(10.0, 0.0, 1.0, False, False, 2, w_slippage=0.5, w_fill=0.3, w_latency=0.2)
        assert 0 < eis < 1


class TestComputeEisFromDf:
    def test_empty_df(self):
        assert compute_eis_from_df(pd.DataFrame()) == {}

    def test_missing_columns(self):
        df = pd.DataFrame({"asset": ["EURUSD"]})
        assert compute_eis_from_df(df) == {}

    def test_with_data(self):
        df = pd.DataFrame({
            "asset": ["EURUSD", "EURUSD", "EURUSD"],
            "friction_entry_slippage_bps": [1.0, 2.0, 3.0],
            "friction_fill_qty_ratio": [1.0, 0.9, 1.0],
            "friction_gap_fill": [False, False, False],
            "friction_partial_fill": [False, False, False],
            "friction_latency_bars": [0, 1, 0],
        })
        result = compute_eis_from_df(df, min_trades=3)
        assert "EURUSD" in result
        assert 0 < result["EURUSD"] <= 1

    def test_too_few_trades(self):
        df = pd.DataFrame({
            "asset": ["EURUSD"],
            "friction_entry_slippage_bps": [1.0],
            "friction_fill_qty_ratio": [1.0],
            "friction_gap_fill": [False],
            "friction_partial_fill": [False],
            "friction_latency_bars": [0],
        })
        assert compute_eis_from_df(df, min_trades=3) == {}
