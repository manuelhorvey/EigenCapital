import numpy as np
import pandas as pd
import pytest

from archive.deprecated._cot_features import (
    cot_index,
    compute_net_positions,
    build_cot_features,
    EURUSD_COT_FEATURES,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def cot_series():
    np.random.seed(42)
    n = 100
    return pd.DataFrame(
        {
            "Lev_Money_Positions_Long_All": np.random.randint(10000, 50000, n),
            "Lev_Money_Positions_Short_All": np.random.randint(5000, 30000, n),
            "Dealer_Positions_Long_All": np.random.randint(20000, 60000, n),
            "Dealer_Positions_Short_All": np.random.randint(10000, 40000, n),
            "Asset_Mgr_Positions_Long_All": np.random.randint(30000, 80000, n),
            "Asset_Mgr_Positions_Short_All": np.random.randint(10000, 50000, n),
            "Open_Interest_All": np.random.randint(100000, 500000, n),
            "Other_Rept_Positions_Long_All": np.random.randint(1000, 5000, n),
            "Other_Rept_Positions_Short_All": np.random.randint(500, 3000, n),
        },
        index=pd.RangeIndex(n),
    )


# ── cot_index ────────────────────────────────────────────────────────────────


def test_cot_index_between_zero_and_one(cot_series):
    net = cot_series["Lev_Money_Positions_Long_All"] - cot_series["Lev_Money_Positions_Short_All"]
    idx = cot_index(net, window=52)
    idx_clean = idx.dropna()
    assert (idx_clean >= 0).all()
    assert (idx_clean <= 1).all()


def test_cot_index_reproducible_across_extended_data():
    series = pd.Series(np.random.default_rng(42).uniform(0, 1, 100))
    idx_short = cot_index(series.iloc[:30], window=52, min_periods=12)
    idx_long = cot_index(series.iloc[:60], window=52, min_periods=12)
    non_nan_short = idx_short.notna()
    non_nan_long = idx_long.iloc[:30].notna()
    assert (non_nan_short == non_nan_long).all(), "NaN positions differ"
    vals_short = idx_short.values[non_nan_short.values]
    vals_long = idx_long.values[:30][non_nan_long.values]
    assert abs(vals_short - vals_long).max() < 1e-14, "Non-NaN values differ when series is extended"


def test_cot_index_constant_series():
    series = pd.Series(np.ones(100) * 5000)
    idx = cot_index(series, window=52)
    assert idx.dropna().iloc[0] == pytest.approx(0.0, abs=0.01)


# ── compute_net_positions ────────────────────────────────────────────────────


def test_compute_net_positions_columns(cot_series):
    net = compute_net_positions(cot_series)
    expected = ["lev_net", "dealer_net", "asset_mgr_net", "open_interest"]
    for col in expected:
        assert col in net.columns


def test_compute_net_positions_values(cot_series):
    net = compute_net_positions(cot_series)
    expected = cot_series["Lev_Money_Positions_Long_All"] - cot_series["Lev_Money_Positions_Short_All"]
    pd.testing.assert_series_equal(net["lev_net"], expected, check_names=False)


# ── build_cot_features ───────────────────────────────────────────────────────


def test_build_cot_features_returns_dataframe(cot_series):
    result = build_cot_features(cot_series)
    assert isinstance(result, pd.DataFrame)


def test_build_cot_features_has_all_expected_columns(cot_series):
    result = build_cot_features(cot_series)
    expected = [
        "lev_net",
        "dealer_net",
        "asset_mgr_net",
        "lev_net_cot_index",
        "dealer_net_cot_index",
        "asset_mgr_net_cot_index",
        "lev_net_change_1w",
        "lev_net_change_4w",
        "dealer_net_change_1w",
        "dealer_net_change_4w",
        "asset_mgr_net_change_1w",
        "asset_mgr_net_change_4w",
        "pct_long_lev",
        "pct_short_lev",
        "commercial_to_lev_ratio",
        "positioning_extreme",
    ]
    for col in expected:
        assert col in result.columns, f"Missing column: {col}"


def test_build_cot_features_positioning_extreme_is_binary(cot_series):
    result = build_cot_features(cot_series)
    assert result["positioning_extreme"].isin([0, 1]).all()


def test_build_cot_features_net_changes(cot_series):
    result = build_cot_features(cot_series)
    assert result["lev_net_change_1w"].notna().any()
    assert result["lev_net_change_4w"].notna().any()


def test_build_cot_features_percentages_between_zero_and_one(cot_series):
    result = build_cot_features(cot_series)
    assert (result["pct_long_lev"].dropna() >= 0).all()
    assert (result["pct_long_lev"].dropna() <= 1).all()


def test_eurusd_cot_features_list_not_empty():
    assert len(EURUSD_COT_FEATURES) > 0
    assert "lev_net_cot_index" in EURUSD_COT_FEATURES
