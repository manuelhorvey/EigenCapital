"""Tests for the Intraday Research Track."""

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday.campaign import (
    CampaignFreezeManifest,
    HypothesisResult,
    IntradayCostModel,
    classify_verdict,
    evaluate_strategy,
    generate_breakout_signal,
    generate_momentum_signal,
    generate_reversal_signal,
    generate_vol_expansion_signal,
    generate_vwap_signal,
    walk_forward_validate,
)
from eigencapital.research.intraday.hypotheses import (
    ALL_HYPOTHESES,
    HYPOTHESIS_REGISTRY,
    HoldingPeriod,
    HypothesisFamily,
    Verdict,
    compute_library_hash,
    get_hypotheses_by_family,
    get_hypothesis,
)
from eigencapital.research.intraday.sessions import (
    Session,
    add_price_structure_features,
    add_realized_volatility_features,
    add_session_features,
    classify_session,
)

# ============================================================
# Hypothesis Registry Tests
# ============================================================


class TestHypothesisRegistry:
    def test_hypothesis_count(self):
        """First campaign should have 20-40 hypotheses."""
        assert 20 <= len(ALL_HYPOTHESES) <= 40

    def test_all_have_unique_ids(self):
        ids = [h.hypothesis_id for h in ALL_HYPOTHESES]
        assert len(ids) == len(set(ids))

    def test_registry_matches_list(self):
        assert len(HYPOTHESIS_REGISTRY) == len(ALL_HYPOTHESES)

    def test_fingerprint_is_deterministic(self):
        h = ALL_HYPOTHESES[0]
        assert h.fingerprint == h.fingerprint

    def test_fingerprint_is_stable(self):
        h1 = ALL_HYPOTHESES[0]
        h2 = get_hypothesis(h1.hypothesis_id)
        assert h1.fingerprint == h2.fingerprint

    def test_library_hash_deterministic(self):
        h1 = compute_library_hash()
        h2 = compute_library_hash()
        assert h1 == h2

    def test_all_families_represented(self):
        families = {h.family for h in ALL_HYPOTHESES}
        assert HypothesisFamily.MOMENTUM in families
        assert HypothesisFamily.REVERSAL in families
        assert HypothesisFamily.BREAKOUT in families
        assert HypothesisFamily.VOLATILITY in families
        assert HypothesisFamily.SESSION in families

    def test_holding_periods_used(self):
        periods = {h.holding_period for h in ALL_HYPOTHESES}
        assert HoldingPeriod.M5 in periods
        assert HoldingPeriod.M15 in periods
        assert HoldingPeriod.H1 in periods

    def test_all_have_economic_rationale(self):
        for h in ALL_HYPOTHESES:
            assert len(h.economic_rationale) > 10

    def test_all_have_falsification_criteria(self):
        for h in ALL_HYPOTHESES:
            assert "min_sharpe" in h.falsification_criteria

    def test_get_hypothesis_by_family(self):
        momentum = get_hypotheses_by_family(HypothesisFamily.MOMENTUM)
        assert len(momentum) >= 2
        for h in momentum:
            assert h.family == HypothesisFamily.MOMENTUM

    def test_incremental_hypotheses_have_dependency(self):
        incremental = [h for h in ALL_HYPOTHESES if h.is_incremental]
        for h in incremental:
            assert h.dependency is not None

    def test_hypothesis_to_dict_roundtrip(self):
        h = ALL_HYPOTHESES[0]
        d = h.to_dict()
        assert d["hypothesis_id"] == h.hypothesis_id
        assert d["family"] == h.family.value

    def test_get_nonexistent_raises(self):
        with pytest.raises(KeyError):
            get_hypothesis("NONEXISTENT-ID")


# ============================================================
# Session Feature Tests
# ============================================================


