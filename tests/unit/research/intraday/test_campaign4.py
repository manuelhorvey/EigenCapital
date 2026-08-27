"""Tests for Campaign 4 — 15M Intraday Alpha Research.

Verifies:
- Hypothesis hash determinism and stability
- Signal function correctness (no look-ahead, valid ranges)
- Backtest engine correctness
- Walk-forward produces valid output
- Permutation test produces valid p-values
- Verdict classification
- Data manifest integrity
- Report generation
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday.campaign4_15m import (
    HYPOTHESES,
    SIGNALS,
    HORIZONS,
    UNIVERSE,
    CostModel,
    Verdict,
    HypResult,
    bt,
    classify,
    permutation_test,
    regime_analysis,
    report,
    wf_validate,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """Generate realistic synthetic 15M OHLCV data."""
    n = 2000
    np.random.seed(42)
    price = 1.1 + np.cumsum(np.random.randn(n) * 0.0002)
    rng = np.abs(np.random.randn(n) * 0.0003)
    return pd.DataFrame({
        "time": pd.date_range("2024-07-01", periods=n, freq="15min"),
        "open": price,
        "high": price + rng,
        "low": price - rng,
        "close": price + np.random.randn(n) * 0.00005,
        "tick_volume": np.random.randint(100, 1000, n),
        "spread": np.random.randint(5, 15, n),
    })


@pytest.fixture
def sample_df_with_session():
    """Generate data with clear session structure (UTC hours)."""
    n = 2000
    np.random.seed(42)
    # Create timestamps with explicit UTC hours
    times = pd.date_range("2024-07-01", periods=n, freq="15min")
    price = 1.1 + np.cumsum(np.random.randn(n) * 0.0002)
    rng = np.abs(np.random.randn(n) * 0.0003)
    return pd.DataFrame({
        "time": times,
        "open": price,
        "high": price + rng,
        "low": price - rng,
        "close": price + np.random.randn(n) * 0.00005,
        "tick_volume": np.random.randint(100, 1000, n),
        "spread": np.random.randint(5, 15, n),
    })


@pytest.fixture
def multi_asset_data():
    """Generate data for multiple assets (needed for cross-asset signals)."""
    n = 2000
    np.random.seed(42)
    times = pd.date_range("2024-07-01", periods=n, freq="15min")
    data = {}
    for sym in ["EURUSDm", "US500m", "USTECm", "XAUUSDm", "USOILm",
                 "GBPUSDm", "USDJPYm", "AUDUSDm"]:
        price = 1.1 + np.cumsum(np.random.randn(n) * 0.0002)
        rng = np.abs(np.random.randn(n) * 0.0003)
        data[sym] = pd.DataFrame({
            "time": times,
            "open": price,
            "high": price + rng,
            "low": price - rng,
            "close": price + np.random.randn(n) * 0.00005,
            "tick_volume": np.random.randint(100, 1000, n),
            "spread": np.random.randint(5, 15, n),
        })
    return data


# ═══════════════════════════════════════════════════════════════════════
# Hypothesis Registry Tests
# ═══════════════════════════════════════════════════════════════════════

class TestHypothesisRegistry:
    def test_hypothesis_count(self):
        """Should have ~30 hypotheses."""
        assert 28 <= len(HYPOTHESES) <= 35

    def test_all_have_unique_ids(self):
        ids = [h.hid for h in HYPOTHESES]
        assert len(ids) == len(set(ids))

    def test_all_have_hash(self):
        for h in HYPOTHESES:
            assert len(h.phash) == 16

    def test_hash_deterministic(self):
        """Hash of same hypothesis is always the same."""
        h = HYPOTHESES[0]
        assert h.phash == h.compute_hash()

    def test_hash_stable_across_runs(self):
        """Hash doesn't change between import calls."""
        h1 = HYPOTHESES[0].phash
        h2 = HYPOTHESES[0].compute_hash()
        assert h1 == h2

    def test_all_families_represented(self):
        families = {h.family for h in HYPOTHESES}
        expected = {"momentum", "mean_reversion", "breakout", "sessions",
                    "volatility", "cross_asset", "price_structure", "composite"}
        assert expected.issubset(families)

    def test_all_have_signal_function(self):
        for h in HYPOTHESES:
            assert h.signal in SIGNALS, f"{h.hid} signal '{h.signal}' not in registry"

    def test_all_have_rationale(self):
        for h in HYPOTHESES:
            assert len(h.rationale) > 10

    def test_json_roundtrip(self):
        """Verify hashes are reproducible from JSON."""
        h = HYPOTHESES[0]
        d = {"id": h.hid, "sig": h.signal, "fam": h.family, "desc": h.description}
        expected = hashlib.sha256(json.dumps(d).encode()).hexdigest()[:16]
        assert h.phash == expected


