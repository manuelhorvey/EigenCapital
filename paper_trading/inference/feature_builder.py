"""Feature builder — alpha, archetype, and regime feature construction.

Extracted from ``AssetInferencePipeline._build_feature_set`` as part of
MAINT-01 (split oversized modules).  Owns the feature computation logic
including alpha features, archetype indicators, and regime features.

Usage:
    builder = FeatureBuilder()
    alpha_df, features_df, x = builder.build(asset, df, shared_macro=None)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import ta

from features.regime_features import generate_regime_features
from features.data_fetch import _cycle_id

logger = logging.getLogger("eigencapital.feature_builder")

# Maximum lookback for indicator computation (matches training convention)
_MAX_INDICATOR_LOOKBACK = 253


class FeatureBuilder:
    """Constructs the full feature matrix for a single asset inference cycle.

    Owns caching for regime features across cycles (avoids recomputing
    when regime sizing is enabled).  Thread-safe when one instance is
    used per asset.

    Usage:
        builder = FeatureBuilder()
        alpha_df, features_df, x = builder.build(asset, df, shared_macro=None)
    """

    def __init__(self) -> None:
        self._regime_features_cache: pd.DataFrame | None = None
        self._regime_cache_cycle: int = -1
        self._truncate_inference: bool = True

    def build(
        self,
        asset: Any,
        df: pd.DataFrame,
        shared_macro: dict[str, pd.Series] | None = None,
        truncate: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Build the full feature set for an asset.

        Args:
            asset: The asset engine (must have ``name``, ``ticker``, ``config``).
            df: OHLCV price DataFrame with a ``close`` column.
            shared_macro: Optional pre-fetched macro data (DXY, VIX, SPX, commodities).
            truncate: Whether to truncate data to ``_MAX_INDICATOR_LOOKBACK + 50`` rows.

        Returns:
            ``(alpha_df, features_df, x)`` where:
            - ``alpha_df`` contains all alpha feature columns
            - ``features_df`` concatenates alpha + archetype + regime features
            - ``x`` is the model input matrix (selected alpha columns only)
        """
        from features.alpha_features import _compute_shared_features, build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv

        self._truncate_inference = truncate

        # ── Fetch raw data ──────────────────────────────────────────
        hist_prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(
            asset.name, asset.ticker, macro_data=shared_macro,
        )

        if self._truncate_inference:
            _trunc_rows = _MAX_INDICATOR_LOOKBACK + 50
            hist_prices = hist_prices.iloc[-_trunc_rows:]
            if not rate_diffs.empty:
                rate_diffs = rate_diffs.iloc[-_trunc_rows:]
            dxy = dxy.iloc[-_trunc_rows:]
            vix = vix.iloc[-_trunc_rows:]
            spx = spx.iloc[-_trunc_rows:]
            if not commodities.empty:
                commodities = commodities.iloc[-_trunc_rows:]

        # ── Cross-asset features ────────────────────────────────────
        shared_features = _compute_shared_features(
            dxy=dxy, vix=vix, spx=spx, commodities=commodities,
            index=hist_prices.index,
        )

        # ── Alpha features ──────────────────────────────────────────
        ohlcv = fetch_asset_ohlcv(asset.ticker)
        alpha_df = build_alpha_features(
            hist_prices, rate_diffs,
            dxy=dxy, vix=vix, spx=spx, commodities=commodities,
            shared_features=shared_features, ohlcv=ohlcv,
        )
        alpha_idx = alpha_df.index

        # ── Archetype features (EMA, ADX, RSI, Bollinger) ───────────
        if not ohlcv.empty:
            if self._truncate_inference:
                ohlcv = ohlcv.iloc[-_trunc_rows:]
            ohlcv = ohlcv.reindex(alpha_idx).ffill()

        archetype_df = pd.DataFrame(index=alpha_idx)
        if not ohlcv.empty:
            ema_20 = ta.trend.ema_indicator(ohlcv["close"], window=20)
            ema_50 = ta.trend.ema_indicator(ohlcv["close"], window=50)
            archetype_df["ema_spread"] = ((ema_20 - ema_50) / ema_50).reindex(alpha_idx)
            archetype_df["adx"] = ta.trend.adx(
                ohlcv["high"], ohlcv["low"], ohlcv["close"], window=14
            ).reindex(alpha_idx)
            archetype_df["rsi"] = ta.momentum.rsi(ohlcv["close"], window=14).reindex(alpha_idx)
            bb = ta.volatility.BollingerBands(ohlcv["close"], window=20, window_dev=2)
            bb_mavg = bb.bollinger_mavg()
            bb_std = bb.bollinger_hband() - bb_mavg
            archetype_df["bb_zscore"] = ((ohlcv["close"] - bb_mavg) / (bb_std / 2)).reindex(alpha_idx)
        archetype_df = archetype_df.bfill()

        # ── Regime features (cached per cycle) ──────────────────────
        regime_inference_df = pd.DataFrame(index=alpha_idx)
        if not ohlcv.empty:
            cache_key = (_cycle_id, asset.name)
            if self._regime_cache_cycle != cache_key:
                raw_regime = generate_regime_features(ohlcv)
                self._regime_features_cache = raw_regime
                self._regime_cache_cycle = cache_key
            else:
                raw_regime = self._regime_features_cache
            prefix = asset.name.upper()
            renaming = {col: f"{prefix}_{col}" for col in raw_regime.columns}
            prefixed = raw_regime.rename(columns=renaming)
            common_idx = alpha_idx.intersection(prefixed.index)
            regime_inference_df = prefixed.reindex(common_idx)

        # ── Build model input matrix ────────────────────────────────
        feature_cols = getattr(asset, "_alpha_feature_cols", None)
        if not feature_cols:
            feature_cols = list(alpha_df.columns)
            asset._alpha_feature_cols = feature_cols
        available = [c for c in feature_cols if c in alpha_df.columns]
        if not available:
            raise ValueError(f"No alpha feature columns found for {asset.name}")
        x = alpha_df[available]
        features_df = pd.concat([alpha_df, archetype_df, regime_inference_df], axis=1)

        # Detect risk-off regime (sets asset._risk_off for downstream gates)
        self._detect_risk_off(asset, features_df)

        return alpha_df, features_df, x

    @staticmethod
    def _detect_risk_off(asset, features_df) -> None:
        """Detect risk-off regime and set _risk_off flag on the asset.

        Only activates for assets with risk_off_enabled: true in config.
        When VIX is rising and SPX is falling, risk-off is flagged.
        """
        if not asset.config.get("risk_off_enabled", False):
            asset._risk_off = False
            return
        try:
            vix_mom = features_df["vix_mom_5d"].iloc[-1]
            spx_mom = features_df["spx_mom_5d"].iloc[-1]
            asset._risk_off = vix_mom > 0.0 and spx_mom < 0.0
        except (KeyError, IndexError):
            asset._risk_off = False

    def reset(self) -> None:
        """Clear regime feature cache.  Call in test fixtures."""
        self._regime_features_cache = None
        self._regime_cache_cycle = -1