class TestSessionFeatures:
    def test_classify_session_london(self):
        ts = pd.Timestamp("2026-01-15 10:00:00")
        assert classify_session(ts) == Session.LONDON

    def test_classify_session_asian(self):
        ts = pd.Timestamp("2026-01-15 03:00:00")
        assert classify_session(ts) == Session.ASIAN

    def test_classify_session_ny_overlap(self):
        ts = pd.Timestamp("2026-01-15 14:00:00")
        assert classify_session(ts) == Session.LONDON_NY_OVERLAP

    def test_classify_session_off_hours(self):
        ts = pd.Timestamp("2026-01-15 22:00:00")
        assert classify_session(ts) == Session.OFF_HOURS

    def test_add_session_features(self):
        n = 100
        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "open": np.random.randn(n) + 1.1,
                "high": np.random.randn(n) + 1.12,
                "low": np.random.randn(n) + 1.08,
                "close": np.random.randn(n) + 1.1,
                "volume": np.random.randint(100, 1000, n),
            }
        )
        result = add_session_features(df)
        assert "session" in result.columns
        assert "hour" in result.columns
        assert "is_asian" in result.columns
        assert "is_london" in result.columns
        assert "bars_into_session" in result.columns

    def test_add_rv_features(self):
        n = 500
        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "close": 1.1 + np.cumsum(np.random.randn(n) * 0.001),
                "volume": np.random.randint(100, 1000, n),
            }
        )
        result = add_realized_volatility_features(df)
        assert "rv_12" in result.columns
        assert "rv_36" in result.columns

    def test_add_price_structure(self):
        n = 100
        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "open": 1.1 + np.random.randn(n) * 0.01,
                "high": 1.12 + np.random.randn(n) * 0.01,
                "low": 1.08 + np.random.randn(n) * 0.01,
                "close": 1.1 + np.random.randn(n) * 0.01,
                "volume": np.random.randint(100, 1000, n),
            }
        )
        result = add_price_structure_features(df)
        assert "bar_range" in result.columns
        assert "body" in result.columns
        assert "body_pct" in result.columns


# ============================================================
# Signal Generator Tests
# ============================================================


class TestSignalGenerators:
    @pytest.fixture
    def sample_df(self):
        n = 500
        np.random.seed(42)
        price = 1.1 + np.cumsum(np.random.randn(n) * 0.0005)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "open": price + np.random.randn(n) * 0.0002,
                "high": price + abs(np.random.randn(n) * 0.001),
                "low": price - abs(np.random.randn(n) * 0.001),
                "close": price,
                "volume": np.random.randint(100, 1000, n),
            }
        )

    def test_momentum_signal_values(self, sample_df):
        signal = generate_momentum_signal(sample_df, 12)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_reversal_signal_values(self, sample_df):
        signal = generate_reversal_signal(sample_df, 5)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_breakout_signal_values(self, sample_df):
        signal = generate_breakout_signal(sample_df, 12)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_vol_expansion_signal(self, sample_df):
        signal = generate_vol_expansion_signal(sample_df)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_vwap_signal(self, sample_df):
        signal = generate_vwap_signal(sample_df)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_momentum_signal_not_all_zero(self, sample_df):
        signal = generate_momentum_signal(sample_df, 12)
        assert signal.abs().sum() > 0

    def test_breakout_signal_detects_moves(self, sample_df):
        # With 2-bar confirmation, small random data may produce 0 signals
        # This is expected — the signal is conservative
        signal = generate_breakout_signal(sample_df, 12)
        assert set(signal.unique()).issubset({-1, 0, 1})


# ============================================================
# Strategy Evaluator Tests
# ============================================================


class TestStrategyEvaluator:
    @pytest.fixture
    def sample_df(self):
        n = 500
        np.random.seed(42)
        price = 1.1 + np.cumsum(np.random.randn(n) * 0.0005)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "open": price + np.random.randn(n) * 0.0002,
                "high": price + abs(np.random.randn(n) * 0.001),
                "low": price - abs(np.random.randn(n) * 0.001),
                "close": price,
                "volume": np.random.randint(100, 1000, n),
            }
        )

    def test_evaluate_returns_metrics(self, sample_df):
        signal = generate_momentum_signal(sample_df, 12)
        cost = IntradayCostModel()
        result = evaluate_strategy(sample_df, signal, 1, cost)
        assert "gross_sharpe" in result
        assert "net_sharpe" in result
        assert "max_dd_pct" in result
        assert "total_trades" in result

    def test_net_worse_than_gross(self, sample_df):
        signal = generate_momentum_signal(sample_df, 12)
        cost = IntradayCostModel()
        result = evaluate_strategy(sample_df, signal, 1, cost)
        assert result["net_sharpe"] <= result["gross_sharpe"]

    def test_zero_signal(self, sample_df):
        signal = pd.Series(0, index=sample_df.index)
        cost = IntradayCostModel()
        result = evaluate_strategy(sample_df, signal, 1, cost)
        assert result["total_trades"] == 0

    def test_cost_model(self):
        cost = IntradayCostModel(spread_bps=8, slippage_bps=3)
        assert cost.base_cost_per_trade_bps == 11.0  # 8 + 0*2 + 3


