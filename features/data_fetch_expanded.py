"""Expanded data fetching — uses cached 10+ year data from data/yfinance_10yr/."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("data_fetch_expanded")

DATA_DIR = Path("data/yfinance_10yr")


def fetch_expanded_data(asset_name: str, ticker: str):
    """Fetch 10+ year data from local cache, aligned with macro."""
    from features.data_fetch import _MIN_HISTORY_ROWS, _fetch_macro_batch, _normalize_index

    ohlcv_path = DATA_DIR / f"{asset_name}_ohlcv.parquet"
    if not ohlcv_path.exists():
        raise FileNotFoundError(f"No cached data for {asset_name} at {ohlcv_path}")

    ohlcv = pd.read_parquet(ohlcv_path)
    ohlcv.index = _normalize_index(ohlcv.index)
    close = ohlcv["close"].copy()
    close.name = asset_name

    if len(close) < _MIN_HISTORY_ROWS:
        raise ValueError(f"{asset_name}: insufficient history ({len(close)} rows)")

    prices = close.to_frame(asset_name)

    macro = _fetch_macro_batch()
    dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
    vix = macro.get("^VIX", pd.Series(dtype=float))
    spx = macro.get("^GSPC", pd.Series(dtype=float))
    wti = macro.get("CL=F", pd.Series(dtype=float))
    tnx = macro.get("^TNX", pd.Series(dtype=float))

    for s in [dxy, vix, spx, wti, tnx]:
        if not s.empty and s.index.duplicated().any():
            s = s[~s.index.duplicated(keep="last")]

    # Build common index
    common = close.index
    if common.duplicated().any():
        common = common[~common.duplicated(keep="last")]
    for s, dropna in [(dxy, False), (vix, False), (spx, False), (wti, False), (tnx, True)]:
        if not s.empty:
            idx = s.dropna().index if dropna else s.index
            if idx.duplicated().any():
                idx = idx[~idx.duplicated(keep="last")]
            common = common.intersection(idx)

    if common.empty:
        raise ValueError(f"{asset_name}: no overlapping dates with macro")

    prices = prices.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)
    tnx = tnx.reindex(common).ffill().fillna(0.0)
    ohlcv = ohlcv.loc[common]

    # Rate differentials
    from features.data_fetch import _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS, CURRENCY_YIELD_TICKERS

    asset_upper = asset_name.upper()
    base_ccy = quote_ccy = None
    if (
        asset_upper not in _ZERO_RATE_ASSETS
        and len(asset_upper) == 6
        and asset_upper[:3] in _KNOWN_CURRENCIES
        and asset_upper[3:] in _KNOWN_CURRENCIES
    ):
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]

    if base_ccy and quote_ccy:
        base_ticker = CURRENCY_YIELD_TICKERS[base_ccy]
        quote_ticker = CURRENCY_YIELD_TICKERS[quote_ccy]
        base_y = macro.get(base_ticker, tnx)
        if not base_y.empty:
            base_y = base_y[~base_y.index.duplicated(keep="last")]
        base_y = base_y.reindex(common).ffill()
        quote_y = macro.get(quote_ticker, tnx)
        if not quote_y.empty:
            quote_y = quote_y[~quote_y.index.duplicated(keep="last")]
        quote_y = quote_y.reindex(common).ffill()
        rate_diff = base_y - quote_y
    else:
        rate_diff = pd.Series(0.0, index=common)

    rate_diffs = pd.DataFrame({asset_name: rate_diff}, index=common)
    commodities = wti.to_frame("WTI")

    logger.info(
        f"{asset_name}: expanded fetch — {len(prices)} rows ({prices.index[0].date()}..{prices.index[-1].date()})"
    )
    return prices, rate_diffs, dxy, vix, spx, commodities, ohlcv
