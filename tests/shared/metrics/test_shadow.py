"""Tests for shared/metrics/shadow.py."""

from __future__ import annotations

import pytest

from shared.metrics.shadow import compute_r_delta_distribution, compute_shadow_divergence


class TestComputeShadowDivergence:
    def test_empty_records(self):
        result = compute_shadow_divergence([])
        assert result["n"] == 0
        assert result["divergence_rate"] == 0.0

    def test_no_divergence(self):
        result = compute_shadow_divergence(
            [
                {
                    "exit_reason": "TP",
                    "live_exit_reason": "TP",
                    "realized_r": 2.0,
                    "live_realized_r": 2.0,
                    "alt_label": "baseline",
                }
            ]
        )
        assert result["overall"]["divergence_rate"] == 0.0
        assert result["overall"]["n"] == 1

    def test_full_divergence(self):
        result = compute_shadow_divergence(
            [
                {
                    "exit_reason": "TP",
                    "live_exit_reason": "SL",
                    "realized_r": 2.0,
                    "live_realized_r": -1.0,
                    "alt_label": "tight",
                }
            ]
        )
        assert result["overall"]["divergence_rate"] == 1.0

    def test_by_label_breakdown(self):
        result = compute_shadow_divergence(
            [
                {
                    "exit_reason": "TP",
                    "live_exit_reason": "TP",
                    "realized_r": 2.0,
                    "live_realized_r": 2.0,
                    "alt_label": "baseline",
                },
                {
                    "exit_reason": "SL",
                    "live_exit_reason": "TP",
                    "realized_r": -1.0,
                    "live_realized_r": 2.0,
                    "alt_label": "tight",
                },
            ]
        )
        assert "by_label" in result
        assert "baseline" in result["by_label"]
        assert "tight" in result["by_label"]


class TestComputeRDeltaDistribution:
    def test_empty_records(self):
        result = compute_r_delta_distribution([])
        assert result["histogram"] == []
        assert result["outliers"]["n_gt_1"] == 0

    def test_histogram_output(self):
        result = compute_r_delta_distribution(
            [
                {"realized_r": 2.0, "live_realized_r": 1.0},
                {"realized_r": 1.0, "live_realized_r": 2.0},
                {"realized_r": 3.0, "live_realized_r": 1.0},
            ]
        )
        assert len(result["histogram"]) > 0
        assert "quartiles" in result
        assert "q1" in result["quartiles"]
        assert "median" in result["quartiles"]
