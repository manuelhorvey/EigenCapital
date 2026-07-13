"""DEPRECATED — legacy per-asset feature functions.

Replaced by ``features/alpha_features.py`` which builds unified cross-asset
features with per-asset factor groups and trend-exhaustion indicators.

This module contains per-asset feature builders (``build_eurusd_features``,
``build_usdjpy_features``, etc.) from the ``FeatureContract`` era.  They are
no longer used in production and are kept only for historical script compat.

Will be removed in a future release.
"""

import warnings

import pandas as pd
import yfinance as yf

from features.publication_lags import apply_lag_to_macro_derived

warnings.warn(
    "features.pair_specific is deprecated. Use features.alpha_features instead.",
    DeprecationWarning,
    stacklevel=2,
)


def yf_download_safe(symbol, start="2008-01-01", end="2026-12-31"):
    try:
        df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Open": "open", "Volume": "volume"})
        df.index = pd.to_datetime(df.index)
        return df
    except (KeyError, ValueError, TypeError, OSError):
        return None


def build_lead_lag_features(target_price, other_asset_price, lag=3):
    """
    Exposes lead-lag relationship as a feature.
    If other_asset leads target_price by 'lag' days, this returns that lagged signal.
    """
    other_rets = other_asset_price["close"].pct_change()
    return other_rets.shift(lag)


def build_nzdjpy_features(price, macro):
    """
    NZDJPY: classic carry trade pair
    Primary driver: VIX (risk appetite, stability=1.11)
    Asymmetric: VIX bull/bear asymmetry = 0.428
    Optimal lag: VIX at 21 days
    """
    macro = apply_lag_to_macro_derived(macro)
    labeled = apply_triple_barrier_caller(price, pt_sl=[2, 2], vertical_barrier=20)
    pi = (
        labeled.index.tz_localize(None)
        if hasattr(labeled.index, "tz") and labeled.index.tz is not None
        else labeled.index
    )
    a = macro.reindex(pi, method="ffill")
    a.index = labeled.index

    a["vix_ma21"] = a["vix"].rolling(21).mean()
    a["vix_delta_5"] = a["vix"].diff(5)
    a["us_jp_10y_spread"] = a["us_10y"] - a["jp_10y"]
    a["nzdjpy_mom_21"] = price["close"].pct_change(21)
    a["nzdjpy_mom_63"] = price["close"].pct_change(63)

    features = ["vix_ma21", "vix_delta_5", "us_jp_10y_spread", "nzdjpy_mom_21"]
    clean = a.dropna(subset=features)
    clean["label"] = (labeled.loc[clean.index, "label"] + 1).astype(int)
    return clean, features


def build_eurusd_features(price, macro):
    """
    EURUSD: bilateral rate differential + lagged cross-asset spillover
    Primary driver: dxy_mom_21 (stability=2.022)
    Added: lagged DXY (momentum persistence), lagged gold (cross-asset flow),
           rate change sensitivity
    """
    macro = apply_lag_to_macro_derived(macro)
    labeled = apply_triple_barrier_caller(price, pt_sl=[2, 2], vertical_barrier=20)
    pi = (
        labeled.index.tz_localize(None)
        if hasattr(labeled.index, "tz") and labeled.index.tz is not None
        else labeled.index
    )
    a = macro.reindex(pi, method="ffill")
    a.index = labeled.index

    a["dxy_mom_21"] = a["dxy"].pct_change(21)
    a["rate_diff"] = a["fed_funds"] - a["ecb_rate"]
    a["rate_diff_delta_3m"] = a["rate_diff"].diff(90)
    a["eurusd_mom_63"] = price["close"].pct_change(63)

    # Cross-asset spillover (lagged)
    gc_price = yf_download_safe("GC=F")
    a["dxy_lag1"] = a["dxy"].pct_change(1).shift(1)
    if gc_price is not None:
        if hasattr(gc_price.index, "tz") and gc_price.index.tz is not None:
            gc_price.index = gc_price.index.tz_localize(None)
        gc_ret = gc_price["close"].pct_change()
        a_index_naive = a.index.tz_localize(None) if hasattr(a.index, "tz") and a.index.tz is not None else a.index
        a["gc_lag1"] = gc_ret.shift(1).reindex(a_index_naive, method="ffill").values
    else:
        a["gc_lag1"] = 0.0

    a["us_2y_delta_5_lag1"] = a["us_2y"].diff(5).shift(1)

    features = ["dxy_mom_21", "rate_diff", "dxy_lag1", "gc_lag1"]

    clean = a.dropna(subset=features)
    clean["label"] = (labeled.loc[clean.index, "label"] + 1).astype(int)
    return clean, features


def build_usdjpy_features(price, macro):
    """
    USDJPY: yield-driven carry pair
    Primary drivers: us_10y (stability=0.941), dxy_mom_21 (stability=1.00)
    Asymmetric: VIX asymmetry = 0.26 (risk-off JPY buying)
    """
    macro = apply_lag_to_macro_derived(macro)
    labeled = apply_triple_barrier_caller(price, pt_sl=[2, 2], vertical_barrier=20)
    pi = (
        labeled.index.tz_localize(None)
        if hasattr(labeled.index, "tz") and labeled.index.tz is not None
        else labeled.index
    )
    a = macro.reindex(pi, method="ffill")
    a.index = labeled.index

    a["dxy_mom_21"] = a["dxy"].pct_change(21)
    a["us_jp_10y_spread"] = a["us_10y"] - a["jp_10y"]
    a["real_yield_delta_63"] = a["real_yield_10y"].diff(63)
    a["usdjpy_mom_63"] = price["close"].pct_change(63)

    features = ["dxy_mom_21", "us_jp_10y_spread", "real_yield_delta_63", "usdjpy_mom_63"]
    clean = a.dropna(subset=features)
    clean["label"] = (labeled.loc[clean.index, "label"] + 1).astype(int)
    return clean, features


def build_gc_features(price, macro):
    """
    GC=F: gold futures
    Primary drivers: dxy_mom_21 (stability=1.083), us_2y (stability=0.839)
    Real yield + USD pressure
    """
    macro = apply_lag_to_macro_derived(macro)
    labeled = apply_triple_barrier_caller(price, pt_sl=[2, 2], vertical_barrier=20)
    pi = (
        labeled.index.tz_localize(None)
        if hasattr(labeled.index, "tz") and labeled.index.tz is not None
        else labeled.index
    )
    a = macro.reindex(pi, method="ffill")
    a.index = labeled.index

    a["dxy_mom_21"] = a["dxy"].pct_change(21)
    a["real_yield_delta_63"] = a["real_yield_10y"].diff(63)
    a["breakeven_delta_63"] = a["breakeven_10y"].diff(63)
    a["gc_mom_63"] = price["close"].pct_change(63)

    features = ["dxy_mom_21", "real_yield_10y", "real_yield_delta_63", "gc_mom_63"]
    clean = a.dropna(subset=features)
    clean["label"] = (labeled.loc[clean.index, "label"] + 1).astype(int)
    return clean, features


def apply_triple_barrier_caller(price, pt_sl, vertical_barrier):
    from labels.triple_barrier import apply_triple_barrier

    return apply_triple_barrier(price, pt_sl=pt_sl, vertical_barrier=vertical_barrier)
