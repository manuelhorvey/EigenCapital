import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.cross_sectional")


def compute_momentum_ranks(
    prices: pd.DataFrame,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    """Multi-horizon momentum rank vs the cross-sectional panel.

    For each horizon, ranks each asset's log return against all other
    assets, producing a percentile [0, 1] where 1 = strongest momentum
    and 0 = weakest.  The rank normalises away asset-specific magnitude
    differences and isolates the *relative* strength signal orthogonal
    to asset-level vol.

    Parameters
    ----------
    prices : pd.DataFrame
        Full 22-asset price panel (N assets x T days), columns = asset names.
    horizons : list[int] | None
        Momentum lookback horizons.  Defaults to [21, 63, 126, 252] matching
        ``alpha_features.momentum_features``.

    Returns
    -------
    pd.DataFrame
        Columns ``{ASSET}_xs_mom_{h}d_rank`` indexed by the panel's date index.
        All values in [0, 1].

    Notes
    -----
    - Uses only ``close[t]`` and ``close[t-h]`` — no lookahead.
    - Will correlate with existing ``mom_{h}d`` columns by construction
      (Spearman ~0.85+).  This is intentional: the rank provides a
      scale-invariant view of the same signal.
    - Horizon `h` means ``h+1`` shift to match the skip-1-day convention
      in ``alpha_features`` (bid-ask bounce avoidance).
    """
    if horizons is None:
        horizons = [21, 63, 126, 252]

    parts: list[pd.DataFrame] = []

    for h in horizons:
        ret = np.log(prices / prices.shift(h + 1))
        ret = ret.clip(-0.20, 0.20)

        ranks = ret.rank(axis=1, pct=True)
        renamed = ranks.rename(columns=lambda c: f"{c.upper()}_xs_mom_{h}d_rank")
        parts.append(renamed)

    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=prices.index)


def compute_cross_sectional_zscore(
    prices: pd.DataFrame,
    horizon: int = 1,
) -> pd.DataFrame:
    """Same-day z-score of each asset's return vs the cross-sectional panel.

    At each date t, computes ``z = (r_i - μ) / σ`` where:
      - r_i = log return of asset i over *horizon* days
      - μ = mean return across all assets at that date
      - σ = std across all assets at that date

    A positive z-score means the asset outperformed the panel (risk-on
    relative strength); negative means it lagged.

    Parameters
    ----------
    prices : pd.DataFrame
        Full 22-asset price panel.
    horizon : int
        Return horizon in days. Default 1 (same-day return).

    Returns
    -------
    pd.DataFrame
        Columns ``{ASSET}_xs_return_z_{h}d``.

    Notes
    -----
    - No leakage: ``return[t] = log(close[t] / close[t-h])`` — uses only
      information available at bar close.
    - When σ=0 (all assets identical return, extremely rare), z-score is 0.
    """
    ret = np.log(prices / prices.shift(horizon))
    mu = ret.mean(axis=1)
    sigma = ret.std(axis=1, ddof=0).replace(0, np.nan)
    z = ret.subtract(mu, axis=0).div(sigma, axis=0).fillna(0.0)

    renamed = z.rename(columns=lambda c: f"{c.upper()}_xs_return_z_{horizon}d")
    return renamed


