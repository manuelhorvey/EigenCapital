import numpy as np
import pandas as pd
import pytest

from features.alpha_features import (
    vol_adjusted_carry,
    momentum_features,
    zscore_reversion,
    vol_regime_ratio,
    dxy_momentum,
    commodity_momentum,
    vix_momentum,
    spx_momentum,
    day_of_week_signal,
    build_alpha_features,
)

N = 300
SEED = 42


@pytest.fixture
def price_series():
    rng = np.random.default_rng(SEED)
    return pd.Series(
        100 + rng.standard_normal(N).cumsum(),
        index=pd.date_range("2024-01-01", periods=N, freq="B"),
        name="close",
    )


@pytest.fixture
def rate_series(price_series):
    rng = np.random.default_rng(SEED)
    return pd.Series(rng.uniform(-0.02, 0.05, N), index=price_series.index)


@pytest.fixture
def sample_prices():
    rng = np.random.default_rng(SEED)
    idx = pd.date_range("2024-01-01", periods=N, freq="B")
    return pd.DataFrame(
        {a: 100 + rng.standard_normal(N).cumsum() for a in ["AUDJPY", "EURCAD"]},
        index=idx,
    )


@pytest.fixture
def sample_rate_diffs(sample_prices):
    rng = np.random.default_rng(SEED)
    return pd.DataFrame(
        {a: rng.uniform(-0.02, 0.05, N) for a in sample_prices.columns},
        index=sample_prices.index,
    )


@pytest.fixture
def sample_macro(sample_prices):
    rng = np.random.default_rng(SEED)
    idx = sample_prices.index
    return {
        "dxy": pd.Series(100 + rng.standard_normal(N).cumsum() * 2, index=idx),
        "vix": pd.Series(np.abs(rng.standard_normal(N)) * 10 + 15, index=idx),
        "spx": pd.Series(4000 + rng.standard_normal(N).cumsum() * 50, index=idx),
        "comms": pd.DataFrame(
            {"WTI": 80 + rng.standard_normal(N).cumsum() * 2}, index=idx
        ),
    }


# ── vol_adjusted_carry ────────────────────────────────────────────────────────────


def test_carry_output_shape_and_type(price_series, rate_series):
    result = vol_adjusted_carry(price_series, rate_series)
    assert isinstance(result, pd.Series)
    assert len(result) == N


def test_carry_produces_non_nan_values(price_series, rate_series):
    result = vol_adjusted_carry(price_series, rate_series)
    assert result.notna().sum() > len(result) * 0.9


def test_carry_zero_rate_diff(price_series):
    zero_rate = pd.Series(0.0, index=price_series.index)
    result = vol_adjusted_carry(price_series, zero_rate)
    assert result.dropna().abs().max() < 1e-10


def test_carry_ratio_ranges(price_series, rate_series):
    result = vol_adjusted_carry(price_series, rate_series)
    clean = result.dropna()
    assert clean.between(-1, 1).all()


# ── momentum_features ─────────────────────────────────────────────────────────────


def test_momentum_returns_dataframe(price_series):
    result = momentum_features(price_series)
    assert isinstance(result, pd.DataFrame)


def test_momentum_expected_columns(price_series):
    result = momentum_features(price_series)
    expected = ["mom_21d", "mom_63d", "mom_126d", "mom_252d"]
    for col in expected:
        assert col in result.columns


def test_momentum_first_rows_nan(price_series):
    result = momentum_features(price_series)
    assert result["mom_252d"].isna().iloc[:253].all()
    assert result["mom_252d"].notna().iloc[253:].any()


def test_momentum_produces_non_nan_values(price_series):
    result = momentum_features(price_series)
    assert result.notna().sum().sum() > 0


def test_momentum_clipping(price_series):
    result = momentum_features(price_series)
    for col in result.columns:
        assert result[col].dropna().between(-0.20, 0.20).all()


# ── zscore_reversion ──────────────────────────────────────────────────────────────


def test_zscore_output_type(price_series):
    result = zscore_reversion(price_series)
    assert isinstance(result, pd.Series)


def test_zscore_clipped_range(price_series):
    result = zscore_reversion(price_series)
    clean = result.dropna()
    assert clean.between(-3, 3).all()


def test_zscore_first_rows_nan(price_series):
    result = zscore_reversion(price_series)
    assert result.isna().iloc[:19].all()
    assert result.notna().iloc[20:].any()


# ── vol_regime_ratio ──────────────────────────────────────────────────────────────


