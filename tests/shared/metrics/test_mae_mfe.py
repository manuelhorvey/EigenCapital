"""Tests for shared/metrics/mae_mfe.py."""

from __future__ import annotations

import pytest

from shared.metrics.mae_mfe import compute_mae_mfe_stats, normalize_mae_mfe


class TestNormalizeMaeMfe:
    def test_price_normalization(self):
        result = normalize_mae_mfe(mae=1.0, mfe=3.0, entry_price=100.0)
        assert result["mae_pct"] == pytest.approx(0.01)
        assert result["mfe_pct"] == pytest.approx(0.03)
        assert result["mfe_mae_ratio"] == pytest.approx(3.0)

    def test_atr_normalization(self):
        result = normalize_mae_mfe(mae=1.0, mfe=2.0, entry_price=100.0, atr_at_entry=2.0)
        assert "mae_atr" in result
        assert result["mae_atr"] == pytest.approx(0.50)
        assert result["mfe_atr"] == pytest.approx(1.0)

    def test_zero_entry_price(self):
        result = normalize_mae_mfe(mae=1.0, mfe=2.0, entry_price=0.0)
        assert result["mae_pct"] == 0.0
        assert result["mfe_mae_ratio"] == 0.0

    def test_zero_atr_falls_back_to_price(self):
        result = normalize_mae_mfe(mae=1.0, mfe=2.0, entry_price=100.0, atr_at_entry=0.0)
        assert "mae_pct" in result  # falls back to price-based
        assert "mae_atr" not in result


class TestComputeMaeMfeStats:
    def test_empty_records(self):
        result = compute_mae_mfe_stats([])
        assert result["overall"]["n"] == 0

    def test_single_trade(self):
        result = compute_mae_mfe_stats(
            [
                {
                    "exit_mae": 1.0,
                    "exit_mfe": 3.0,
                    "entry_price": 100.0,
                    "exit_exit_reason": "tp",
                }
            ]
        )
        assert result["overall"]["n"] == 1
        assert result["overall"]["avg_mfe_mae_ratio"] > 0

    def test_with_archetype_and_regime(self):
        result = compute_mae_mfe_stats(
            [
                {
                    "exit_mae": 0.5,
                    "exit_mfe": 2.0,
                    "entry_price": 100.0,
                    "exit_exit_reason": "tp",
                    "pred_archetype_at_entry": "BREAKOUT",
                    "pred_regime_at_entry": "GREEN",
                }
            ]
        )
        assert "BREAKOUT" in result["by_archetype"]
        assert "GREEN" in result["by_regime"]