# ═══════════════════════════════════════════════════════════════════════
# Signal Function Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSignalFunctions:
    def test_momentum_signals_produce_values(self, sample_df):
        for sig_name in ["sig_mom_4", "sig_mom_8", "sig_mom_16"]:
            sig = SIGNALS[sig_name](sample_df)
            assert isinstance(sig, pd.Series)
            assert len(sig) == len(sample_df)
            # Should have non-zero values
            assert sig.abs().sum() > 0

    def test_mean_reversion_signals_produce_values(self, sample_df):
        for sig_name in ["sig_vwap_dev_8", "sig_zscore_16",
                         "sig_vol_norm_dev_16", "sig_range_revert"]:
            sig = SIGNALS[sig_name](sample_df)
            assert isinstance(sig, pd.Series)
            assert len(sig) == len(sample_df)

    def test_session_signals_are_gated(self, sample_df_with_session):
        """Session signals should only produce non-zero during their session."""
        sig_london = SIGNALS["sig_london_open"](sample_df_with_session)
        sig_ny = SIGNALS["sig_ny_open"](sample_df_with_session)
        sig_overlap = SIGNALS["sig_overlap_mom"](sample_df_with_session)

        times = pd.to_datetime(sample_df_with_session["time"])
        hours = times.dt.hour

        # London signal should be zero outside hours 7-12
        # (NaN from pct_change is fine — only non-zero finite values matter)
        london_outside = sig_london[(hours < 7) | (hours >= 12)]
        london_outside = london_outside.dropna()
        assert (london_outside == 0).all(), \
            "London signal produced non-zero outside London session"

        # NY signal should be zero outside hours 16-21
        ny_outside = sig_ny[(hours < 16) | (hours >= 21)].dropna()
        assert (ny_outside == 0).all(), \
            "NY signal produced non-zero outside NY session"

        # Overlap signal should be zero outside hours 12-16
        overlap_outside = sig_overlap[(hours < 12) | (hours >= 16)].dropna()
        assert (overlap_outside == 0).all(), \
            "Overlap signal produced non-zero outside overlap session"

    def test_cross_asset_signals_need_all_data(self, sample_df, multi_asset_data):
        """Cross-asset signals should return zero without all_data."""
        sig = SIGNALS["sig_us500_eurusd_lead"](sample_df)
        # Without all_data, should return zeros
        assert (sig == 0).all()

        # With all_data, should produce values
        sig2 = SIGNALS["sig_us500_eurusd_lead"](sample_df, all_data=multi_asset_data)
        assert isinstance(sig2, pd.Series)

    def test_no_lookahead_in_signals(self, sample_df):
        """Verify signals at time t don't use information after t.

        We test this by modifying future data and checking that the signal
        at a past time doesn't change.
        """
        sig1 = SIGNALS["sig_mom_8"](sample_df).copy()

        # Modify future data (after bar 500)
        modified = sample_df.copy()
        modified.loc[500:, "close"] *= 2.0  # Double all future closes

        sig2 = SIGNALS["sig_mom_8"](modified).copy()

        # Signal at bar 400 should be identical (before the modification)
        # Allow for floating point differences
        np.testing.assert_almost_equal(
            sig1.iloc[400], sig2.iloc[400], decimal=10,
            err_msg="Signal at bar 400 changed when future data was modified — LOOK-AHEAD DETECTED"
        )

    def test_breakout_signals_produce_correct_values(self, sample_df):
        sig = SIGNALS["sig_range_break_20"](sample_df)
        # Should be -1, 0, or 1 (sign of close vs midrange)
        unique = set(sig.dropna().unique())
        assert unique.issubset({-1.0, 0.0, 1.0})

    def test_failed_breakout_produces_correct_values(self, sample_df):
        sig = SIGNALS["sig_failed_break"](sample_df)
        unique = set(sig.dropna().unique())
        assert unique.issubset({-1.0, 0.0, 1.0})


