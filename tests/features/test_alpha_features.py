import numpy as np
import pandas as pd
import pytest

from features.alpha_features import (
    adx_slope,
    bb_pct_b,
    build_alpha_features,
    commodity_momentum,
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
        "AUDJPY_carry_up",
        "AUDJPY_carry_dn",
        "AUDJPY_mom_21d",
        "AUDJPY_mom_21d_up",
        "AUDJPY_mom_21d_dn",
        "AUDJPY_mom_63d",
        "AUDJPY_mom_63d_up",
        "AUDJPY_mom_63d_dn",
        "AUDJPY_mom_126d",
        "AUDJPY_mom_126d_up",
        "AUDJPY_mom_126d_dn",
        "AUDJPY_mom_252d",
        "AUDJPY_mom_252d_up",
        "AUDJPY_mom_252d_dn",
        "AUDJPY_zscore_20",
        "AUDJPY_vol_ratio",
        "AUDJPY_dow_signal",
        "EURCAD_carry_vol_adj",
        "EURCAD_carry_up",
        "EURCAD_carry_dn",
        "EURCAD_mom_21d",
        "EURCAD_mom_21d_up",
        "EURCAD_mom_21d_dn",
        "EURCAD_mom_63d",
        "EURCAD_mom_63d_up",
        "EURCAD_mom_63d_dn",
        "EURCAD_mom_126d",
        "EURCAD_mom_126d_up",
        "EURCAD_mom_126d_dn",
        "EURCAD_mom_252d",
        "EURCAD_mom_252d_up",
        "EURCAD_mom_252d_dn",
        "EURCAD_zscore_20",
        "EURCAD_vol_ratio",
        "EURCAD_dow_signal",
        "dxy_mom_21d",
        "vix_mom_5d",
        "spx_mom_5d",
        "WTI_mom_21d",
        # FXStreet narrative cross-asset features
        "usd_strength_narr",
        "geopol_risk",
        "fed_hawk",
        "rbnz_hawk",
        "rba_hawk",
        "boj_intervene_risk",
        "energy_pressure",
        "usd_bias_num",
        "nzd_bias_num",
        "aud_bias_num",
        "jpy_bias_num",
        "cad_bias_num",
        "eur_bias_num",
        "regime_risk_on",
        "regime_geopol",
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


def test_build_alpha_features_cot_removed(
    sample_prices, sample_rate_diffs, sample_macro,
):
    """COT features are removed — no COT columns in the output."""
    result = build_alpha_features(
        sample_prices, sample_rate_diffs,
        dxy=sample_macro["dxy"], vix=sample_macro["vix"],
        spx=sample_macro["spx"], commodities=sample_macro["comms"],
    )
    # COT columns were removed 2026-07-11
    assert "AUDJPY_cot_z" not in result.columns, "COT column should not exist"
    assert "AUDJPY_has_cot" not in result.columns, "COT column should not exist"
    assert "EURCAD_cot_z" not in result.columns, "COT column should not exist"
    assert "EURUSD_cot_z" not in result.columns, "COT column should not exist"


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
