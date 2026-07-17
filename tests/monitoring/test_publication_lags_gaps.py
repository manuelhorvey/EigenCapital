import numpy as np
import pandas as pd

from features.publication_lags import (
    audit_lookahead,
    ALL_LAGS,
)


# ── audit_lookahead ──────────────────────────────────────────────────────────
# Covers previously uncovered lines: 136 (early return), 140 (None lag), 146 (NaN), 148 (mom skip)


def test_audit_lookahead_single_row_returns_early():
    """audit_lookahead returns early when df has < 2 rows (line 136)."""
    df = pd.DataFrame(
        {"rate_diff": [1.0]},
        index=pd.RangeIndex(1),
    )
    audit_lookahead(df, contract_name="TEST_SINGLE")


def test_audit_lookahead_empty_dataframe():
    """audit_lookahead returns early on empty DataFrame."""
    df = pd.DataFrame()
    audit_lookahead(df, contract_name="TEST_EMPTY")


def test_audit_lookahead_skips_unknown_columns():
    """Columns not in FEATURE_LAG_MATRIX are skipped (line 140)."""
    df = pd.DataFrame(
        {"rate_diff": np.random.randn(10), "unknown_col": np.random.randn(10)},
        index=pd.RangeIndex(10),
    )
    audit_lookahead(df, contract_name="TEST_UNKNOWN")


def test_audit_lookahead_skips_columns_with_nan():
    """Columns where latest or earlier value is NaN are skipped (line 146)."""
    df = pd.DataFrame(
        {
            "rate_diff": [np.nan] + list(np.random.randn(9)),
            "us_jp_10y_spread": list(np.random.randn(9)) + [np.nan],
        },
        index=pd.RangeIndex(10),
    )
    audit_lookahead(df, contract_name="TEST_NAN_COLUMNS")


def test_audit_lookahead_skips_momentum_columns():
    """Columns ending in _mom_21 or _mom_63 are skipped (line 148)."""
    df = pd.DataFrame(
        {
            "rate_diff": np.random.randn(50),
            "us_jp_10y_spread": np.random.randn(50),
            "ca_jp_spread_mom_21": np.random.randn(50),
            "dxy_mom_63": np.random.randn(50),
            "some_mom_21": np.random.randn(50),
        },
        index=pd.RangeIndex(50),
    )
    audit_lookahead(df, contract_name="TEST_MOM_SKIP")


def test_audit_lookahead_with_lag_override():
    """audit_lookahead accepts a lag_override dict."""
    df = pd.DataFrame(
        {"rate_diff": np.random.randn(50), "custom_feat": np.random.randn(50)},
        index=pd.RangeIndex(50),
    )
    audit_lookahead(df, contract_name="TEST_OVERRIDE", lag_override={"custom_feat": 5})


def test_audit_lookahead_finds_lag_columns():
    """All lag > 0 columns in FEATURE_LAG_MATRIX are checked."""
    df = pd.DataFrame(
        {
            "rate_diff": np.random.randn(50),
            "us_jp_10y_spread": np.random.randn(50),
            "vix_ma21": np.random.randn(50),
        },
        index=pd.RangeIndex(50),
    )
    audit_lookahead(df, contract_name="TEST_FEATURES")


def test_all_lags_consistency():
    """ALL_LAGS contains all entries from both PUBLICATION_LAGS_RAW and DERIVED_FEATURE_LAGS."""
    from features.publication_lags import PUBLICATION_LAGS_RAW, DERIVED_FEATURE_LAGS

    for k, v in PUBLICATION_LAGS_RAW.items():
        assert ALL_LAGS[k] == v
    for k, v in DERIVED_FEATURE_LAGS.items():
        assert ALL_LAGS[k] == v