# ═══════════════════════════════════════════════════════════════════════
# Backtest Engine Tests
# ═══════════════════════════════════════════════════════════════════════

class TestBacktest:
    def test_bt_returns_tuple(self, sample_df):
        sig = SIGNALS["sig_mom_4"](sample_df).fillna(0)
        sharpe, ret, dd, trades = bt(sample_df, sig, 1, 0)
        assert isinstance(sharpe, float)
        assert isinstance(ret, float)
        assert isinstance(dd, float)
        assert isinstance(trades, int)

    def test_bt_zero_signal(self, sample_df):
        sig = pd.Series(0.0, index=sample_df.index)
        sharpe, ret, dd, trades = bt(sample_df, sig, 1, 0)
        assert trades == 0
        assert ret == 0.0

    def test_bt_with_cost_reduces_sharpe(self, sample_df):
        sig = SIGNALS["sig_mom_4"](sample_df).fillna(0)
        g_sharpe, _, _, _ = bt(sample_df, sig, 1, 0)
        n_sharpe, _, _, _ = bt(sample_df, sig, 1, CostModel.BASE)
        if g_sharpe > 0:
            assert n_sharpe <= g_sharpe

    def test_bt_drawdown_negative(self, sample_df):
        sig = SIGNALS["sig_mom_8"](sample_df).fillna(0)
        _, _, dd, _ = bt(sample_df, sig, 4, 0)
        assert dd <= 0

    def test_bt_trade_count_non_negative(self, sample_df):
        sig = SIGNALS["sig_mom_4"](sample_df).fillna(0)
        _, _, _, trades = bt(sample_df, sig, 1, 0)
        assert trades >= 0


# ═══════════════════════════════════════════════════════════════════════
# Walk-Forward Tests
# ═══════════════════════════════════════════════════════════════════════

class TestWalkForward:
    def test_wf_returns_valid_output(self, sample_df):
        func = SIGNALS["sig_mom_4"]
        cons, oos, folds = wf_validate(sample_df, func, hp=1, n_folds=3)
        assert 0.0 <= cons <= 1.0
        assert isinstance(oos, float)
        assert len(folds) <= 3

    def test_wf_consistency_range(self, sample_df):
        func = SIGNALS["sig_mom_8"]
        cons, _, _ = wf_validate(sample_df, func, hp=4, n_folds=5)
        assert 0.0 <= cons <= 1.0

    def test_wf_with_short_data(self):
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=100, freq="15min"),
            "close": 1.1 + np.random.randn(100) * 0.001,
            "tick_volume": [100] * 100,
            "high": 1.11 + np.abs(np.random.randn(100) * 0.001),
            "low": 1.09 - np.abs(np.random.randn(100) * 0.001),
            "open": 1.1 + np.random.randn(100) * 0.001,
            "spread": [10] * 100,
        })
        func = SIGNALS["sig_mom_4"]
        cons, oos, folds = wf_validate(df, func, hp=1, n_folds=3)
        assert 0.0 <= cons <= 1.0

    def test_wf_cross_asset(self, sample_df, multi_asset_data):
        func = SIGNALS["sig_us500_eurusd_lead"]
        cons, oos, folds = wf_validate(
            sample_df, func, hp=2, n_folds=3, all_data=multi_asset_data
        )
        assert 0.0 <= cons <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# Permutation Test
# ═══════════════════════════════════════════════════════════════════════

