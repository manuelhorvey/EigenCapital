from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import pandas as pd


class FeatureMismatchError(ValueError):
    pass


@dataclass(frozen=True)
class FeatureContract:
    ticker: str
    name: str
    label_type: Literal["tb20", "fwd60"]
    label_params: dict
    macro_filters: tuple[str, ...]
    price_mom_windows: tuple[int, ...]
    vs_spy_windows: tuple[int, ...]
    custom_features: tuple[str, ...] = ()
    warmup_rows: int = 90
    min_history_days: int = 250
    contract_prefix: str = ""

    @property
    def requires_ref(self) -> bool:
        return len(self.vs_spy_windows) > 0

    @property
    def features(self) -> tuple[str, ...]:
        parts = list(self.macro_filters)
        slug = (self.contract_prefix or self.name).lower()
        for w in self.price_mom_windows:
            parts.append(f"{slug}_mom_{w}")
        for w in self.vs_spy_windows:
            parts.append(f"{slug}_vs_spy_{w}")
        parts.extend(self.custom_features)
        return tuple(parts)

    def validate_dataframe(self, df: pd.DataFrame) -> None:
        expected = list(self.features)
        actual = list(df.columns[: len(expected)])
        if actual != expected:
            raise FeatureMismatchError(
                f"{self.name}: expected columns {expected}, got {actual}. "
                f"Missing: {set(expected) - set(actual)}. "
                f"Extra: {set(actual) - set(expected)}."
            )

    def validate_model(self, model) -> None:
        try:
            model_feats = model.get_booster().feature_names
        except AttributeError:
            return
        expected = set(self.features)
        actual = set(model_feats)
        if actual != expected:
            raise FeatureMismatchError(
                f"{self.name}: model trained on {model_feats}, "
                f"contract requires {self.features}. "
                f"Missing: {expected - actual}. "
                f"Extra: {actual - expected}."
            )

    def validate_no_cross_asset_leakage(
        self,
        df: pd.DataFrame,
        expected_prefixes: tuple[str, ...] = ("macro_", "spy_", "regime_"),
        known_slugs: Iterable[str] = (),
    ) -> None:
        """
        Asserts all feature columns start with asset_name or belong to expected_prefixes.
        Used to prevent data leakage during multi-asset training or inference.
        """
        slug = (self.contract_prefix or self.name).lower()
        asset_prefix = f"{slug}_"
        other_slugs = [s.lower() for s in known_slugs if s.lower() != slug]

        for col in df.columns:
            if col == "label":
                continue
            # Check if it belongs to this asset
            if col.startswith(asset_prefix) or col in self.custom_features:
                continue
            # Check if it's an allowed shared prefix
            if any(col.startswith(p) for p in expected_prefixes):
                continue
            # Check for explicitly known macro columns (for backward compatibility)
            if col in KNOWN_MACRO_COLUMNS:
                continue
            # Check if it belongs to ANOTHER asset (leakage)
            for other in other_slugs:
                if col.startswith(f"{other}_"):
                    raise FeatureMismatchError(
                        f"{self.name}: column '{col}' belongs to asset '{other}' "
                        f"but appears in {self.name}'s feature set. "
                        f"Cross-asset feature leakage detected."
                    )
            # If we got here, it's unrecognized
            raise FeatureMismatchError(
                f"{self.name}: column '{col}' is unrecognized. "
                f"Valid features must start with '{asset_prefix}' or one of {expected_prefixes}."
            )


# Raw FRED series carried through compute_macro_derived unchanged.
# Must stay in sync with data/raw/macro_factors.parquet columns.
_RAW_MACRO_COLUMNS: set[str] = {
    "fed_funds",
    "ecb_rate",
    "us_2y",
    "us_10y",
    "breakeven_10y",
    "real_yield_10y",
    "dxy",
    "vix",
    "baa_spread",
    "jp_10y",
    "de_10y",
    "gb_10y",
    "ca_10y",
    "au_10y",
}

# Derived macro columns computed in compute_macro_derived().
# If new derived columns are added to builder.py they must be added here.
_DERIVED_MACRO_COLUMNS: set[str] = {
    "rate_diff",
    "rate_diff_delta_3m",
    "2y_yield_delta_63",
    "dxy_mom_63",
    "dxy_mom_21",
    "vix_ma21",
    "vix_delta_5",
    "us_jp_10y_spread",
    "ca_jp_10y_spread",
    "ca_jp_spread_mom_21",
    "ca_jp_spread_mom_5",
    "real_yield_delta_63",
    "breakeven_delta_63",
    "yield_slope",
    "fed_funds_delta_3m",
}

KNOWN_MACRO_COLUMNS: set[str] = _RAW_MACRO_COLUMNS | _DERIVED_MACRO_COLUMNS


def validate_no_cross_asset_leakage(
    df: pd.DataFrame,
    contract: FeatureContract,
    known_slugs: Iterable[str] = (),
) -> pd.DataFrame:
    contract.validate_no_cross_asset_leakage(df, known_slugs=known_slugs)
    return df
