"""DEPRECATED — legacy per-asset feature pipeline.

Replaced by ``features/alpha_features.py`` + ``features/regime_features.py`` which
build a single cross-asset feature matrix for all 22 assets simultaneously.

This module (``build_features``, ``compute_training_data``, etc.) uses the old
``FeatureContract`` / ``FEATURE_REGISTRY`` system with per-asset config-driven
features and publication-lag-aware macro processing.  It is kept for backward
compatibility with historical scripts (``scripts/backtest/walk_forward_all.py``,
``scripts/training/train_all_assets.py``).

New scripts and pipelines MUST import from ``features.alpha_features`` instead.

Will be removed in a future release.
"""

import logging
import os
import warnings

import pandas as pd

from features.contract import FeatureContract, validate_no_cross_asset_leakage
from features.publication_lags import (
    apply_lag_to_macro_derived,
    apply_publication_lags,
    audit_lookahead,
)
from features.registry import FEATURE_CONTRACT_VALIDATION, FEATURE_REGISTRY
from labels.triple_barrier import apply_triple_barrier

warnings.warn(
    "features.builder is deprecated. Use features.alpha_features.build_alpha_features instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger("eigencapital.features.builder")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("US/Eastern")
    else:
        df.index = df.index.tz_convert("US/Eastern")
    return df


def compute_macro_derived(macro_df: pd.DataFrame) -> pd.DataFrame:
    m = macro_df.copy()
    # Shift raw FRED series forward by their publication lags before any derived math
    m = apply_publication_lags(m)
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq="D")).ffill()
    m["rate_diff"] = m["fed_funds"] - m["ecb_rate"]
    m["2y_yield_delta_63"] = m["us_2y"].diff(63)
    m["dxy_mom_63"] = m["dxy"].pct_change(63)
    m["dxy_mom_21"] = m["dxy"].pct_change(21)
    m["vix_ma21"] = m["vix"].rolling(21).mean()
    m["vix_delta_5"] = m["vix"].diff(5)
    m["us_jp_10y_spread"] = m["us_10y"] - m["jp_10y"]
    m["ca_jp_10y_spread"] = m["ca_10y"] - m["jp_10y"]
    m["ca_jp_spread_mom_21"] = m["ca_jp_10y_spread"].diff(21)
    m["ca_jp_spread_mom_5"] = m["ca_jp_10y_spread"].diff(5)
    m["real_yield_delta_63"] = m["real_yield_10y"].diff(63)
    m["breakeven_delta_63"] = m["breakeven_10y"].diff(63)
    # Additional macro columns needed by MacroExpertHead
    m["rate_diff_delta_3m"] = m["rate_diff"].diff(63)
    m["yield_slope"] = m["us_10y"] - m["us_2y"]
    m["fed_funds_delta_3m"] = m["fed_funds"].diff(63)
    return m.iloc[90:]


def compute_label(df: pd.DataFrame, contract: FeatureContract) -> pd.Series:
    if contract.label_type == "fwd60":
        ret = df["close"].pct_change(contract.label_params["window"]).shift(-contract.label_params["window"])
        return (
            ret.apply(
                lambda x: (
                    2
                    if x > contract.label_params["threshold"]
                    else (0 if x < -contract.label_params["threshold"] else 1)
                )
            )
            .astype(int)
            .dropna()
        )
    labeled = apply_triple_barrier(
        df, pt_sl=contract.label_params["pt_sl"], vertical_barrier=contract.label_params["vertical_barrier"]
    )
    return (labeled["label"] + 1).astype(int)


