"""Tests for shared/kelly.py — Fractional Kelly sizing."""

from __future__ import annotations

import pytest

from shared.kelly import (
    compute_edge,
    compute_kelly_fraction,
    compute_kelly_multiplier,
    compute_kelly_size,
    edge_description,
)


class TestComputeEdge:
    def test_positive_edge(self):
        edge = compute_edge(0.6, tp_mult=2.0, sl_mult=1.0)
        assert edge == pytest.approx(0.6 * 2.0 - 0.4 * 1.0)

    def test_negative_edge(self):
        edge = compute_edge(0.3, tp_mult=2.0, sl_mult=1.0)
        assert edge < 0

    def test_zero_edge(self):
        edge = compute_edge(1 / 3, tp_mult=2.0, sl_mult=1.0)
        assert edge == pytest.approx(0.0, abs=1e-10)

    def test_edge_tp_only(self):
        edge = compute_edge(0.5, tp_mult=1.0, sl_mult=0.0)
        assert edge == pytest.approx(0.5)

    def test_edge_boundaries(self):
        assert compute_edge(0.0, 2.0, 1.0) == -1.0
        assert compute_edge(1.0, 2.0, 1.0) == 2.0


class TestComputeKellyFraction:
    def test_fair_coin_no_edge(self):
        f = compute_kelly_fraction(0.5, tp_mult=1.0, sl_mult=1.0)
        assert f == 0.0

    def test_known_edge(self):
        f = compute_kelly_fraction(0.6, tp_mult=2.0, sl_mult=1.0)
        # f* = p - q * sl/tp = 0.6 - 0.4 * 1/2 = 0.6 - 0.2 = 0.4
        assert f == pytest.approx(0.4)

    def test_full_kelly_binary(self):
        p = 0.55
        tp = 1.0
        sl = 1.0
        f = compute_kelly_fraction(p, tp, sl)
        # f* = 2p - 1 = 0.1
        assert f == pytest.approx(0.1)

    def test_fraction_never_negative(self):
        assert compute_kelly_fraction(0.1, 2.0, 1.0) >= 0
        assert compute_kelly_fraction(0.0, 2.0, 1.0) >= 0

    def test_high_confidence(self):
        f = compute_kelly_fraction(0.9, tp_mult=2.0, sl_mult=1.0)
        assert f > 0.5

    def test_extreme_sl_mult(self):
        f = compute_kelly_fraction(0.9, tp_mult=1.0, sl_mult=5.0)
        # edge = 0.9*1 - 0.1*5 = 0.9 - 0.5 = 0.4
        # b = 1/5 = 0.2
        # f* = (0.2 * 0.9 - 0.1) / 0.2 = (0.18 - 0.1) / 0.2 = 0.4
        assert f == pytest.approx(0.4)

    def test_kelly_property(self):
        """Kelly fraction is increasing in both p and tp/sl ratio."""
        base = compute_kelly_fraction(0.55, 2.0, 1.0)
        higher_p = compute_kelly_fraction(0.65, 2.0, 1.0)
        better_odds = compute_kelly_fraction(0.55, 3.0, 1.0)
        assert higher_p > base
        assert better_odds > base

    def test_boundary_values(self):
        assert compute_kelly_fraction(0.0, 2.0, 1.0) == 0.0
        assert compute_kelly_fraction(1.0, 2.0, 1.0) == 0.0  # degenerate

    def test_prob_too_wide(self):
        assert compute_kelly_fraction(-0.1, 2.0, 1.0) == 0.0
        assert compute_kelly_fraction(1.5, 2.0, 1.0) == 0.0


class TestComputeKellyMultiplier:
    def test_quarter_kelly(self):
        m = compute_kelly_multiplier(0.6, 2.0, 1.0, fraction=0.25)
        # Full Kelly = 0.4, quarter = 0.1
        assert m == pytest.approx(0.4 * 0.25)

    def test_half_kelly(self):
        m = compute_kelly_multiplier(0.6, 2.0, 1.0, fraction=0.5)
        assert m == pytest.approx(0.4 * 0.5)

    def test_no_edge_returns_zero(self):
        m = compute_kelly_multiplier(0.5, 1.0, 1.0)
        assert m == 0.0

    def test_min_edge_blocks(self):
        m = compute_kelly_multiplier(0.55, 1.0, 1.0, min_edge=0.2)
        # edge = 0.1, min_edge = 0.2 -> blocked
        assert m == 0.0

    def test_max_cap(self):
        m = compute_kelly_multiplier(0.95, 3.0, 1.0, max_cap=0.5)
        assert m <= 0.5

    def test_zero_prob(self):
        assert compute_kelly_multiplier(0.0, 2.0, 1.0) == 0.0

    def test_one_prob(self):
        assert compute_kelly_multiplier(1.0, 2.0, 1.0) == 0.0


class TestComputeKellySize:
    def test_simple_adjustment(self):
        size = compute_kelly_size(10000, 0.6, 2.0, 1.0, fraction=0.25, max_cap=0.5)
        # Kelly multiplier = 0.4 * 0.25 = 0.1, adjusted = 1000
        assert size == pytest.approx(1000.0)

    def test_zero_base_size(self):
        size = compute_kelly_size(0, 0.6, 2.0, 1.0)
        assert size == 0.0

    def test_no_edge_skips(self):
        size = compute_kelly_size(10000, 0.5, 1.0, 1.0)
        assert size == 0.0

    def test_max_cap_limits(self):
        size = compute_kelly_size(10000, 0.99, 5.0, 1.0, max_cap=0.3)
        assert size <= 3000.0  # 10000 * 0.3


class TestEdgeDescription:
    def test_output_format(self):
        desc = edge_description(0.6, 2.0, 1.0)
        assert "edge=" in desc
        assert "kelly_f=" in desc
        assert "prob=" in desc
        assert "tp=" in desc
        assert "sl=" in desc

    def test_no_edge(self):
        desc = edge_description(0.5, 1.0, 1.0)
        assert "0.0000" in desc


class TestKellyProperties:
    def test_monotonic_in_prob(self):
        """Higher probability should never give smaller size."""
        sizes = [compute_kelly_size(1, p, 2.0, 1.0, fraction=1.0) for p in [0.51, 0.55, 0.60, 0.70, 0.80, 0.90]]
        for i in range(len(sizes) - 1):
            assert sizes[i] <= sizes[i + 1] or (sizes[i] == 0 and sizes[i + 1] == 0)

    def test_monotonic_in_tp(self):
        """Higher tp_mult should never give smaller size."""
        sizes = [compute_kelly_size(1, 0.55, tp, 1.0, fraction=1.0) for tp in [1.0, 1.5, 2.0, 3.0, 5.0]]
        for i in range(len(sizes) - 1):
            assert sizes[i] <= sizes[i + 1] or sizes[i + 1] == 0

    def test_kelly_never_exceeds_max_cap(self):
        for prob in [0.51, 0.6, 0.7, 0.8, 0.9, 0.99]:
            m = compute_kelly_multiplier(prob, 2.0, 1.0, max_cap=0.4)
            assert m <= 0.4, f"Kelly {m} exceeds max_cap for prob={prob}"

    def test_kelly_never_negative(self):
        for prob in [0.0, 0.1, 0.3, 0.5, 0.7, 1.0]:
            m = compute_kelly_multiplier(prob, 2.0, 1.0)
            assert m >= 0, f"Kelly negative for prob={prob}"
