from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("eigencapital.publication_lags")

# Publication delays in CALENDAR DAYS for raw FRED series.
# FRED observation dates are the period the data is *for*.
# To avoid look-ahead, we shift all values forward by the delay before use.
PUBLICATION_LAGS_RAW: dict[str, int] = {
    # Daily Treasury yields published ~6PM ET — shift 1d for strict safety
    "us_2y": 1,
    "us_10y": 1,
    # Breakeven / real yields derived from Treasury yields
    "breakeven_10y": 1,
    "real_yield_10y": 1,
    # Fed funds effective rate — published next business day
    "fed_funds": 1,
    # ECB rate — announced at meeting days; same-day availability
    "ecb_rate": 0,
    # VIX closing value — available at market close
    "vix": 0,
    # Trade-weighted USD — available at market close
    "dxy": 0,
    # Baa corporate spread — Moody's publishes daily
    "baa_spread": 1,
    # OECD long-term yields — monthly series, publication lag ~4-6 weeks
    "jp_10y": 30,
    "de_10y": 30,
    "gb_10y": 30,
    "ca_10y": 30,
    "au_10y": 30,
}

# Derived features that appear in contract.macro_filters.
# Each entry is the MAXIMUM publication lag among its raw constituents.
DERIVED_FEATURE_LAGS: dict[str, int] = {
    "rate_diff": 1,
    "2y_yield_delta_63": 1,
    "vix_ma21": 0,
    "vix_delta_5": 0,
    "dxy_mom_21": 0,
    "dxy_mom_63": 0,
    "real_yield_delta_63": 1,
    "breakeven_delta_63": 1,
    "us_jp_10y_spread": 30,
    "ca_jp_10y_spread": 30,
    "ca_jp_spread_mom_21": 30,
    "ca_jp_spread_mom_5": 30,
}

ALL_LAGS: dict[str, int] = {**PUBLICATION_LAGS_RAW, **DERIVED_FEATURE_LAGS}


def publication_lag(feature_name: str) -> int:
    return ALL_LAGS.get(feature_name, 0)


def apply_publication_lags(
    macro_df: pd.DataFrame,
    lags: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Shift every column in macro_df forward by its publication lag (calendar days).

    Columns not present in the lag dict are left untouched.
    """
    result = macro_df.copy()
    resolved = lags or PUBLICATION_LAGS_RAW
    for col in result.columns:
        lag = resolved.get(col, 0)
        if lag > 0:
            original_last = result[col].iloc[-1]
            result[col] = result[col].shift(lag)
            # carry the most recent value forward so we don't introduce NaNs
            if pd.notna(original_last):
                result[col] = result[col].ffill()
            logger.debug("Applied %dd publication lag to '%s'", lag, col)
    return result


def apply_lag_to_macro_derived(
    macro_derived: pd.DataFrame,
) -> pd.DataFrame:
    """Shift derived features in a macro-derived DataFrame.

    This is applied *after* compute_macro_derived() so it shifts the
    derived columns that correspond to contract-level macro_filters.
    """
    result = macro_derived.copy()
    for col in result.columns:
        lag = DERIVED_FEATURE_LAGS.get(col, 0)
        if lag > 0:
            original_last = result[col].iloc[-1]
            result[col] = result[col].shift(lag)
            if pd.notna(original_last):
                result[col] = result[col].ffill()
    return result


FEATURE_LAG_MATRIX: dict[str, int] = {
    # Map descriptive names to their source lag
    "rate_diff": 1,
    "rate_diff_delta_3m": 1,
    "yield_slope": 1,
    "fed_funds_delta_3m": 1,
    "2y_yield_delta_63": 1,
    "dxy_mom_63": 0,
    "dxy_mom_21": 0,
    "vix_ma21": 0,
    "vix_delta_5": 0,
    "us_jp_10y_spread": 30,
    "ca_jp_10y_spread": 30,
    "ca_jp_spread_mom_21": 30,
    "ca_jp_spread_mom_5": 30,
    "real_yield_delta_63": 1,
    "breakeven_delta_63": 1,
    "real_yield_10y": 1,
}


def audit_lookahead(
    features_df: pd.DataFrame,
    contract_name: str = "",
    lag_override: dict[str, int] | None = None,
) -> None:
    """Assert that no macro-derived feature column has suspiciously recent values.

    This is an advisory check — it logs warnings rather than raising.
    Run it after feature assembly to flag potential look-ahead issues.
    """
    resolved = {**FEATURE_LAG_MATRIX, **(lag_override or {})}
    row_count = len(features_df)
    if row_count < 2:
        return
    for col in features_df.columns:
        lag = resolved.get(col)
        if lag is None:
            continue
        if lag <= 0:
            continue
        latest_val = features_df[col].iloc[-1]
        earlier_val = features_df[col].iloc[-min(lag + 1, row_count)]
        if pd.isna(latest_val) or pd.isna(earlier_val):
            continue
        if col.endswith("_mom_21") or col.endswith("_mom_63"):
            continue
        logger.info(
            "Lag audit [%s] '%s': pub_lag=%dd, last=%s, %d-back=%s",
            contract_name,
            col,
            lag,
            latest_val,
            -min(lag + 1, row_count),
            earlier_val,
        )