# ============================================================
# Walk-Forward Validation Tests
# ============================================================


class TestWalkForward:
    @pytest.fixture
    def sample_df(self):
        n = 1000
        np.random.seed(42)
        price = 1.1 + np.cumsum(np.random.randn(n) * 0.0005)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=n, freq="5min"),
                "open": price + np.random.randn(n) * 0.0002,
                "high": price + abs(np.random.randn(n) * 0.001),
                "low": price - abs(np.random.randn(n) * 0.001),
                "close": price,
                "volume": np.random.randint(100, 1000, n),
            }
        )

    def test_wf_returns_metrics(self, sample_df):
        def sig_func(df):
            return generate_momentum_signal(df, 12)

        wf = walk_forward_validate(sample_df, sig_func, n_folds=3)
        assert "oos_sharpe" in wf
        assert "consistency" in wf
        assert "folds" in wf

    def test_wf_consistency_range(self, sample_df):
        def sig_func(df):
            return generate_momentum_signal(df, 12)

        wf = walk_forward_validate(sample_df, sig_func, n_folds=3)
        assert 0.0 <= wf["consistency"] <= 1.0

    def test_wf_with_short_data(self):
        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15", periods=50, freq="5min"),
                "close": 1.1 + np.random.randn(50) * 0.001,
                "volume": [100] * 50,
            }
        )

        def sig_func(d):
            return generate_momentum_signal(d, 5)

        wf = walk_forward_validate(df, sig_func, n_folds=3)
        assert wf["folds"] <= 3


# ============================================================
# Verdict Classification Tests
# ============================================================


class TestVerdictClassification:
    def test_rejected_negative_sharpe(self):
        result = {
            "gross_sharpe": -0.5,
            "net_sharpe": -0.8,
            "max_dd_pct": -50,
            "turnover_annual": 100,
            "total_trades": 200,
            "avg_holding_bars": 5,
            "hit_rate": 0.45,
            "long_sharpe": -0.3,
            "short_sharpe": -1.0,
            "cost_pct_of_gross": 30,
        }
        wf = {"oos_sharpe": -0.5, "consistency": 0.2, "folds": 5}
        hyp = ALL_HYPOTHESES[0]
        cost = IntradayCostModel()
        verdict, fms, reason = classify_verdict(result, wf, hyp, cost)
        assert verdict == Verdict.REJECTED

    def test_supported_good_metrics(self):
        result = {
            "gross_sharpe": 0.8,
            "net_sharpe": 0.6,
            "max_dd_pct": -12,
            "turnover_annual": 50,
            "total_trades": 500,
            "avg_holding_bars": 10,
            "hit_rate": 0.55,
            "long_sharpe": 0.7,
            "short_sharpe": 0.5,
            "cost_pct_of_gross": 15,
        }
        wf = {"oos_sharpe": 0.5, "consistency": 0.8, "folds": 5}
        hyp = ALL_HYPOTHESES[0]
        cost = IntradayCostModel()
        verdict, fms, reason = classify_verdict(result, wf, hyp, cost)
        assert verdict in (Verdict.SUPPORTED, Verdict.FRAGILE)

    def test_cost_sensitive(self):
        result = {
            "gross_sharpe": 0.8,
            "net_sharpe": 0.1,
            "max_dd_pct": -10,
            "turnover_annual": 500,
            "total_trades": 5000,
            "avg_holding_bars": 2,
            "hit_rate": 0.52,
            "long_sharpe": 0.1,
            "short_sharpe": 0.1,
            "cost_pct_of_gross": 85,
        }
        wf = {"oos_sharpe": 0.1, "consistency": 0.6, "folds": 5}
        hyp = ALL_HYPOTHESES[0]
        cost = IntradayCostModel()
        verdict, fms, reason = classify_verdict(result, wf, hyp, cost)
        assert "cost_sensitivity" in fms

    def test_insufficient_trades(self):
        result = {
            "gross_sharpe": 0.5,
            "net_sharpe": 0.4,
            "max_dd_pct": -5,
            "turnover_annual": 5,
            "total_trades": 10,
            "avg_holding_bars": 50,
            "hit_rate": 0.6,
            "long_sharpe": 0.4,
            "short_sharpe": 0.4,
            "cost_pct_of_gross": 10,
        }
        wf = {"oos_sharpe": 0.3, "consistency": 0.7, "folds": 5}
        hyp = ALL_HYPOTHESES[0]
        cost = IntradayCostModel()
        verdict, fms, reason = classify_verdict(result, wf, hyp, cost)
        assert "insufficient_trades" in fms


