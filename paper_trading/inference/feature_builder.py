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

import pandas as pd
import ta

from features.data_fetch import _cycle_id
from features.regime_features import generate_regime_features

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
        self._regime_cache_cycle: tuple = (-1,)
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
            asset.name,
            asset.ticker,
            macro_data=shared_macro,
        )

        if self._truncate_inference:
            _trunc_rows = _MAX_INDICATOR_LOOKBACK + 256
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
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            index=hist_prices.index,
        )

        # ── Alpha features ──────────────────────────────────────────
        ohlcv = fetch_asset_ohlcv(asset.ticker)
        alpha_df = build_alpha_features(
            hist_prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
            shared_features=shared_features,
            ohlcv=ohlcv,
        )
        alpha_idx = alpha_df.index

        # ── Cross-sectional features (Group 1) ──────────────────────
        # Lazily assembles the full price panel and computes momentum
        # ranks, cross-sectional z-scores, and DXY/SPX correlations.
        # Only adds columns that exist in the training schema (avoids
        # silent schema drift if models are not yet retrained).
        xs_df = self._compute_cross_sectional_for_asset(
            asset,
            alpha_idx,
            shared_macro,
        )
        if xs_df is not None and not xs_df.empty:
            for col in xs_df.columns:
                alpha_df[col] = xs_df[col].reindex(alpha_idx)

        # ── Positioning features (Group 2 — volume momentum) ─────────
        from features.positioning_features import check_oi_availability, compute_volume_features

        prefix = asset.name.upper()
        vol_df = compute_volume_features(ohlcv)
        if vol_df is not None and not vol_df.empty:
            for col in vol_df.columns:
                alpha_df[f"{prefix}_{col}"] = vol_df[col].reindex(alpha_idx)
        alpha_df[f"{prefix}_oi_available"] = check_oi_availability(asset.ticker)

        # ── Rates & carry features (Group 3) ─────────────────────────
        from features.rates_features import compute_all as compute_rates

        rd_series = (
            rate_diffs[asset.name]
            if rate_diffs is not None and asset.name in rate_diffs.columns
            else pd.Series(0.0, index=alpha_idx)
        )
        rates_df = compute_rates(shared_macro or {}, rd_series, alpha_idx)
        if rates_df is not None and not rates_df.empty:
            for col in rates_df.columns:
                alpha_df[f"{prefix}_{col}"] = rates_df[col].reindex(alpha_idx)

        # ── Event & calendar features (Group 4) ─────────────────────
        from features.event_features import compute_event_features

        event_df = compute_event_features(alpha_idx)
        if event_df is not None and not event_df.empty:
            for col in event_df.columns:
                alpha_df[f"{prefix}_{col}"] = event_df[col].reindex(alpha_idx)

        # ── Lead-lag custom features from FeatureContract ────────────
        # Custom features like gc_lead_1 are computed as lagged returns
        # of the leader asset. Uses the same OHLCV data pipeline as the
        # asset's own features.
        _custom_feats = getattr(asset.contract, "custom_features", ())
        if _custom_feats:
            from features.lead_lag_features import load_lead_lag_edges

            _edges = load_lead_lag_edges()
            _leader_cache_local: dict[str, pd.Series] = {}
            for _edge in _edges:
                if _edge.get("target") != asset.ticker:
                    continue
                _col = _edge.get("column", "")
                if _col not in _custom_feats or _col in alpha_df.columns:
                    continue
                _leader_ticker = _edge.get("leader", "")
                _lag = _edge.get("lag", 1)
                if _leader_ticker not in _leader_cache_local:
                    try:
                        _lohlcv = fetch_asset_ohlcv(_leader_ticker)
                        if _lohlcv is not None and not _lohlcv.empty and "close" in _lohlcv.columns:
                            _leader_cache_local[_leader_ticker] = _lohlcv["close"]
                        else:
                            logger.warning(
                                "%s: leader OHLCV empty for %s — skipping '%s'",
                                asset.name,
                                _leader_ticker,
                                _col,
                            )
                            continue
                    except (OSError, ValueError, KeyError) as _exc:
                        logger.warning(
                            "%s: failed to fetch leader %s for '%s': %s",
                            asset.name,
                            _leader_ticker,
                            _col,
                            _exc,
                        )
                        continue
                _leader_close = _leader_cache_local.get(_leader_ticker)
                if _leader_close is not None:
                    _lret = _leader_close.pct_change().dropna()
                    alpha_df[_col] = _lret.shift(_lag).reindex(alpha_idx)
                    logger.info(
                        "%s: added lead-lag feature '%s' at inference (leader=%s, lag=%d)",
                        asset.name,
                        _col,
                        _leader_ticker,
                        _lag,
                    )

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
            archetype_df["adx"] = ta.trend.adx(ohlcv["high"], ohlcv["low"], ohlcv["close"], window=14).reindex(
                alpha_idx
            )
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
                raw_regime = generate_regime_features(ohlcv)[0]
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

    def _compute_cross_sectional_for_asset(
        self,
        asset: Any,
        alpha_idx: pd.Index,
        shared_macro: dict[str, Any] | None = None,
    ) -> pd.DataFrame | None:
        """Compute cross-sectional features for a single asset.

        Assembles the full 22-asset price panel lazily (cycle-cached),
        computes all Group 1 features, and returns only the current
        asset's ``xs_`` prefixed columns aligned to *alpha_idx*.

        Returns ``None`` when the full panel cannot be assembled (e.g.
        ``_all_assets`` not in *shared_macro*, or insufficient data).
        """
        from features.cross_sectional import compute_all as compute_xs
        from features.data_fetch import _get_cycle_cached, _set_cycle_cache, fetch_asset_data

        all_assets = (shared_macro or {}).get("_all_assets")
        if not all_assets:
            return None

        # Lazy full panel — cycle-cached so only the first caller pays
        cached = _get_cycle_cached("_full_panel")
        if cached is not None:
            full_panel = cached
        else:
            panel: dict[str, pd.Series] = {}
            for asset_name, ticker in all_assets.items():
                try:
                    prices, _, _, _, _, _ = fetch_asset_data(asset_name, ticker)
                    if prices is not None and not prices.empty:
                        panel[asset_name] = prices.iloc[:, 0]
                except (OSError, ValueError, KeyError, RuntimeError):
                    continue
            full_panel = pd.DataFrame(panel).ffill().dropna(how="all")
            _set_cycle_cache("_full_panel", full_panel)

        if full_panel.empty or len(full_panel.columns) < 2:
            return None

        # Extract DXY/SPX from shared_macro for benchmark correlations
        dxy_s = (shared_macro or {}).get("DX-Y.NYB", pd.Series(dtype=float))
        spx_s = (shared_macro or {}).get("^GSPC", pd.Series(dtype=float))

        # Compute all cross-sectional features, align to alpha index
        xs_full = compute_xs(full_panel, dxy=dxy_s, spx=spx_s)
        prefix = asset.name.upper()
        asset_cols = [c for c in xs_full.columns if c.startswith(f"{prefix}_xs_")]
        if not asset_cols:
            return None

        xs_aligned = xs_full[asset_cols].reindex(alpha_idx).ffill()
        return xs_aligned.fillna(0.0)

    def reset(self) -> None:
        """Clear regime feature cache.  Call in test fixtures."""
        self._regime_features_cache = None
        self._regime_cache_cycle = (-1,)
