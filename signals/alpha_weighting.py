import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("quorrin.alpha_weighting")

DEFAULT_WEIGHTS = {
    "carry_vol_adj": 0.25,
    "mom_21d": 0.15,
    "mom_63d": 0.10,
    "mom_126d": 0.05,
    "mom_252d": 0.05,
    "zscore_20": -0.10,
    "vol_ratio": 0.00,
    "dow_signal": 0.05,
}

CROSS_ASSET_WEIGHTS = {
    "dxy_mom_21d": 0.15,
    "vix_mom_5d": 0.05,
    "spx_mom_5d": 0.05,
    "WTI_mom_21d": 0.00,
}


def normalize_to_unit(x: pd.Series) -> pd.Series:
    """Robust scaling to [-1, 1] using 1st/99th percentiles."""
    lo, hi = x.quantile([0.01, 0.99])
    scale = max(abs(hi - lo), 1e-10)
    clipped = x.clip(lo, hi)
    return 2 * (clipped - lo) / scale - 1


def compute_asset_signals(
    alpha_df: pd.DataFrame,
    asset_weights: dict[str, float] | None = None,
    normalize: bool = True,
) -> pd.DataFrame:
    """
    Combine per-asset alpha features into composite signals.

    Parameters
    ----------
    alpha_df : pd.DataFrame
        Output of build_alpha_features().
    asset_weights : dict, optional
        Feature weights keyed by suffix (e.g. 'carry_vol_adj').
        Negative weights mean the feature is used as a contrary indicator.
        Defaults to DEFAULT_WEIGHTS.
    normalize : bool
        Whether to normalise each column to [-1, 1] before weighting.

    Returns
    -------
    pd.DataFrame with one column per asset in [-1, 1].
    """
    if asset_weights is None:
        asset_weights = DEFAULT_WEIGHTS

    suffixes = set(asset_weights.keys())
    prefix_counts: dict[str, int] = {}
    for col in alpha_df.columns:
        if "_" in col:
            prefix, suffix = col.split("_", 1)
            if suffix in suffixes:
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    asset_prefixes = {p for p, c in prefix_counts.items() if c >= 2}

    signals = pd.DataFrame(index=alpha_df.index)
    for asset in sorted(asset_prefixes):
        total = pd.Series(0.0, index=alpha_df.index)
        weight_sum = 0.0
        for suffix, w in asset_weights.items():
            col = f"{asset}_{suffix}"
            if col not in alpha_df.columns:
                continue
            series = alpha_df[col].fillna(0.0)
            if normalize:
                series = normalize_to_unit(series)
            total += w * series
            weight_sum += abs(w)

        if weight_sum > 0:
            total /= weight_sum
        signals[asset] = total.clip(-1, 1)

    return signals


def compute_cross_asset_overlay(
    alpha_df: pd.DataFrame,
    cross_weights: dict[str, float] | None = None,
) -> pd.Series:
    """
    Combine cross-asset features into a single overlay signal.

    This overlay is applied equally to all asset signals and represents
    broad macro/sentiment conditions (USD strength, risk appetite, etc.).

    Parameters
    ----------
    alpha_df : pd.DataFrame
        Output of build_alpha_features().
    cross_weights : dict, optional
        Weights for cross-asset columns. Defaults to CROSS_ASSET_WEIGHTS.

    Returns
    -------
    pd.Series in [-1, 1] — one value per timestamp.
    """
    if cross_weights is None:
        cross_weights = CROSS_ASSET_WEIGHTS

    overlay = pd.Series(0.0, index=alpha_df.index)
    weight_sum = 0.0
    for col, w in cross_weights.items():
        if col not in alpha_df.columns or w == 0.0:
            continue
        series = alpha_df[col].fillna(0.0)
        overlay += w * normalize_to_unit(series)
        weight_sum += abs(w)

    if weight_sum > 0:
        overlay /= weight_sum
    return overlay.clip(-1, 1)


def generate_weighted_signals(
    alpha_df: pd.DataFrame,
    asset_weights: dict[str, float] | None = None,
    cross_weights: dict[str, float] | None = None,
    overlay_strength: float = 0.2,
) -> pd.DataFrame:
    """
    Full weighting pipeline: per-asset + cross-asset overlay.

    Parameters
    ----------
    alpha_df : pd.DataFrame
        Output of build_alpha_features().
    asset_weights : dict, optional
        Per-asset feature weights. See compute_asset_signals().
    cross_weights : dict, optional
        Cross-asset overlay weights. See compute_cross_asset_overlay().
    overlay_strength : float
        How much the cross-asset overlay shifts asset signals (0 = none).

    Returns
    -------
    pd.DataFrame with columns:
        {ASSET}_signal : composite signal in [-1, 1]
        {ASSET}_raw    : un-adjusted per-asset weighted signal
        overlay        : cross-asset overlay (same for all assets)
    """
    asset_sigs = compute_asset_signals(alpha_df, asset_weights)
    overlay = compute_cross_asset_overlay(alpha_df, cross_weights)

    result = pd.DataFrame(index=alpha_df.index)
    result["overlay"] = overlay
    for asset in asset_sigs.columns:
        raw = asset_sigs[asset]
        result[f"{asset}_raw"] = raw
        adjusted = raw + overlay_strength * overlay
        result[f"{asset}_signal"] = adjusted.clip(-1, 1)

    return result
