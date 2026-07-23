"""Immutable experiment fingerprint — SHA256 of all non-labeling parameters.

Ensures all experiments are directly comparable by recording every
parameter that is NOT the labeling strategy. If any two experiments
share the same fingerprint, their only difference is the labeling
configuration — making them a valid controlled comparison.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_fingerprint(
    asset: str,
    n_folds: int = 3,
    gap: int = 20,
    min_train: int = 100,
    window_type: str = "expanding",
    rolling_window_bars: int = 756,
    max_depth: int = 2,
    n_estimators: int = 300,
    learning_rate: float = 0.02,
    objective: str = "binary:logistic",
    random_state: int = 42,
    early_stopping_rounds: int = 50,
    validation_split: float = 0.2,
    signal_buy_threshold: float = 0.55,
    signal_sell_threshold: float = 0.45,
    calibrate_enabled: bool = False,
    calibrator_bins: int = 10,
    alpha_features_enabled: bool = True,
    regime_features_enabled: bool = True,
    positioning_features_enabled: bool = True,
    rates_features_enabled: bool = True,
    event_features_enabled: bool = True,
    macro_filters: tuple[str, ...] = (),
    price_mom_windows: tuple[int, ...] = (),
    vs_spy_windows: tuple[int, ...] = (),
    custom_features: tuple[str, ...] = (),
    # Known non-contributing components captured for completeness
    _data_source: str = "yfinance+expanded",
) -> str:
    """Deterministic SHA256 digest of the execution pipeline.

    Returns a 16-character hex prefix for readable comparison.
    """
    blob: dict[str, Any] = {
        "fingerprint_version": 1,
        "asset": asset,
        "walk_forward": {
            "n_folds": n_folds,
            "gap": gap,
            "min_train": min_train,
            "window_type": window_type,
            "rolling_window_bars": rolling_window_bars,
        },
        "model": {
            "max_depth": max_depth,
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "objective": objective,
            "random_state": random_state,
            "early_stopping_rounds": early_stopping_rounds,
            "validation_split": validation_split,
        },
        "signal": {
            "buy_threshold": signal_buy_threshold,
            "sell_threshold": signal_sell_threshold,
        },
        "calibration": {
            "enabled": calibrate_enabled,
            "n_bins": calibrator_bins,
        },
        "features": {
            "alpha": alpha_features_enabled,
            "regime": regime_features_enabled,
            "positioning": positioning_features_enabled,
            "rates": rates_features_enabled,
            "event": event_features_enabled,
            "macro_filters": sorted(macro_filters),
            "price_mom_windows": sorted(price_mom_windows),
            "vs_spy_windows": sorted(vs_spy_windows),
            "custom_features": sorted(custom_features),
        },
        "data_source": _data_source,
    }
    raw = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:16]


def fingerprint_for_asset(asset: str) -> str:
    """Compute the production fingerprint for an asset using its FEATURE_REGISTRY config."""
    from features.registry import FEATURE_REGISTRY
    contract = None
    for c in FEATURE_REGISTRY.values():
        if c.name == asset:
            contract = c
            break
    if contract is None:
        return compute_fingerprint(asset)

    return compute_fingerprint(
        asset=asset,
        n_folds=3,
        gap=20,
        min_train=100,
        window_type="expanding",
        rolling_window_bars=756,
        macro_filters=contract.macro_filters,
        price_mom_windows=contract.price_mom_windows,
        vs_spy_windows=contract.vs_spy_windows,
        custom_features=contract.custom_features,
    )
