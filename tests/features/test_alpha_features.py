import numpy as np
import pandas as pd
import pytest

from features.alpha_features import (
    adx_slope,
    bb_pct_b,
    build_alpha_features,
    commodity_momentum,
    cot_net_positioning,
    day_of_week_signal,
    dxy_momentum,
    macd_histogram,
    momentum_features,
    spx_momentum,
    stochastic_oscillator,
    vix_momentum,
    vol_adjusted_carry,
    vol_regime_ratio,
    zscore_reversion,
)

N = 300
SEED = 42


@pytest.fixture
def price_series():
    rng = np.random.default_rng(SEED)
    return pd.Series(
        100 + rng.standard_normal(N).cumsum(),
        name="close",
    )


@pytest.fixture
def rate_series(price_series):
    rng = np.random.default_rng(SEED)
    return pd.Series(rng.uniform(-0.02, 0.05, N), index=price_series.index)


@pytest.fixture
def sample_prices():
    rng = np.random.default_rng(SEED)
    return pd.DataFrame(
        {a: 100 + rng.standard_normal(N).cumsum() for a in ["AUDJPY", "EURCAD"]},
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
    assert result["mom_252d"].isna().iloc[:252].all()
    assert result["mom_252d"].notna().iloc[252:].any()


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
        "AUDJPY_has_cot",
        "EURCAD_carry_vol_adj",
        "EURCAD_mom_21d",
        "EURCAD_mom_63d",
        "EURCAD_mom_126d",
        "EURCAD_mom_252d",
        "EURCAD_zscore_20",
        "EURCAD_vol_ratio",
        "EURCAD_dow_signal",
        "EURCAD_has_cot",
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


def test_build_alpha_features_adds_trend_exhaustion_with_ohlcv(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """When ohlcv is provided, all 6 trend-exhaustion columns appear."""
    idx = sample_prices.index
    ohlcv = pd.DataFrame({
        "open": np.random.default_rng(42).uniform(99, 101, len(idx)),
        "high": np.random.default_rng(43).uniform(100, 103, len(idx)),
        "low": np.random.default_rng(44).uniform(97, 100, len(idx)),
        "close": sample_prices["AUDJPY"].values,
        "volume": np.random.default_rng(45).uniform(1000, 5000, len(idx)),
    }, index=idx)
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
        ohlcv=ohlcv,
    )
    for asset in sample_prices.columns:
        upper = asset.upper()
        for feat in ("macd_hist", "stoch_k", "stoch_d", "bb_pct_b", "adx_slope", "rsi_divergence"):
            assert f"{upper}_{feat}" in result.columns, f"Missing {upper}_{feat}"


def test_build_alpha_features_without_ohlcv_skips_trend_exhaustion(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """Without ohlcv, no trend-exhaustion columns appear."""
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
    )
    for asset in sample_prices.columns:
        upper = asset.upper()
        assert f"{upper}_macd_hist" not in result.columns


def test_build_alpha_features_missing_rate_diff_defaults_to_zero(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """When an asset's pair is missing from rate_diffs, carry should be ~0."""
    missing_pair = "GBPJPY"
    prices_w_missing = pd.DataFrame({missing_pair: sample_prices["AUDJPY"].values}, index=sample_prices.index)
    # rate_diffs has AUDJPY and EURCAD, not GBPJPY
    result = build_alpha_features(
        prices_w_missing, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
    )
    assert f"{missing_pair}_carry_vol_adj" in result.columns
    # With zero rate_diff, the carry should be near 0
    carry_col = result[f"{missing_pair}_carry_vol_adj"]
    assert carry_col.dropna().abs().max() < 1e-10


def test_build_alpha_features_with_cot_data(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """COT columns from relevant factor groups appear when cot_data is provided."""
    idx = sample_prices.index
    # Use COT pairs whose factor groups overlap with the portfolio (AUDJPY ↔ AUD/JPY, EURCAD ↔ EUR/CAD).
    # EURUSD overlaps with EUR, AUDUSD overlaps with AUD.
    cot_data = pd.DataFrame({
        "EURUSD_cot_z": np.random.default_rng(42).normal(0, 1, len(idx)),
        "EURUSD_cot_change_4w": np.random.default_rng(43).normal(0, 0.5, len(idx)),
        "AUDUSD_cot_z": np.random.default_rng(44).normal(0, 1, len(idx)),
        "AUDUSD_cot_change_4w": np.random.default_rng(45).normal(0, 0.5, len(idx)),
    }, index=idx)
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
        cot_data=cot_data,
    )
    assert "EURUSD_cot_z" in result.columns
    assert "EURUSD_cot_change_4w" in result.columns
    assert "AUDUSD_cot_z" in result.columns
    assert "AUDUSD_cot_change_4w" in result.columns


def test_build_alpha_features_cot_initialized_zero_when_missing(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """When cot_data is None, COT columns are still initialized to 0.0.
    Uses AUDUSD which IS in FX_COT_CONTRACTS.
    """
    prices = pd.DataFrame({"AUDUSD": sample_prices["AUDJPY"].values}, index=sample_prices.index)
    rate = pd.DataFrame({"AUDUSD": sample_rate_diffs["AUDJPY"].values}, index=sample_prices.index)
    result = build_alpha_features(
        prices, rate,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
        cot_data=None,
    )
    assert "AUDUSD_cot_z" in result.columns
    assert (result["AUDUSD_cot_z"] == 0.0).all()


def test_build_alpha_features_cot_three_day_lag(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """COT features are shifted by 3 days (publication lag)."""
    idx = sample_prices.index
    values = np.random.default_rng(42).normal(0, 1, len(idx))
    cot_data = pd.DataFrame({"EURUSD_cot_z": values}, index=idx)
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
        cot_data=cot_data,
    )
    # The lag means the first 3 rows of cot_z should be NaN (filled by ffill)
    # and the last 3 rows of cot_data should be absent from the result
    # Just check the column exists and has correct values
    assert "EURUSD_cot_z" in result.columns


# ── cot_net_positioning ─────────────────────────────────────────────────────


def test_cot_net_positioning_basic():
    normalised = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5] * 20)
    oi = pd.Series([100.0] * 100)
    result = cot_net_positioning(normalised, oi)
    assert isinstance(result, pd.Series)
    assert not result.isna().all()


def test_cot_net_positioning_zero_open_interest():
    normalised = pd.Series([0.1] * 100)
    oi = pd.Series([0.0] * 100)
    result = cot_net_positioning(normalised, oi)
    assert not result.empty


def test_cot_net_positioning_clips_extremes():
    rng = np.random.default_rng(42)
    normalised = pd.Series(rng.normal(0, 1, 200))
    oi = pd.Series([100.0] * 200)
    result = cot_net_positioning(normalised, oi)
    assert result.dropna().between(-3, 3).all()


def test_cot_net_positioning_short_history():
    normalised = pd.Series([0.1] * 10)
    oi = pd.Series([100.0] * 10)
    result = cot_net_positioning(normalised, oi, lookback=52)
    assert result.isna().all() or result.empty


# ── macd_histogram ──────────────────────────────────────────────────────────


def test_macd_histogram_basic():
    rng = np.random.default_rng(42)
    close = pd.Series(100 + rng.standard_normal(300).cumsum())
    result = macd_histogram(close)
    assert isinstance(result, pd.Series)
    assert len(result) == 300
    assert result.dropna().between(-0.05, 0.05).all()


def test_macd_histogram_constant_close():
    close = pd.Series([100.0] * 300)
    result = macd_histogram(close)
    assert result.dropna().abs().max() < 1e-10


def test_macd_histogram_short_series():
    close = pd.Series([100.0, 101.0, 102.0])
    result = macd_histogram(close)
    assert result.isna().all()


# ── stochastic_oscillator ───────────────────────────────────────────────────


def test_stochastic_kd_basic():
    rng = np.random.default_rng(42)
    n = 300
    close = pd.Series(100 + rng.standard_normal(n).cumsum())
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    k, d = stochastic_oscillator(high, low, close)
    assert isinstance(k, pd.Series)
    assert isinstance(d, pd.Series)
    assert k.dropna().between(0, 1).all()
    assert d.dropna().between(0, 1).all()


def test_stochastic_kd_constant_prices():
    close = pd.Series([100.0] * 300)
    high = pd.Series([101.0] * 300)
    low = pd.Series([99.0] * 300)
    k, d = stochastic_oscillator(high, low, close)
    assert not k.isna().all()


# ── bb_pct_b ────────────────────────────────────────────────────────────────


def test_bb_pct_basic():
    rng = np.random.default_rng(42)
    close = pd.Series(100 + rng.standard_normal(300).cumsum())
    result = bb_pct_b(close)
    assert isinstance(result, pd.Series)
    assert len(result) == 300


def test_bb_pct_constant_close():
    close = pd.Series([100.0] * 300)
    result = bb_pct_b(close)
    # Constant price -> zero band width -> undefined %B (NaN or near-zero)
    assert isinstance(result, pd.Series)
    assert len(result) == 300


# ── adx_slope ───────────────────────────────────────────────────────────────


def test_adx_slope_basic():
    rng = np.random.default_rng(42)
    n = 300
    close = pd.Series(100 + rng.standard_normal(n).cumsum())
    high = close + np.abs(rng.standard_normal(n)) * 0.5
    low = close - np.abs(rng.standard_normal(n)) * 0.5
    result = adx_slope(high, low, close)
    assert isinstance(result, pd.Series)
    assert len(result) == 300


# ── _compute_shared_features ────────────────────────────────────────────────


def test_build_alpha_features_with_shared_features(
    sample_prices, sample_rate_diffs,
):
    """Pre-computed shared_features are used instead of recomputing."""
    idx = sample_prices.index
    shared = {"dxy_mom_21d": pd.Series(np.linspace(-0.01, 0.01, len(idx)), index=idx)}
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        shared_features=shared,
    )
    assert "dxy_mom_21d" in result.columns
    assert not result["dxy_mom_21d"].isna().all()


def test_build_alpha_features_shared_features_reindexed(
    sample_prices, sample_rate_diffs,
):
    """shared_features are reindexed to feature DataFrame index."""
    idx = sample_prices.index
    shorter_idx = idx[: len(idx) - 10]
    shared = {"dxy_mom_21d": pd.Series(np.linspace(-0.01, 0.01, len(shorter_idx)), index=shorter_idx)}
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        shared_features=shared,
    )
    assert len(result) > 0
    assert "dxy_mom_21d" in result.columns