def compute_benchmark_correlations(
    prices: pd.DataFrame,
    dxy: pd.Series,
    spx: pd.Series,
    corr_window: int = 60,
    zscore_window: int = 252,
) -> pd.DataFrame:
    """Rolling correlation of each asset to DXY and SPX, plus regime-break flag.

    At each date t, computes ``Pearson(log_ret_asset, log_ret_benchmark)``
    over a rolling *corr_window*-day window.  A binary *correlation regime
    break* flag fires when the current correlation's z-score (vs its own
    *zscore_window*-day history) exceeds 2 — i.e. the correlation structure
    has shifted anomalously.

    Parameters
    ----------
    prices : pd.DataFrame
        Full 22-asset price panel.
    dxy : pd.Series
        DXY close price, same index as *prices*.
    spx : pd.Series
        SPX close price, same index as *prices*.
    corr_window : int
        Rolling window for Pearson correlation (default 60).
    zscore_window : int
        Rolling window for the correlation's own z-score (default 252).

    Returns
    -------
    pd.DataFrame
        Six columns per asset:
        ``{ASSET}_xs_dxy_corr_{window}d``
        ``{ASSET}_xs_spx_corr_{window}d``
        ``{ASSET}_xs_corr_break`` (binary: 1 when *either* DXY or SPX
        correlation z-score exceeds 2).

    Notes
    -----
    - Uses rolling ``.corr()`` on 1d log returns — standard pandas
      implementation that aligns on the common index.
    - The regime break z-score uses the correlation value itself (Fisher
      z-transformed to unbias the distribution) vs its own rolling mean/std.
    - Requires at least *corr_window* + *zscore_window* rows of history for
      the break flag to activate.  Before sufficient history, break = 0.
    """
    common = prices.index.intersection(dxy.dropna().index).intersection(spx.dropna().index)
    if common.empty:
        logger.warning("No overlapping dates between price panel and DXY/SPX — returning zeros")
        result = pd.DataFrame(index=prices.index)
        for asset in prices.columns:
            au = asset.upper()
            result[f"{au}_xs_dxy_corr_{corr_window}d"] = 0.0
            result[f"{au}_xs_spx_corr_{corr_window}d"] = 0.0
            result[f"{au}_xs_corr_break"] = 0
        return result

    prices_a = prices.loc[common]
    dxy_a = dxy.loc[common]
    spx_a = spx.loc[common]

    asset_rets = np.log(prices_a / prices_a.shift(1))
    dxy_rets = np.log(dxy_a / dxy_a.shift(1))
    spx_rets = np.log(spx_a / spx_a.shift(1))

    dxy_corr_s = pd.DataFrame(
        {c: asset_rets[c].rolling(corr_window, min_periods=corr_window).corr(dxy_rets) for c in prices_a.columns},
        index=prices_a.index,
    )
    dxy_corr_s.columns = [f"{c.upper()}_xs_dxy_corr_{corr_window}d" for c in dxy_corr_s.columns]

    spx_corr_s = pd.DataFrame(
        {c: asset_rets[c].rolling(corr_window, min_periods=corr_window).corr(spx_rets) for c in prices_a.columns},
        index=prices_a.index,
    )
    spx_corr_s.columns = [f"{c.upper()}_xs_spx_corr_{corr_window}d" for c in spx_corr_s.columns]

    fisher_dxy = np.arctanh(dxy_corr_s.clip(-0.9999, 0.9999))
    fisher_spx = np.arctanh(spx_corr_s.clip(-0.9999, 0.9999))

    mu_dxy = fisher_dxy.rolling(zscore_window, min_periods=corr_window + 20).mean()
    std_dxy = fisher_dxy.rolling(zscore_window, min_periods=corr_window + 20).std(ddof=0).replace(0, np.nan)
    z_dxy = ((fisher_dxy - mu_dxy) / std_dxy).abs()

    mu_spx = fisher_spx.rolling(zscore_window, min_periods=corr_window + 20).mean()
    std_spx = fisher_spx.rolling(zscore_window, min_periods=corr_window + 20).std(ddof=0).replace(0, np.nan)
    z_spx = ((fisher_spx - mu_spx) / std_spx).abs()

    break_s = ((z_dxy > 2.0) | (z_spx > 2.0)).astype(int)
    break_s.columns = [f"{c.upper()}_xs_corr_break" for c in break_s.columns]

    return pd.concat([dxy_corr_s, spx_corr_s, break_s], axis=1)


def compute_all(
    prices: pd.DataFrame,
    dxy: pd.Series,
    spx: pd.Series,
    momentum_horizons: list[int] | None = None,
    corr_window: int = 60,
    zscore_window: int = 252,
) -> pd.DataFrame:
    """Convenience wrapper — compute all Group 1 cross-sectional features.

    Parameters
    ----------
    prices : pd.DataFrame
        Full 22-asset price panel.
    dxy : pd.Series
        DXY close price.
    spx : pd.Series
        SPX close price.
    momentum_horizons : list[int] | None
        Momentum horizons for rank features.
    corr_window : int
        Rolling window for benchmark correlations.
    zscore_window : int
        Rolling window for correlation z-score regime break.

    Returns
    -------
    pd.DataFrame
        All cross-sectional features combined.
    """
    parts: list[pd.DataFrame] = []

    mom_ranks = compute_momentum_ranks(prices, momentum_horizons)
    if not mom_ranks.empty:
        parts.append(mom_ranks)

    zs = compute_cross_sectional_zscore(prices)
    if not zs.empty:
        parts.append(zs)

    corr = compute_benchmark_correlations(prices, dxy, spx, corr_window, zscore_window)
    if not corr.empty:
        parts.append(corr)

    if not parts:
        return pd.DataFrame(index=prices.index)

    combined = pd.concat(parts, axis=1)
    return combined