def test_vol_regime_output_type(price_series):
    result = vol_regime_ratio(price_series)
    assert isinstance(result, pd.Series)


def test_vol_regime_clipped_range(price_series):
    result = vol_regime_ratio(price_series)
    clean = result.dropna()
    assert clean.between(0.1, 5.0).all()


def test_vol_regime_not_all_nan(price_series):
    result = vol_regime_ratio(price_series)
    assert result.notna().sum() > 0


# ── day_of_week_signal ────────────────────────────────────────────────────────────


def test_dow_output_shape(price_series):
    result = day_of_week_signal(price_series)
    assert isinstance(result, pd.Series)
    assert len(result) == N


def test_dow_all_values_valid(price_series):
    result = day_of_week_signal(price_series)
    assert result.notna().all()
    assert result.between(-1, 1).all()


# ── dxy / vix / spx / commodity ──────────────────────────────────────────────────


def test_dxy_momentum_output(sample_macro):
    result = dxy_momentum(sample_macro["dxy"])
    assert isinstance(result, pd.Series)
    assert len(result) == N
    assert result.dropna().between(-0.05, 0.05).all()


def test_vix_momentum_output(sample_macro):
    result = vix_momentum(sample_macro["vix"])
    assert isinstance(result, pd.Series)
    assert len(result) == N


def test_spx_momentum_output(sample_macro):
    result = spx_momentum(sample_macro["spx"])
    assert isinstance(result, pd.Series)
    assert len(result) == N
    assert result.dropna().between(-0.05, 0.05).all()


def test_commodity_momentum_output(sample_macro):
    result = commodity_momentum(sample_macro["comms"]["WTI"])
    assert isinstance(result, pd.Series)
    assert len(result) == N
    assert result.dropna().between(-0.10, 0.10).all()


# ── build_alpha_features ──────────────────────────────────────────────────────────


def test_build_alpha_features_returns_dataframe(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices,
        sample_rate_diffs,
        dxy=sample_macro["dxy"],
        vix=sample_macro["vix"],
        spx=sample_macro["spx"],
        commodities=sample_macro["comms"],
    )
    assert isinstance(result, pd.DataFrame)


def test_build_alpha_features_all_nan_dropped(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices,
        sample_rate_diffs,
        dxy=sample_macro["dxy"],
        vix=sample_macro["vix"],
        spx=sample_macro["spx"],
        commodities=sample_macro["comms"],
    )
    assert not result.isna().any().any()


def test_build_alpha_features_expected_columns(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices,
        sample_rate_diffs,
        dxy=sample_macro["dxy"],
        vix=sample_macro["vix"],
        spx=sample_macro["spx"],
        commodities=sample_macro["comms"],
    )
    expected = [
        "AUDJPY_carry_vol_adj",
        "AUDJPY_mom_21d",
        "AUDJPY_mom_63d",
        "AUDJPY_mom_126d",
        "AUDJPY_mom_252d",
        "AUDJPY_zscore_20",
        "AUDJPY_vol_ratio",
        "AUDJPY_dow_signal",
        "EURCAD_carry_vol_adj",
        "EURCAD_mom_21d",
        "EURCAD_mom_63d",
        "EURCAD_mom_126d",
        "EURCAD_mom_252d",
        "EURCAD_zscore_20",
        "EURCAD_vol_ratio",
        "EURCAD_dow_signal",
        "dxy_mom_21d",
        "vix_mom_5d",
        "spx_mom_5d",
        "WTI_mom_21d",
    ]
    for col in expected:
        assert col in result.columns, f"Missing: {col}"
    assert len(result.columns) == len(expected)


def test_build_alpha_features_no_dxy(sample_prices, sample_rate_diffs):
    result = build_alpha_features(sample_prices, sample_rate_diffs)
    assert isinstance(result, pd.DataFrame)
    assert "dxy_mom_21d" not in result.columns


def test_build_alpha_features_no_commodities(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"],
    )
    assert "WTI_mom_21d" not in result.columns


def test_build_alpha_features_preserves_index(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"],
    )
    assert result.index.isin(sample_prices.index).all()


def test_build_alpha_features_output_not_empty(sample_prices, sample_rate_diffs, sample_macro):
    result = build_alpha_features(
        sample_prices,
        sample_rate_diffs,
        dxy=sample_macro["dxy"],
        vix=sample_macro["vix"],
        spx=sample_macro["spx"],
        commodities=sample_macro["comms"],
    )
    assert len(result) > 0