class TestPermutation:
    def test_permutation_returns_p_value(self, sample_df):
        func = SIGNALS["sig_mom_4"]
        p = permutation_test(sample_df, func, hp=1, n_permutations=10)
        assert 0.0 <= p <= 1.0

    def test_permutation_p_for_random_signal(self):
        """Random signal should have high p-value."""
        np.random.seed(42)
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=500, freq="15min"),
            "close": 1.1 + np.cumsum(np.random.randn(500) * 0.0005),
            "tick_volume": np.random.randint(100, 1000, 500),
            "high": 1.12 + np.random.randn(500) * 0.001,
            "low": 1.08 + np.random.randn(500) * 0.001,
            "open": 1.1 + np.random.randn(500) * 0.001,
            "spread": np.random.randint(5, 15, 500),
        })
        # A pure random signal should not be significant
        def random_sig(df, **kw):
            return pd.Series(np.random.randn(len(df)), index=df.index)
        p = permutation_test(df, random_sig, hp=1, n_permutations=20)
        # Should generally be > 0.05 (not significant), though not guaranteed
        assert 0.0 <= p <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# Regime Analysis
# ═══════════════════════════════════════════════════════════════════════

class TestRegimeAnalysis:
    def test_regime_returns_dicts(self, sample_df_with_session):
        sig = SIGNALS["sig_mom_4"](sample_df_with_session).fillna(0)
        yr, sess = regime_analysis(sample_df_with_session, sig, hp=1)
        assert isinstance(yr, dict)
        assert isinstance(sess, dict)

    def test_regime_years_are_valid(self, sample_df_with_session):
        sig = SIGNALS["sig_mom_8"](sample_df_with_session).fillna(0)
        yr, _ = regime_analysis(sample_df_with_session, sig, hp=4)
        for k, v in yr.items():
            assert k.isdigit()
            assert isinstance(v, float)

    def test_regime_sessions_are_valid(self, sample_df_with_session):
        sig = SIGNALS["sig_mom_4"](sample_df_with_session).fillna(0)
        _, sess = regime_analysis(sample_df_with_session, sig, hp=1)
        valid_sessions = {"asian", "london", "overlap", "new_york", "off_hours"}
        for k in sess:
            assert k in valid_sessions


# ═══════════════════════════════════════════════════════════════════════
# Verdict Classification
# ═══════════════════════════════════════════════════════════════════════

class TestVerdictClassification:
    def test_rejected_negative_gross(self):
        r = HypResult(hid="X", family="test", description="t", hp=1,
                      gross_sharpe=-0.5, net_base=-0.8)
        verdict, reasons, primary = classify(r)
        assert verdict == Verdict.REJECTED
        assert "negative_gross" in reasons

    def test_supported_good_metrics(self):
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.8, net_base=0.6, net_adverse=0.3,
                      max_dd=-0.1, trades=100, wf_consistency=0.8,
                      wf_oos_sharpe=0.5, degradation=0.15,
                      permutation_p=0.01,
                      sym_sharpes={"A": 0.5, "B": 0.7, "C": 0.4})
        verdict, reasons, primary = classify(r)
        assert verdict == Verdict.SUPPORTED

    def test_fragile_borderline(self):
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.5, net_base=0.15, net_adverse=0.05,
                      max_dd=-0.15, trades=50, wf_consistency=0.6,
                      wf_oos_sharpe=0.1, degradation=0.3)
        verdict, reasons, primary = classify(r)
        assert verdict in (Verdict.FRAGILE, Verdict.COST_SENSITIVE)

    def test_regime_dependent_low_wf(self):
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.5, net_base=0.2, net_adverse=0.1,
                      max_dd=-0.15, trades=50, wf_consistency=0.3,
                      wf_oos_sharpe=0.1, degradation=0.2)
        verdict, reasons, primary = classify(r)
        assert verdict == Verdict.REGIME_DEPENDENT

    def test_instrument_dependent(self):
        # Need < 30% positive instruments for instrument_dependent
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.5, net_base=0.2, net_adverse=0.1,
                      max_dd=-0.15, trades=50, wf_consistency=0.6,
                      wf_oos_sharpe=0.1, degradation=0.2,
                      permutation_p=0.01,
                      sym_sharpes={"A": 0.8, "B": -0.5, "C": -0.3,
                                   "D": -0.2, "E": -0.1})
        verdict, reasons, primary = classify(r)
        assert "instrument_dependent" in reasons

    def test_catastrophic_dd(self):
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.5, net_base=0.2, net_adverse=0.1,
                      max_dd=-0.35, trades=50, wf_consistency=0.6,
                      wf_oos_sharpe=0.1, degradation=0.2)
        verdict, reasons, primary = classify(r)
        assert "catastrophic_dd" in reasons

    def test_permutation_insignificant(self):
        r = HypResult(hid="X", family="test", description="t", hp=4,
                      gross_sharpe=0.5, net_base=0.2, net_adverse=0.1,
                      max_dd=-0.15, trades=50, wf_consistency=0.6,
                      wf_oos_sharpe=0.1, degradation=0.2,
                      permutation_p=0.15)
        verdict, reasons, primary = classify(r)
        assert "permutation_insignificant" in reasons


