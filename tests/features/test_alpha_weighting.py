import numpy as np
import pandas as pd
import pytest

from archive.deprecated._alpha_weighting import (
    normalize_to_unit,
    compute_asset_signals,
    compute_cross_asset_overlay,
    generate_weighted_signals,
)

N = 100
SEED = 42


@pytest.fixture
def alpha_df():
    rng = np.random.default_rng(SEED)
    df = pd.DataFrame(index=range(N))
    for asset in ["AUDJPY", "EURCAD"]:
        df[f"{asset}_carry_vol_adj"] = rng.uniform(-1, 1, N)
        df[f"{asset}_mom_21d"] = rng.uniform(-0.2, 0.2, N)
        df[f"{asset}_zscore_20"] = rng.uniform(-2, 2, N)
        df[f"{asset}_vol_ratio"] = rng.uniform(0.1, 3.0, N)
        df[f"{asset}_dow_signal"] = rng.uniform(-0.5, 0.5, N)
    df["dxy_mom_21d"] = rng.uniform(-0.05, 0.05, N)
    df["vix_mom_5d"] = rng.uniform(-0.1, 0.1, N)
    df["spx_mom_5d"] = rng.uniform(-0.03, 0.03, N)
    df["WTI_mom_21d"] = rng.uniform(-0.1, 0.1, N)
    return df


# ── normalize_to_unit ─────────────────────────────────────────────────────────


def test_normalize_to_unit_range():
    s = pd.Series(np.linspace(-10, 10, 100))
    result = normalize_to_unit(s)
    assert result.min() >= -1.0
    assert result.max() <= 1.0


def test_normalize_to_unit_constant():
    s = pd.Series(np.ones(100) * 5.0)
    result = normalize_to_unit(s)
    assert result.abs().max() <= 1.0


# ── compute_asset_signals ─────────────────────────────────────────────────────


def test_asset_signals_output_shape(alpha_df):
    result = compute_asset_signals(alpha_df)
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["AUDJPY", "EURCAD"]
    assert len(result) == N


def test_asset_signals_in_range(alpha_df):
    result = compute_asset_signals(alpha_df)
    for col in result.columns:
        assert result[col].between(-1, 1).all()


def test_asset_signals_not_constant(alpha_df):
    result = compute_asset_signals(alpha_df)
    for col in result.columns:
        assert result[col].std() > 0


def test_asset_signals_weight_override(alpha_df):
    weights = {"carry_vol_adj": 1.0, "mom_21d": 0.0, "zscore_20": 0.0, "vol_ratio": 0.0, "dow_signal": 0.0}
    result = compute_asset_signals(alpha_df, asset_weights=weights)
    expected = normalize_to_unit(alpha_df["AUDJPY_carry_vol_adj"])
    pd.testing.assert_series_equal(result["AUDJPY"], expected, check_names=False)


def test_asset_signals_no_normalize(alpha_df):
    result = compute_asset_signals(alpha_df, normalize=False)
    assert result["AUDJPY"].between(-1, 1).all()


# ── compute_cross_asset_overlay ──────────────────────────────────────────────


def test_cross_overlay_output_shape(alpha_df):
    result = compute_cross_asset_overlay(alpha_df)
    assert isinstance(result, pd.Series)
    assert len(result) == N


def test_cross_overlay_in_range(alpha_df):
    result = compute_cross_asset_overlay(alpha_df)
    assert result.between(-1, 1).all()


def test_cross_overlay_no_columns():
    df = pd.DataFrame({"dummy": [1.0, 2.0]})
    result = compute_cross_asset_overlay(df)
    assert (result == 0.0).all()


# ── generate_weighted_signals ─────────────────────────────────────────────────


def test_generate_signals_output_columns(alpha_df):
    result = generate_weighted_signals(alpha_df)
    assert "overlay" in result.columns
    assert "AUDJPY_raw" in result.columns
    assert "AUDJPY_signal" in result.columns
    assert "EURCAD_raw" in result.columns
    assert "EURCAD_signal" in result.columns


def test_generate_signals_in_range(alpha_df):
    result = generate_weighted_signals(alpha_df)
    assert result["overlay"].between(-1, 1).all()
    assert result["AUDJPY_signal"].between(-1, 1).all()
    assert result["EURCAD_signal"].between(-1, 1).all()


def test_generate_signals_overlay_strength_zero(alpha_df):
    result = generate_weighted_signals(alpha_df, overlay_strength=0.0)
    pd.testing.assert_series_equal(result["AUDJPY_raw"], result["AUDJPY_signal"], check_names=False)


def test_generate_signals_overlay_strength_nonzero_effect(alpha_df):
    result = generate_weighted_signals(alpha_df, overlay_strength=0.5)
    assert not result["AUDJPY_raw"].equals(result["AUDJPY_signal"])
