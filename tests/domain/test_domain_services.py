from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.domain.services.pnl_service import DefaultPnLService, PnLService
from eigencapital.domain.services.signal_service import (
    FixedThresholdService,
    SignalService,
    _apply_threshold,
    generate_signal,
)
from eigencapital.domain.services.sizing_service import (
    _edge_decay,
    calculate_position_size,
    compute_equal_risk_weights,
    risk_contribution,
    risk_parity_weights,
)
from eigencapital.domain.services.volatility_service import __all__ as vol_all


class TestRiskContribution:
    def test_equal_weights_equal_risk(self):
        cov = np.array([[1.0, 0.5], [0.5, 1.0]])
        weights = np.array([0.5, 0.5])
        rc = risk_contribution(weights, cov)
        assert rc.shape == (2,)
        assert np.isclose(rc[0], rc[1], atol=1e-6)

    def test_single_asset(self):
        cov = np.array([[2.0]])
        weights = np.array([1.0])
        rc = risk_contribution(weights, cov)
        assert np.isclose(rc[0], 1.0)

    def test_unequal_weights(self):
        cov = np.array([[1.0, 0.0], [0.0, 4.0]])
        weights = np.array([0.8, 0.2])
        rc = risk_contribution(weights, cov)
        assert np.isclose(rc.sum(), 1.0)


class TestRiskParityWeights:
    def test_weights_sum_to_one(self):
        cov = np.array([[1.0, 0.3], [0.3, 1.0]])
        w = risk_parity_weights(cov)
        assert np.isclose(w.sum(), 1.0)
        assert np.all(w >= 0)

    def test_three_assets(self):
        cov = np.array([[1.0, 0.2, 0.1], [0.2, 1.0, 0.3], [0.1, 0.3, 1.0]])
        w = risk_parity_weights(cov)
        assert np.isclose(w.sum(), 1.0)
        assert w.shape == (3,)

    def test_with_target_risk(self):
        cov = np.eye(3)
        target = np.array([0.5, 0.3, 0.2])
        w = risk_parity_weights(cov, target_risk=target)
        assert np.isclose(w.sum(), 1.0)

    def test_uncorrelated_equal_weights(self):
        cov = np.eye(4)
        w = risk_parity_weights(cov)
        assert np.allclose(w, 0.25)


class TestComputeEqualRiskWeights:
    def test_returns_dict(self):
        dates = pd.date_range("2026-01-01", periods=100, freq="D")
        returns = pd.DataFrame(
            {"A": np.random.randn(100) * 0.01, "B": np.random.randn(100) * 0.02},
            index=dates,
        )
        w = compute_equal_risk_weights(returns)
        assert isinstance(w, dict)
        assert set(w.keys()) == {"A", "B"}
        assert np.isclose(sum(w.values()), 1.0)

    def test_single_column(self):
        returns = pd.DataFrame({"X": np.random.randn(50) * 0.01})
        w = compute_equal_risk_weights(returns)
        assert np.isclose(w["X"], 1.0)


class TestCalculatePositionSize:
    @pytest.fixture
    def close_series(self):
        return pd.Series(np.linspace(100, 110, 100))

    def test_default_no_regime(self, close_series):
        size = calculate_position_size(close_series, {"position_size": 0.95})
        assert 0 < size <= 0.95

    def test_regime_aware_bull(self, close_series):
        size_bull = calculate_position_size(close_series, {"position_size": 0.95}, regime="bull", regime_aware=True)
        assert size_bull > 0

    def test_regime_aware_bear(self, close_series):
        size_bear = calculate_position_size(close_series, {"position_size": 0.95}, regime="bear", regime_aware=True)
        assert size_bear > 0

    def test_regime_aware_crisis(self, close_series):
        size_crisis = calculate_position_size(close_series, {"position_size": 0.95}, regime="crisis", regime_aware=True)
        assert size_crisis > 0

    def test_short_window_falls_back(self):
        close = pd.Series(np.linspace(100, 110, 10))
        size = calculate_position_size(close, {"position_size": 0.5}, window=30)
        assert 0 < size <= 0.5

    def test_constant_price_zero_vol(self):
        close = pd.Series(np.ones(50) * 100.0)
        size = calculate_position_size(close, {"position_size": 0.8})
        assert size == 0.8