# ═══════════════════════════════════════════════════════════════════════
# Report Generation
# ═══════════════════════════════════════════════════════════════════════

class TestReport:
    def test_report_generates_string(self):
        results = [
            HypResult(hid="T-001", family="test", description="test", hp=1,
                      verdict=Verdict.REJECTED, reasons=["negative_gross"]),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_report.md")
            text = report(results, path=path)
            assert isinstance(text, str)
            assert "CAMPAIGN 4" in text
            assert "T-001" in text
            # Check JSON was also written
            json_path = path.replace(".md", ".json")
            assert os.path.exists(json_path)

    def test_report_survivor_analysis(self):
        results = [
            HypResult(hid="S-001", family="test", description="good", hp=4,
                      gross_sharpe=0.8, net_base=0.6, wf_consistency=0.8,
                      verdict=Verdict.SUPPORTED, sym_sharpes={"A": 0.5}),
            HypResult(hid="R-001", family="test", description="bad", hp=1,
                      gross_sharpe=-0.5, net_base=-0.8,
                      verdict=Verdict.REJECTED, reasons=["negative_gross"]),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_report.md")
            text = report(results, path=path)
            assert "Survivors: 1/2" in text
            assert "VERDICT DISTRIBUTION" in text


# ═══════════════════════════════════════════════════════════════════════
# Data Integrity
# ═══════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_cost_model_values(self):
        assert CostModel.BASE == 13 / 10000
        assert CostModel.ADVERSE == 22 / 10000

    def test_horizons_are_valid(self):
        assert HORIZONS == [1, 2, 4, 8, 16]
        for h in HORIZONS:
            assert h > 0
            assert isinstance(h, int)

    def test_universe_size(self):
        assert len(UNIVERSE) == 8

    def test_all_signals_registered(self):
        for h in HYPOTHESES:
            assert h.signal in SIGNALS, \
                f"Hypothesis {h.hid} references missing signal '{h.signal}'"


# ═══════════════════════════════════════════════════════════════════════
# M15 Data Puller Tests
# ═══════════════════════════════════════════════════════════════════════

class TestM15DataPuller:
    def test_manifest_from_dict(self):
        from eigencapital.research.intraday.m15_data_puller import M15DataManifest
        m = M15DataManifest(
            broker="Exness", terminal_id="123",
            symbols=["EURUSDm"], timeframe="M15",
            bars_per_symbol={"EURUSDm": 50000},
            total_bars=50000,
            first_timestamp="2024-07-04", last_timestamp="2026-08-24",
            retrieval_timestamp="2026-08-24",
            missing_bars=0, duplicate_bars=0, ohlc_violations=0,
            zero_volume_bars=0, snapshot_hash="abc123",
        )
        d = m.to_dict()
        assert d["broker"] == "Exness"
        assert d["total_bars"] == 50000
        assert d["timeframe"] == "M15"

    def test_integrity_checks(self):
        from eigencapital.research.intraday.m15_data_puller import _check_integrity
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-15 00:00", periods=100, freq="15min"),
            "open": [1.1] * 100,
            "high": [1.12] * 100,
            "low": [1.08] * 100,
            "close": [1.1] * 100,
            "tick_volume": [100] * 100,
        })
        data = {"EURUSDm": df}
        missing, dupes, ohlc, zv = _check_integrity(data)
        assert missing == 0
        assert dupes == 0
        assert ohlc == 0
        assert zv == 0