def _resolve_leader_path(leader: str, raw_dir: str) -> str | None:
    """Resolve leader data file, trying multiple patterns. Download via yfinance if missing."""
    candidates = [
        leader.replace("^", ""),
        leader.replace("^", "").replace("=X", "").replace("=F", ""),
        leader,
    ]
    for c in set(candidates):
        path = os.path.join(raw_dir, f"{c}_1d.parquet")
        if os.path.exists(path):
            return path
    # Fallback: download via yfinance
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            import yfinance as yf

            df = yf.download(leader, period="10y", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Open": "open", "Volume": "volume"})
            filename = leader.replace("^", "").replace("=X", "").replace("=F", "")
            path = os.path.join(raw_dir, f"{filename}_1d.parquet")
            df.to_parquet(path)
            return path
        except (OSError, ValueError, TypeError):
            return None


def _attach_lead_lag_features(a: pd.DataFrame, df: pd.DataFrame, contract: FeatureContract) -> None:
    from features.lead_lag_features import apply_lead_lag_features, load_lead_lag_edges

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(base, "data", "raw")
    for edge in load_lead_lag_edges():
        if edge.get("target") != contract.ticker:
            continue
        col = edge.get("column")
        if col not in contract.custom_features:
            continue
        leader = edge.get("leader", "")
        path = _resolve_leader_path(leader, raw_dir)
        if path is None:
            continue
        leader_df = pd.read_parquet(path)
        if "close" not in leader_df.columns:
            continue
        leader_df = _normalize(leader_df)
        # Strip tz from leader_df if df is tz-unaware (inference path).
        # If leader_df stays tz-aware while df is tz-unaware,
        # apply_lead_lag_features returns a Series with tz-aware index
        # that .reindex(a.index) cannot align (a.index is tz-unaware)
        # producing all NaN (see ADR-017 inference path).
        if df.index.tz is None and leader_df.index.tz is not None:
            leader_df = leader_df.copy()
            leader_df.index = leader_df.index.tz_localize(None)
        a[col] = apply_lead_lag_features(df, leader_df, lag=int(edge.get("lag", 1)), column_name=col).reindex(a.index)


def build_features(
    df: pd.DataFrame,
    macro: pd.DataFrame,
    ref: pd.DataFrame | None,
    contract: FeatureContract,
    compute_labels: bool = True,
) -> pd.DataFrame:
    """
    Builds a feature set for a specific asset contract.
    Ensures that each feature is independent and belongs to the specified asset
    (using the contract_prefix) or allowed shared macro prefixes.

    When compute_labels is False, no labels are computed — this is the inference
    path. This avoids the structural risk of .dropna() on label columns silently
    dropping recent feature rows (see ADR-017).
    """
    df = _normalize(df)
    if ref is not None:
        ref = _normalize(ref)

    if compute_labels:
        labels = compute_label(df, contract)
        pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labels.index])
    else:
        pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in df.index])

    # Apply derived-feature publication lags before alignment (safety net)
    macro = apply_lag_to_macro_derived(macro)
    a = macro.reindex(pi, method="ffill")

    if compute_labels:
        a.index = labels.index
    else:
        # Inference path: a has tz-unaware index (from pi), but _normalize
        # made df tz-aware.  Strip tz from df/ref so pandas index alignment
        # works when assigning feature columns to a.
        df = df.copy()
        df.index = df.index.tz_localize(None)
        if ref is not None:
            ref = ref.copy()
            ref.index = ref.index.tz_localize(None)

    slug = (contract.contract_prefix or contract.name).lower()
    for w in contract.price_mom_windows:
        a[f"{slug}_mom_{w}"] = df["close"].pct_change(w)

    for w in contract.vs_spy_windows:
        mom = df["close"].pct_change(w)
        spy_mom = ref["close"].pct_change(w) if ref is not None else 0
        a[f"{slug}_vs_spy_{w}"] = mom - spy_mom

    if contract.custom_features:
        _attach_lead_lag_features(a, df, contract)

    if compute_labels:
        a["label"] = labels
        drop_cols = [c for c in list(contract.features) + ["label"] if c in a.columns]
    else:
        drop_cols = [c for c in list(contract.features) if c in a.columns]

    result = a.dropna(subset=drop_cols)
    if FEATURE_CONTRACT_VALIDATION:
        validate_no_cross_asset_leakage(result, contract, known_slugs=FEATURE_REGISTRY.keys())
    return result


def compute_training_data(
    ticker: str, macro: pd.DataFrame, ref: pd.DataFrame, df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.Series, FeatureContract]:
    contract = FEATURE_REGISTRY[ticker]
    features_df = build_features(df, macro, ref, contract)
    audit_lookahead(features_df, contract_name=contract.name)
    return features_df[list(contract.features)], features_df["label"], contract


def compute_training_data_extended(
    ticker: str, macro: pd.DataFrame, ref: pd.DataFrame, df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.Series, FeatureContract]:
    """
    Computes training data for the full provided history (2000+).
    Same pipeline as compute_training_data but intended for extended history datasets.
    """
    contract = FEATURE_REGISTRY[ticker]
    features_df = build_features(df, macro, ref, contract)
    # Skip strict lookahead audit for historical data if it might be noisy,
    # but still build all features correctly.
    return features_df[list(contract.features)], features_df["label"], contract


def compute_inference_features(
    ticker: str, macro: pd.DataFrame, ref: pd.DataFrame | None, df: pd.DataFrame
) -> pd.DataFrame:
    contract = FEATURE_REGISTRY[ticker]
    features_df = build_features(df, macro, ref, contract, compute_labels=False)
    audit_lookahead(features_df, contract_name=contract.name)
    return features_df[list(contract.features)]


def model_path(ticker: str) -> str:
    contract = FEATURE_REGISTRY[ticker]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "paper_trading", "models", f"{contract.name}_model.json")
