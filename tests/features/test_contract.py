"""Tests for features/contract — FeatureContract, validation, and helpers."""

import pytest

from features.contract import (
    FeatureContract,
    FeatureMismatchError,
    KNOWN_MACRO_COLUMNS,
    validate_no_cross_asset_leakage,
)
import pandas as pd


def _make_contract(**overrides):
    params = dict(
        ticker="EURUSD=X",
        name="EURUSD",
        label_type="tb20",
        label_params={"pt_sl": [2.0, 2.0], "vertical_barrier": 20},
        macro_filters=("rate_diff", "vix_ma21"),
        price_mom_windows=(21, 63),
        vs_spy_windows=(10, 20),
        custom_features=(),
    )
    params.update(overrides)
    return FeatureContract(**params)


class TestFeatureContractProperties:
    def test_requires_ref_when_vs_spy_present(self):
        c = _make_contract(vs_spy_windows=(10,))
        assert c.requires_ref

    def test_requires_ref_false_when_no_vs_spy(self):
        c = _make_contract(vs_spy_windows=())
        assert not c.requires_ref

    def test_features_includes_macro_filters_and_mom_windows(self):
        c = _make_contract(
            macro_filters=("rate_diff", "vix_ma21"),
            price_mom_windows=(21, 63),
            vs_spy_windows=(),
        )
        feats = c.features
        assert "rate_diff" in feats
        assert "vix_ma21" in feats
        assert "eurusd_mom_21" in feats
        assert "eurusd_mom_63" in feats

    def test_features_includes_vs_spy_prefix(self):
        c = _make_contract(vs_spy_windows=(10, 20))
        feats = c.features
        assert "eurusd_vs_spy_10" in feats
        assert "eurusd_vs_spy_20" in feats

    def test_features_includes_custom_features(self):
        c = _make_contract(custom_features=("dji_lead_1",))
        feats = c.features
        assert "dji_lead_1" in feats

    def test_label_version_is_deterministic(self):
        c1 = _make_contract()
        c2 = _make_contract()
        assert c1.label_version == c2.label_version

    def test_label_version_changes_with_params(self):
        c1 = _make_contract(label_params={"pt_sl": [2.0, 2.0]})
        c2 = _make_contract(label_params={"pt_sl": [3.0, 3.0]})
        assert c1.label_version != c2.label_version

    def test_label_version_is_12_chars(self):
        c = _make_contract()
        assert len(c.label_version) == 12

    def test_contract_prefix_default_empty(self):
        c = _make_contract(contract_prefix="")
        assert c.contract_prefix == ""

    def test_features_with_custom_contract_prefix(self):
        c = _make_contract(contract_prefix="eurusd=x", price_mom_windows=(21,))
        feats = c.features
        assert "eurusd=x_mom_21" in feats


class TestValidateDataframe:
    def test_passes_when_columns_match(self):
        c = _make_contract(macro_filters=("rate_diff",), price_mom_windows=(21,), vs_spy_windows=())
        df = pd.DataFrame({"rate_diff": [1.0], "eurusd_mom_21": [0.01]})
        # Should not raise
        c.validate_dataframe(df)

    def test_raises_on_column_mismatch(self):
        c = _make_contract(macro_filters=("rate_diff",), price_mom_windows=(21,), vs_spy_windows=())
        df = pd.DataFrame({"wrong_col": [1.0]})
        with pytest.raises(FeatureMismatchError):
            c.validate_dataframe(df)


class TestValidateNoCrossAssetLeakage:
    def test_passes_with_valid_columns(self):
        c = _make_contract(custom_features=("dji_lead_1",))
        df = pd.DataFrame({
            "eurusd_mom_21": [1.0],
            "rate_diff": [1.0],
            "vix_ma21": [2.0],
            "dji_lead_1": [0.5],
        })
        c.validate_no_cross_asset_leakage(df)

    def test_raises_on_other_asset_column(self):
        c = _make_contract()
        df = pd.DataFrame({"eurusd_mom_21": [1.0], "gbpusd_mom_21": [2.0]})
        with pytest.raises(FeatureMismatchError, match="Cross-asset feature leakage"):
            c.validate_no_cross_asset_leakage(df, known_slugs=["EURUSD", "GBPUSD"])

    def test_passes_with_known_macro_columns(self):
        c = _make_contract(macro_filters=(), price_mom_windows=(), vs_spy_windows=())
        df = pd.DataFrame({"fed_funds": [2.5]})
        c.validate_no_cross_asset_leakage(df, expected_prefixes=("macro_",))

    def test_raises_on_unrecognized_column(self):
        c = _make_contract(macro_filters=(), price_mom_windows=(), vs_spy_windows=())
        df = pd.DataFrame({"random_col": [1.0]})
        with pytest.raises(FeatureMismatchError, match="unrecognized"):
            c.validate_no_cross_asset_leakage(df)


class TestValidateModel:
    def test_skips_when_no_feature_names(self):
        """validate_model does nothing if model lacks get_booster."""
        c = _make_contract()
        c.validate_model(object())  # should not raise

    def test_raises_on_feature_mismatch(self):
        try:
            import xgboost
            has_xgb = True
        except ImportError:
            has_xgb = False
        if not has_xgb:
            pytest.skip("xgboost not installed")
        c = _make_contract(macro_filters=("rate_diff",), price_mom_windows=(21,), vs_spy_windows=())
        import numpy as np
        import xgboost as xgb
        X = pd.DataFrame({"wrong_feat": np.random.randn(10)})
        y = np.random.randint(0, 2, 10)
        model = xgb.XGBClassifier(n_estimators=2, max_depth=2, verbosity=0)
        model.fit(X, y)
        with pytest.raises(FeatureMismatchError):
            c.validate_model(model)


class TestFeatureMismatchError:
    def test_is_value_error(self):
        assert issubclass(FeatureMismatchError, ValueError)


class TestKnownMacroColumns:
    def test_includes_raw_macro(self):
        assert "fed_funds" in KNOWN_MACRO_COLUMNS
        assert "dxy" in KNOWN_MACRO_COLUMNS
        assert "vix" in KNOWN_MACRO_COLUMNS

    def test_includes_derived_macro(self):
        assert "rate_diff" in KNOWN_MACRO_COLUMNS
        assert "vix_ma21" in KNOWN_MACRO_COLUMNS
        assert "yield_slope" in KNOWN_MACRO_COLUMNS


class TestValidateNoCrossAssetLeakageModuleFn:
    def test_module_function_delegates_to_contract(self):
        c = _make_contract()
        df = pd.DataFrame({"eurusd_mom_21": [1.0], "rate_diff": [2.0]})
        result = validate_no_cross_asset_leakage(df, c)
        assert result is df  # returns the same DataFrame
