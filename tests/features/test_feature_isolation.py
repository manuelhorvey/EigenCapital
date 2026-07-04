import pandas as pd
import pytest

from features.contract import (
    KNOWN_MACRO_COLUMNS,
    FeatureContract,
    FeatureMismatchError,
    validate_no_cross_asset_leakage,
)
from features.registry import FEATURE_REGISTRY

ALL_SLUGS = [(c.contract_prefix or c.name) for c in FEATURE_REGISTRY.values()]


class TestValidateNoCrossAssetLeakage:
    def test_macro_only_columns_pass(self):
        contract = FEATURE_REGISTRY["NZDJPY=X"]
        df = pd.DataFrame({"rate_diff": [1.0], "dxy_mom_21": [0.5], "label": [0]})
        result = validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)
        assert result is df

    def test_own_mom_columns_pass(self):
        contract = FEATURE_REGISTRY["NZDJPY=X"]
        # NZDJPY=X contract_prefix is "nzdjpy=x"
        df = pd.DataFrame({"nzdjpy=x_mom_21": [0.01], "label": [0]})
        result = validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)
        assert result is df

    def test_foreign_asset_mom_raises(self):
        contract = FEATURE_REGISTRY["NZDJPY=X"]
        # EURUSD=X contract_prefix is "eurusd=x"
        df = pd.DataFrame({"eurusd=x_mom_21": [0.01], "label": [0]})
        with pytest.raises(FeatureMismatchError, match="Cross-asset feature leakage"):
            validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)

    def test_vs_spy_columns_pass(self):
        contract = FEATURE_REGISTRY["BTC-USD"]
        # BTC-USD contract_prefix is "btc-usd"
        df = pd.DataFrame({"btc-usd_vs_spy_21": [0.01], "label": [0]})
        result = validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)
        assert result is df

    def test_known_macro_columns_all_contracts(self):
        for ticker, contract in FEATURE_REGISTRY.items():
            cols = list(KNOWN_MACRO_COLUMNS) + ["label"]
            df = pd.DataFrame({c: [1.0] for c in cols})
            validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)

    def test_every_contract_own_features_pass(self):
        for ticker, contract in FEATURE_REGISTRY.items():
            cols = list(contract.features) + ["label"]
            df = pd.DataFrame({c: [1.0] for c in cols})
            validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)

    def test_unknown_column_raises(self):
        contract = FEATURE_REGISTRY["NZDJPY=X"]
        df = pd.DataFrame({"nonsense_col": [1.0], "label": [0]})
        with pytest.raises(FeatureMismatchError, match="is unrecognized"):
            validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)

    def test_custom_features_allowed(self):
        contract = FeatureContract(
            ticker="NZDJPY=X",
            name="NZDJPY",
            contract_prefix="nzdjpy=x",
            label_type="tb20",
            label_params={"pt_sl": [2.0, 0.5], "vertical_barrier": 20},
            macro_filters=("vix_ma21",),
            price_mom_windows=(21,),
            vs_spy_windows=(),
            custom_features=("audjpy_lead_3",),
        )
        df = pd.DataFrame({"vix_ma21": [1.0], "nzdjpy=x_mom_21": [0.01], "audjpy_lead_3": [0.02], "label": [0]})
        validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)

    def test_custom_features_foreign_slug_still_raises(self):
        contract = FeatureContract(
            ticker="NZDJPY=X",
            name="NZDJPY",
            contract_prefix="nzdjpy=x",
            label_type="tb20",
            label_params={"pt_sl": [2.0, 0.5], "vertical_barrier": 20},
            macro_filters=(),
            price_mom_windows=(),
            vs_spy_windows=(),
            custom_features=(),
        )
        df = pd.DataFrame({"eurusd=x_mom_21": [0.01], "label": [0]})
        with pytest.raises(FeatureMismatchError, match="Cross-asset feature leakage"):
            validate_no_cross_asset_leakage(df, contract, known_slugs=ALL_SLUGS)
