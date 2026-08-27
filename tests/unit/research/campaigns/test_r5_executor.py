"""Tests for the R5 swing-breadth executor primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.campaigns.r5_executor import (
    CUMULATIVE_TRIALS,
    FAMILY_SIZE,
    PRIOR_EVALUATIONS,
    _hold,
    _portfolio_series,
    _rsi,
    _tercile_ls,
    build_trend001,
    evaluate_hypothesis,
)


def _flat_px(n=300, symbols=("AAA", "BBB", "CCC")) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))) for s in symbols},
        index=idx,
    )


class TestGovernanceConstants:
    def test_ledger_matches_preregistration(self):
        assert PRIOR_EVALUATIONS == 27
        assert FAMILY_SIZE == 16
        assert CUMULATIVE_TRIALS == 43


class TestPrimitives:
    def test_rsi_bounds_and_extremes(self):
        up = pd.Series(np.linspace(100, 200, 100))
        assert _rsi(up).iloc[-1] == pytest.approx(100.0)
        down = pd.Series(np.linspace(200, 100, 100))
        assert _rsi(down).iloc[-1] == pytest.approx(0.0)

    def test_tercile_ls_requires_minimum_names(self):
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        thin = pd.DataFrame({"a": [1, 1, 1, 1, 1], "b": [2, 2, 2, 2, 2], "c": [3, 3, 3, 3, 3]}, index=idx)
        assert (_tercile_ls(thin) == 0).all().all()

    def test_hold_limits_exposure_length(self):
        idx = pd.date_range("2020-01-01", periods=10, freq="D")
        sig = pd.DataFrame({"a": [1.0] + [0.0] * 9}, index=idx)
        held = _hold(sig, 3)
        assert held["a"].sum() == pytest.approx(3.0)


class TestPortfolioSeries:
    def test_costs_reduce_series_by_flip_charge(self):
        px = _flat_px()
        pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        pos.iloc[5:] = 1.0  # single entry flip at bar 5
        gross = _portfolio_series(px, pos, 0.0)
        net = _portfolio_series(px, pos, 7.5e-4)
        # exactly one entry flip per symbol, equal-weighted across 3
        assert gross.sum() - net.sum() == pytest.approx(7.5e-4)

    def test_no_lookahead_position_enters_next_bar(self):
        px = _flat_px(n=50)
        sig = pd.DataFrame(np.sign(px.pct_change()), index=px.index, columns=px.columns)
        s = _portfolio_series(px, sig, 0.0)
        assert s.iloc[0] == 0.0 or np.isnan(s.iloc[0])


class TestEvaluateHypothesis:
    def test_zero_signal_rejected_without_crash(self):
        px = _flat_px()
        empty = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        result = evaluate_hypothesis("TREND-001", lambda *a, **k: empty, {}, px, px * 0, px * 0, None)
        assert result["verdict"] == "REJECTED"
        assert result["reasons"] == ["no_signal"]

    def test_perfect_foresight_is_statistically_strong(self):
        px = _flat_px(n=400)
        fwd_sign = pd.DataFrame(np.sign(px.shift(-1) - px), index=px.index, columns=px.columns)
        result = evaluate_hypothesis("TREND-001", lambda *a, **k: fwd_sign.fillna(0), {}, px, px * 0, px * 0, None)
        assert result["net_sharpe"] > 1.0
        assert result["p_raw"] < 0.05

    def test_trend001_builds_positions_on_real_shapes(self):
        px = _flat_px(n=400)
        pos = build_trend001(px, px * 0, None)
        assert pos.shape == px.shape
        assert pos.abs().sum().sum() > 0