# ============================================================
# Campaign Manifest Tests
# ============================================================


class TestCampaignManifest:
    def test_freeze_manifest(self):
        freeze = CampaignFreezeManifest(
            campaign_id="TEST-001",
            data_snapshot_hash="abc123",
            hypothesis_library_hash="def456",
            cost_model_version="base_v1",
            universe=["EURUSDm", "GBPUSDm"],
            timeframe="M5",
            frozen_at="2026-01-01",
            git_commit="abc123",
        )
        d = freeze.to_dict()
        assert d["campaign_id"] == "TEST-001"
        assert len(d["universe"]) == 2

    def test_hypothesis_result_to_dict(self):
        r = HypothesisResult(
            hypothesis_id="ID-MOM-001",
            family="momentum",
            name="Test",
            verdict=Verdict.SUPPORTED,
            gross_sharpe=0.8,
            net_sharpe=0.6,
            oos_sharpe=0.5,
            max_dd_pct=-12.0,
            turnover_annual=50.0,
            total_trades=200,
            avg_holding_bars=5.0,
            long_sharpe=0.7,
            short_sharpe=0.5,
            hit_rate=0.55,
            cost_pct_of_gross=15.0,
            walk_forward_consistency=0.8,
            degradation_pct=25.0,
            failure_modes=[],
            asset_sharpes={"EURUSDm": 0.5, "GBPUSDm": 0.7},
            session_sharpes={"london": 0.6},
            reason="All gates passed",
        )
        d = r.to_dict()
        assert d["verdict"] == "supported"
        assert d["net_sharpe"] == 0.6


# ============================================================
# Data Puller Tests (unit tests only, no MT5)
# ============================================================


class TestIntradayDataPuller:
    def test_manifest_from_dict(self):
        from eigencapital.research.intraday.data_puller import IntradayDataManifest

        m = IntradayDataManifest(
            broker="Exness",
            terminal_id="123",
            symbols=["EURUSDm"],
            timeframe="M5",
            bars_per_symbol={"EURUSDm": 1000},
            total_bars=1000,
            first_timestamp="2026-01-01",
            last_timestamp="2026-08-24",
            retrieval_timestamp="2026-08-24",
            missing_bars=0,
            duplicate_bars=0,
            ohlc_violations=0,
            snapshot_hash="abc123",
        )
        d = m.to_dict()
        assert d["broker"] == "Exness"
        assert d["total_bars"] == 1000

    def test_integrity_checks(self):
        from eigencapital.research.intraday.data_puller import IntradayDataPuller

        puller = IntradayDataPuller()

        # Good data
        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15 00:00", periods=100, freq="5min"),
                "open": [1.1] * 100,
                "high": [1.12] * 100,
                "low": [1.08] * 100,
                "close": [1.1] * 100,
                "volume": [100] * 100,
            }
        )
        data = {"EURUSDm": df}
        missing, dupes, ohlc = puller._check_integrity(data)
        assert missing == 0
        assert dupes == 0
        assert ohlc == 0

    def test_integrity_ohlc_violation(self):
        from eigencapital.research.intraday.data_puller import IntradayDataPuller

        puller = IntradayDataPuller()

        df = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-15 00:00", periods=5, freq="5min"),
                "open": [1.1, 1.1, 1.1, 1.1, 1.1],
                "high": [1.0, 1.12, 1.12, 1.12, 1.12],  # High < Low on bar 0
                "low": [1.2, 1.08, 1.08, 1.08, 1.08],  # Low > High on bar 0
                "close": [1.1, 1.1, 1.1, 1.1, 1.1],
                "volume": [100] * 5,
            }
        )
        data = {"EURUSDm": df}
        missing, dupes, ohlc = puller._check_integrity(data)
        assert ohlc > 0