class TestEdgeDecay:
    def test_below_threshold(self):
        assert _edge_decay(3.0) == 1.0

    def test_at_threshold(self):
        assert _edge_decay(5.0) == 1.0

    def test_above_threshold(self):
        result = _edge_decay(10.0)
        assert result < 1.0
        assert result >= 0.5

    def test_large_impact_floor(self):
        result = _edge_decay(100.0)
        assert result == 0.5


class TestSignalService:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            SignalService()  # type: ignore[abstract]


class TestGenerateSignal:
    def test_1d_array_buy(self):
        proba = np.array([0.8, 0.7, 0.9])
        result = generate_signal(proba, threshold=0.6)
        assert result.signal_type.name == "BUY"
        assert result.label == 1

    def test_1d_array_sell(self):
        proba = np.array([0.2, 0.3, 0.1])
        result = generate_signal(proba, threshold=0.6)
        assert result.signal_type.name == "SELL"
        assert result.label == -1

    def test_1d_array_flat(self):
        proba = np.array([0.5, 0.55, 0.52])
        result = generate_signal(proba, threshold=0.6)
        assert result.signal_type.name == "FLAT"
        assert result.label == 0

    def test_2d_array_with_three_cols(self):
        proba = np.array([[0.1, 0.8, 0.1], [0.2, 0.7, 0.1]])
        result = generate_signal(proba, threshold=0.6)
        assert result.signal_type.name == "BUY"

    def test_2d_array_two_cols(self):
        proba = np.array([[0.3, 0.7], [0.2, 0.8]])
        result = generate_signal(proba, threshold=0.6)
        assert result.signal_type.name == "SELL"

    def test_signal_result_fields(self):
        proba = np.array([0.85])
        result = generate_signal(proba, threshold=0.6, position_size=0.5)
        assert result.confidence_pct == 0.85
        assert result.position_size == 0.5
        assert result.prob_long == 0.85
        assert result.prob_short == pytest.approx(0.15)


class TestApplyThreshold:
    def test_buy_above_threshold(self):
        st, conf = _apply_threshold(0.8, 0.1, 0.6)
        assert st.name == "BUY"
        assert conf == 0.8

    def test_sell_above_threshold(self):
        st, conf = _apply_threshold(0.2, 0.75, 0.6)
        assert st.name == "SELL"
        assert conf == 0.75

    def test_both_below_threshold(self):
        st, conf = _apply_threshold(0.4, 0.3, 0.6)
        assert st.name == "FLAT"
        assert conf == 0.4

    def test_buy_wins_tie(self):
        st, conf = _apply_threshold(0.7, 0.7, 0.6)
        assert st.name == "BUY"


class TestFixedThresholdService:
    def test_compute_delegates(self):
        svc = FixedThresholdService()
        proba = np.array([0.9])
        result = svc.compute(proba, threshold=0.6)
        assert result.signal_type.name == "BUY"
        assert result.confidence_pct == 0.9


class TestPnLService:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            PnLService()  # type: ignore[abstract]

    def test_default_simple(self):
        svc = DefaultPnLService()
        result = svc.compute_daily(10000.0, 1, 0.02, 0.5, 1.0)
        assert result == 100.0

    def test_default_short(self):
        svc = DefaultPnLService()
        result = svc.compute_daily(10000.0, -1, 0.02, 0.5, 1.0)
        assert result == -100.0

    def test_default_zero_pl(self):
        svc = DefaultPnLService()
        result = svc.compute_daily(10000.0, 1, 0.0, 1.0, 1.0)
        assert result == 0.0

    def test_default_half_size(self):
        svc = DefaultPnLService()
        result = svc.compute_daily(10000.0, 1, 0.01, 1.0, 0.5)
        assert result == 50.0


class TestVolatilityService:
    def test_re_exports_public_api(self):
        expected = [
            "compute_atr_series",
            "compute_atr_pct",
            "compute_latest_atr",
            "compute_latest_atr_pct",
            "estimate_gap_risk",
            "estimate_ewm_vol",
        ]
        for name in expected:
            assert name in vol_all
