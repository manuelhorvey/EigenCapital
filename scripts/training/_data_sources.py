"""Shared data-source helpers for retrain + walk-forward scripts.

Provides ``load_expanded_prices(asset_name, expanded_dir)`` which resolves
(same priority order on every consumer):

    1.  ``EIGENCAPITAL_EXPANDED_DATA_DIR`` env var. When set, the helper
        reads ``{env_var}/{asset_name}_ohlcv.parquet`` (cached full-history
        coverage from ``download_expanded_data.py``).
    2.  ``data/yfinance_10yr/{asset_name}_ohlcv.parquet`` under the project
        root — fall-through default if the env var is unset.
    3.  None — caller falls back to live ``fetch_asset_data()``.

A single helper means both retrain and walk-forward pivot on the same
env var without duplicating the path-resolution logic. To force the live
fetch path, explicitly pass ``expanded_dir=None`` and check the return.

NOTE ON DATA WINDOW: the cached parquet contains 10-20y of OHLCV per asset
(verified 2006-2026 for AUDUSD), but live macro series (DXY/VIX/SPX/^TNX/
^TIPS10Y/^BREKEVEN10Y/etc.) only go back ~6y via yfinance/FRED. Both retrain
and walk-forward forward-fill macro to the OHLCV range, then intersect at
the walk-forward's source data length — typically 5-6y of "fully populated"
features. The training corpus can extend further back with macro
forward-filled to 0/NA, but features derived from rolling macros
(yield_slope, breakeven_21d_chg, etc.) need warmup rows so the first ~6y
of signals are zero/near-zero. Model robustness is unaffected because
walk-forward splits only use windows after the macro warmup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from paper_trading.ops.data_fetcher import _set_store

logger = logging.getLogger("eigencapital.data_sources")

# Null store so yfinance live fetch works during offline training runs
# (mirrors what retrain_all_fixed.py / train_canary.py do at startup).
class _NullStore:
    def save_cache(self, *a, **k): return None
    def load_cache(self, *a, **k): return None
    def cache_path(self, *a, **k): return "/dev/null"


_set_store(_NullStore())


DEFAULT_EXPANDED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "yfinance_10yr"


def resolve_expanded_dir() -> Path | None:
    """Return the 10-year cache directory if one is available.

    Order:
        1. ``EIGENCAPITAL_EXPANDED_DATA_DIR`` env var (overrides everything)
        2. ``data/yfinance_10yr/`` under the project root
    Returns None if neither resolves to an existing directory.
    """
    env_dir = os.environ.get("EIGENCAPITAL_EXPANDED_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
    if DEFAULT_EXPANDED_DIR.is_dir():
        return DEFAULT_EXPANDED_DIR
    return None


def load_expanded_prices(
    asset_name: str,
    expanded_dir: Path | None = None,
) -> pd.Series | None:
    """Read the cached ``close`` series for ``asset_name`` from the
    10-year parquet cache.

    ``expanded_dir`` defaults to ``resolve_expanded_dir()``. Pass
    ``expanded_dir=None`` explicitly to return None unconditionally.
    """
    if expanded_dir is None and (expanded_dir := resolve_expanded_dir()) is None:
        return None
    pq = Path(expanded_dir) / f"{asset_name}_ohlcv.parquet"
    if not pq.exists():
        return None
    try:
        df = pd.read_parquet(pq)
    except (OSError, ValueError, RuntimeError):
        return None
    if df.empty or "close" not in df.columns:
        return None
    return df["close"]


def fetch_from_expanded_or_live(
    asset_name: str,
    ticker: str,
    expanded_dir: Path | None = None,
):
    """Fetch asset data, preferring the 10-year cached parquet over live
    yfinance. Returns the same 6-tuple as
    ``features.data_fetch.fetch_asset_data``:

        (prices, rate_diffs, dxy, vix, spx, commodities)

    When ``expanded_dir`` resolves to an existing directory AND
    ``{asset}_ohlcv.parquet`` exists there, we:

        1. Read the OHLCV parquet, normalise the index.
        2. Pull macro/vix/spx/dxy/wti/tnx via the live batch fetcher
           (small payload, not cached — varies by current month).
        3. Build rate_diffs the same way the training pipeline does
           (cross-currency yield differential from CURRENCY_YIELD_TICKERS).

    Otherwise we fall through to ``fetch_asset_data`` unchanged, so callers
    behave identically when no cache is configured.

    ``return_ohlcv=True`` returns an extra (prices, rate_diffs, dxy, vix,
    spx, commodities, ohlcv) 7-tuple — needed by callers that want the
    bar-level data for label generation, regime features, etc.
    """
    if expanded_dir is None:
        expanded_dir = resolve_expanded_dir()

    pq = Path(expanded_dir) / f"{asset_name}_ohlcv.parquet" if expanded_dir else None
    if not (pq is not None and pq.exists()):
        from features.data_fetch import fetch_asset_data
        return fetch_asset_data(asset_name, ticker)

    from features.data_fetch import (
        _normalize_index,
        _fetch_macro_batch,
        CURRENCY_YIELD_TICKERS,
        _KNOWN_CURRENCIES,
        _ZERO_RATE_ASSETS,
    )

    ohlcv = pd.read_parquet(pq)
    ohlcv.index = _normalize_index(ohlcv.index)

    macro = _fetch_macro_batch()
    dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
    vix = macro.get("^VIX", pd.Series(dtype=float))
    spx = macro.get("^GSPC", pd.Series(dtype=float))
    wti = macro.get("CL=F", pd.Series(dtype=float))
    tnx = macro.get("^TNX", pd.Series(dtype=float))

    # Use the cached OHLCV as the canonical date range. Macro series
    # (dxy/vix/spx/wti/tnx) only cover the most recent ~5y via yfinance,
    # so we forward-fill them to the full OHLCV range. Without this
    # intersection, the walk-forward would silently truncate to macro's
    # 5y span even though OHLCV is 10y+ and we'd be paying the data
    # cost without the duration benefit.
    common = ohlcv.index
    aligned_dxy = dxy.reindex(common).ffill() if not dxy.empty else pd.Series(0.0, index=common)
    aligned_vix = vix.reindex(common).ffill() if not vix.empty else pd.Series(0.0, index=common)
    aligned_spx = spx.reindex(common).ffill() if not spx.empty else pd.Series(0.0, index=common)
    aligned_wti = wti.reindex(common).ffill() if not wti.empty else pd.Series(0.0, index=common)
    aligned_tnx = tnx.reindex(common).ffill() if not tnx.empty else pd.Series(0.0, index=common)

    prices = ohlcv["close"].to_frame(asset_name)
    rate_diffs = pd.DataFrame(index=common)
    commodities = pd.DataFrame(index=common)
    commodities["WTI"] = aligned_wti

    asset_upper = asset_name.upper()
    base_ccy = asset_upper[:3]
    quote_ccy = asset_upper[3:]
    if (
        base_ccy in _KNOWN_CURRENCIES
        and quote_ccy in _KNOWN_CURRENCIES
        and asset_upper not in _ZERO_RATE_ASSETS
    ):
        base_series = pd.Series(0.0, index=common)
        quote_series = pd.Series(0.0, index=common)
        base_yc_key = CURRENCY_YIELD_TICKERS.get(base_ccy)
        if base_yc_key and base_yc_key in macro:
            base_series = macro[base_yc_key].reindex(common).ffill().fillna(0.0)
        quote_yc_key = CURRENCY_YIELD_TICKERS.get(quote_ccy)
        if quote_yc_key and quote_yc_key in macro:
            quote_series = macro[quote_yc_key].reindex(common).ffill().fillna(0.0)
        rate_diffs[asset_name] = base_series - quote_series
    else:
        rate_diffs[asset_name] = pd.Series(0.0, index=common)

    return prices, rate_diffs, aligned_dxy, aligned_vix, aligned_spx, commodities


def fetch_ohlcv_from_expanded_or_live(
    asset_name: str,
    ticker: str,
    expanded_dir: Path | None = None,
):
    """Return the OHLCV DataFrame for ``asset_name``.

    Uses the cached 10y parquet when available, otherwise falls through
    to ``fetch_asset_ohlcv`` (live 5y yfinance fetch).
    """
    if expanded_dir is None:
        expanded_dir = resolve_expanded_dir()
    pq = Path(expanded_dir) / f"{asset_name}_ohlcv.parquet" if expanded_dir else None
    if pq is not None and pq.exists():
        from features.data_fetch import _normalize_index
        ohlcv = pd.read_parquet(pq)
        ohlcv.index = _normalize_index(ohlcv.index)
        return ohlcv
    from features.data_fetch import fetch_asset_ohlcv
    return fetch_asset_ohlcv(ticker)



def build_expanded_full_panel(
    portfolio: dict,
    expanded_dir: Path | None = None,
) -> pd.DataFrame:
    """Pre-fetch the full panel for cross-sectional (Group 1) features
    from cached parquets. Drops assets whose cache is missing or unreadable.

    Mirrors the live ``fetch_asset_data`` panel-construction in
    ``retrain_all_fixed.py`` and ``run_expanded_walkforward_v2.py`` but
    reads from local parquets first, then live (yfinance) only as fallback.
    """
    if expanded_dir is None:
        expanded_dir = resolve_expanded_dir()

    panel_dict: dict[str, pd.Series] = {}
    if expanded_dir is not None:
        for aname in portfolio.keys():
            series = load_expanded_prices(aname, expanded_dir=expanded_dir)
            if series is not None:
                panel_dict[aname] = series

    if not panel_dict:
        from features.data_fetch import fetch_asset_data
        for aname, aspec in portfolio.items():
            try:
                aprices, _, _, _, _, _ = fetch_asset_data(aname, aspec["ticker"])
                if aprices is not None and not aprices.empty:
                    panel_dict[aname] = aprices.iloc[:, 0]
            except (OSError, ValueError, KeyError, RuntimeError):
                continue

    return pd.DataFrame(panel_dict).ffill().dropna(how="all")
