import pandas as pd
import numpy as np
import pytest

from features.publication_lags import (
    PUBLICATION_LAGS_RAW,
    DERIVED_FEATURE_LAGS,
    publication_lag,
    apply_publication_lags,
    apply_lag_to_macro_derived,
    audit_lookahead,
)


def test_publication_lag_known():
    """Known raw series should return their configured lag."""
    assert publication_lag("jp_10y") == 30
    assert publication_lag("fed_funds") == 1
    assert publication_lag("vix") == 0


def test_publication_lag_unknown():
    """Unknown features should return 0 (no lag)."""
    assert publication_lag("nonexistent_feature") == 0


def test_apply_publication_lags_shifts_columns():
    """apply_publication_lags should shift columns by their configured lag."""
    df = pd.DataFrame({
        "us_2y": np.linspace(3.0, 3.5, 50),
        "jp_10y": np.full(50, 1.0),
        "vix": np.full(50, 15.0),
    }, index=pd.RangeIndex(50))

    shifted = apply_publication_lags(df)

    # us_2y has lag 1 → first row should be NaN
    assert pd.isna(shifted["us_2y"].iloc[0])
    # vix has lag 0 → first row should be preserved
    assert shifted["vix"].iloc[0] == 15.0


def test_apply_publication_lags_ffill():
    """After shift, NaNs after position 0 should be forward-filled."""
    df = pd.DataFrame({
        "fed_funds": [2.5, 2.5, 2.75, 2.75, 2.75],
        "vix": [15.0, 16.0, 14.0, 13.0, 12.0],
    }, index=pd.RangeIndex(5))

    shifted = apply_publication_lags(df)

    # fed_funds lag=1: shift(1) → [NaN, 2.5, 2.5, 2.75, 2.75], ffill → [NaN, 2.5, 2.5, 2.75, 2.75]
    assert pd.isna(shifted["fed_funds"].iloc[0])  # no prior value to ffill
    assert shifted["fed_funds"].iloc[1] == 2.5
    assert shifted["fed_funds"].iloc[3] == 2.75


def test_apply_lag_to_macro_derived():
    """Derived feature lags should be applied to matching column names."""
    df = pd.DataFrame({
        "us_jp_10y_spread": np.full(10, 2.0),
        "vix_ma21": np.full(10, 15.0),
        "rate_diff": np.full(10, 1.5),
    }, index=pd.RangeIndex(10))

    shifted = apply_lag_to_macro_derived(df)

    # us_jp_10y_spread lag=30 > len(df) → all NaN (shift wipes out all rows)
    assert pd.isna(shifted["us_jp_10y_spread"]).all()

    # vix_ma21 lag=0 → should be unchanged
    np.testing.assert_array_equal(shifted["vix_ma21"], df["vix_ma21"])


def test_apply_lag_to_macro_derived_noop_for_price_features():
    """Price-only feature columns (momentum) should not be affected."""
    df = pd.DataFrame({
        "btc_mom_21": np.linspace(0.01, 0.05, 10),
        "btc_mom_63": np.linspace(0.02, 0.08, 10),
        "rate_diff": np.full(10, 1.5),
    }, index=pd.RangeIndex(10))

    shifted = apply_lag_to_macro_derived(df)

    # Price moment features are not in DERIVED_FEATURE_LAGS → untouched
    np.testing.assert_array_almost_equal(shifted["btc_mom_21"], df["btc_mom_21"])


def test_audit_lookahead_runs():
    """audit_lookahead should run without errors on a typical feature frame."""
    df = pd.DataFrame({
        "rate_diff": np.random.randn(50),
        "us_jp_10y_spread": np.random.randn(50),
        "vix_ma21": np.random.randn(50),
    }, index=pd.RangeIndex(50))
    audit_lookahead(df, contract_name="TEST")


@pytest.mark.skip(reason="CI runner pandas C extensions segfault on DatetimeIndex construction")
def test_end_to_end_no_lookahead():
    """Simulate the full compute_macro_derived → build_features path."""
    from features.builder import compute_macro_derived

    dates = pd.date_range("2020-01-01", periods=200, freq="D")
    macro_raw = pd.DataFrame({
        "fed_funds": np.full(200, 2.5),
        "ecb_rate": np.full(200, 1.0),
        "us_2y": np.full(200, 3.0),
        "us_10y": np.full(200, 3.5),
        "jp_10y": np.full(200, 0.5),
        "ca_10y": np.full(200, 2.0),
        "vix": np.full(200, 15.0),
        "dxy": np.full(200, 96.0),
        "real_yield_10y": np.full(200, 0.5),
        "breakeven_10y": np.full(200, 2.0),
    }, index=dates)

    derived = compute_macro_derived(macro_raw)

    # All derived features should exist
    expected_cols = [
        "rate_diff", "2y_yield_delta_63", "dxy_mom_63", "dxy_mom_21",
        "vix_ma21", "vix_delta_5", "us_jp_10y_spread", "ca_jp_10y_spread",
        "ca_jp_spread_mom_21", "ca_jp_spread_mom_5",
        "real_yield_delta_63", "breakeven_delta_63",
    ]
    for col in expected_cols:
        assert col in derived.columns, f"Missing derived column: {col}"

    # The OECD-influenced columns (jp_10y based) should have been shifted
    # Since jp_10y lag=30 and we had 200 rows, the shift should not zero out all data
    assert derived["us_jp_10y_spread"].notna().sum() > 0
    assert derived["ca_jp_10y_spread"].notna().sum() > 0
    assert derived["ca_jp_spread_mom_21"].notna().sum() > 0
    assert derived["ca_jp_spread_mom_5"].notna().sum() > 0


@pytest.mark.skip(reason="CI runner pandas C extensions segfault on DatetimeIndex construction")
def test_cot_loader_still_handles_lag():
    """COT loader's align_cot_to_daily should still work correctly."""
    from data.loaders.cot_loader import align_cot_to_daily

    weekly_dates = pd.date_range("2020-01-03", periods=10, freq="W-FRI")
    cot_df = pd.DataFrame({
        "lev_net": np.random.randn(10),
        "dealer_net": np.random.randn(10),
    }, index=weekly_dates)

    daily_idx = pd.date_range("2020-01-01", periods=100, freq="D")
    aligned = align_cot_to_daily(cot_df, daily_idx, release_lag_days=3)

    assert len(aligned) == len(daily_idx)
    assert aligned.index.equals(daily_idx)


def test_publication_lags_no_side_effects():
    """apply_publication_lags should not modify the input DataFrame."""
    original = pd.DataFrame({
        "us_2y": np.full(10, 3.0),
        "vix": np.full(10, 15.0),
    }, index=pd.RangeIndex(10))
    copy = original.copy()

    shifted = apply_publication_lags(original)

    pd.testing.assert_frame_equal(original, copy)
    assert shifted is not original


def test_all_lags_consistency():
    """Every entry in DERIVED_FEATURE_LAGS should have a non-negative integer lag."""
    for name, lag in DERIVED_FEATURE_LAGS.items():
        assert isinstance(lag, int), f"{name} lag is not int"
        assert lag >= 0, f"{name} lag is negative"
    for name, lag in PUBLICATION_LAGS_RAW.items():
        assert isinstance(lag, int), f"{name} lag is not int"
        assert lag >= 0, f"{name} lag is negative"
