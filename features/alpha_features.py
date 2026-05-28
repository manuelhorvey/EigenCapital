import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("quantforge.alpha_features")


def vol_adjusted_carry(
    price: pd.Series, rate_diff: pd.Series, vol_window: int = 21
) -> pd.Series:
    """
    Carry signal normalized by realized volatility.

    Theory: Interest rate differential adjusted for risk (realized vol).
    High carry relative to low vol => attractive long; negative carry with
    high vol => unattractive. Menkhoff et al. (2012) JFE.
    Expected decay: ~1-3 months.

    rate_diff: domestic minus foreign annualized rate in decimal (e.g. 0.05 = 5%)
    """
    log_returns = np.log(price.astype(float) / price.astype(float).shift(1))
    realized_vol = log_returns.rolling(vol_window).std() * np.sqrt(252)
    carry_to_vol = rate_diff.reindex(price.index) / realized_vol.replace(0, np.nan)
    lo, hi = carry_to_vol.quantile([0.05, 0.95])
    return carry_to_vol.clip(lo, hi)


def momentum_features(
    price: pd.Series, horizons: list = None
) -> pd.DataFrame:
    """
    Multi-horizon momentum with skip-1-day to avoid bid-ask bounce.

    Theory: Cross-sectional and time-series momentum documented across
    asset classes. Menkhoff et al. (2012) JFE; Jegadeesh & Titman (1993).
    Expected decay: 1m momentum ~weeks; 12m momentum ~months.
    """
    if horizons is None:
        horizons = [21, 63, 126, 252]
    mom = pd.DataFrame(index=price.index)
    for h in horizons:
        ret = np.log(price.astype(float) / price.astype(float).shift(h + 1))
        mom[f"mom_{h}d"] = ret.clip(-0.20, 0.20)
    return mom


def zscore_reversion(price: pd.Series, window: int = 20) -> pd.Series:
    """
    Z-score of price relative to rolling mean.

    Theory: Deviations from rolling mean signal overbought/oversold.
    Balvers, Wu & Gilliland (2000) — mean reversion in currency pairs.
    Expected decay: 10-30 days.
    """
    ma = price.rolling(window).mean()
    std = price.rolling(window).std()
    z = (price - ma) / std.replace(0, np.nan)
    return z.clip(-3, 3)


def vol_regime_ratio(
    price: pd.Series, short_window: int = 5, long_window: int = 63
) -> pd.Series:
    """
    Ratio of short-term to long-term realized volatility.

    Theory: When short-term vol exceeds long-term vol, market regime
    is shifting. Predicts momentum crashes and carry unwinding.
    Brunnermeier, Nagel & Pedersen (2008) JFE.
    Expected decay: 5-10 days.
    """
    log_returns = np.log(price.astype(float) / price.astype(float).shift(1))
    short_vol = log_returns.rolling(short_window).std()
    long_vol = log_returns.rolling(long_window).std()
    ratio = short_vol / long_vol.replace(0, np.nan)
    return ratio.clip(0.1, 5.0)


def dxy_momentum(dxy_price: pd.Series, horizon: int = 21) -> pd.Series:
    """
    USD index momentum — dominant FX factor.

    Theory: USD strength/weakness is the primary driver of FX moves.
    USD-short pairs (EUR, AUD, GBP) weaken when USD strengthens.
    Expected decay: 5-20 days.
    """
    ret = np.log(dxy_price.astype(float) / dxy_price.astype(float).shift(horizon + 1))
    return ret.clip(-0.05, 0.05)


def commodity_momentum(commodity_price: pd.Series, horizon: int = 21) -> pd.Series:
    """
    Commodity price momentum for commodity-linked currencies.

    Theory: Australia (iron ore), Canada (oil), gold (XAU) are
    commodity-linked. Commodity price moves predict FX with 1-5 day lag.
    Chen & Rogoff (2003) JIE.
    Expected decay: 5-15 days.
    """
    ret = np.log(
        commodity_price.astype(float)
        / commodity_price.astype(float).shift(horizon + 1)
    )
    return ret.clip(-0.10, 0.10)


def vix_momentum(vix_price: pd.Series, horizon: int = 5) -> pd.Series:
    """
    VIX momentum — risk sentiment indicator.

    Theory: VIX spikes correlate with FX vol expansion and carry trade
    unwinding (JPY strengthens during risk-off).
    Brunnermeier, Nagel & Pedersen (2008).
    Expected decay: 2-10 days.
    """
    return vix_price.astype(float).pct_change(horizon)


def spx_momentum(spx_price: pd.Series, horizon: int = 5) -> pd.Series:
    """
    S&P 500 momentum — equity risk appetite for FX.

    Theory: Risk-on = buy high-yield (AUD, NZD), sell low-yield (JPY, CHF).
    SPX returns lead FX risk appetite with ~1 day lag.
    Expected decay: 1-5 days.
    """
    ret = spx_price.astype(float).pct_change(horizon)
    return ret.clip(-0.05, 0.05)


def cot_net_positioning(
    net_spec_long: pd.Series,
    open_interest: pd.Series,
    lookback: int = 52,
) -> pd.Series:
    """
    COT speculative positioning normalized by open interest, z-scored.

    Theory: Extreme spec long positions predict mean reversion.
    Klosse & Rzepkowski (2019) — weekly horizon predictive power.
    Limitation: released Friday for Tuesday data (3-day stale).
    Use as regime context, not entry signal.
    Expected decay: 1-4 weeks.
    """
    normalized = net_spec_long.astype(float) / open_interest.astype(float).replace(
        0, np.nan
    )
    roll_mean = normalized.rolling(lookback, min_periods=26).mean()
    roll_std = normalized.rolling(lookback, min_periods=26).std()
    z = (normalized - roll_mean) / roll_std.replace(0, np.nan)
    return z.clip(-3, 3)


def day_of_week_signal(price: pd.Series) -> pd.Series:
    """
    Rolling day-of-week effect — mean forward return by weekday.

    Theory: Monday/Friday effects exist in FX due to weekend
    positioning and month-end rebalancing.
    Cornett, Schwarz & Szakmary (1995).
    Expected decay: 1 day (resets each week).

    Uses rolling(window=252, min_periods=63) to avoid look-ahead bias.
    """
    forward_1d = price.pct_change(-1, fill_method=None)
    result = pd.Series(0.0, index=price.index)
    for d in range(5):
        mask = price.index.dayofweek == d
        idx = price.index[mask]
        series = forward_1d.reindex(idx)
        rolling_mean = series.rolling(window=252, min_periods=63).mean()
        result.loc[idx] = rolling_mean.shift(1).fillna(0.0)
    return result


def build_alpha_features(
    prices: pd.DataFrame,
    rate_diffs: pd.DataFrame,
    dxy: pd.Series | None = None,
    vix: pd.Series | None = None,
    spx: pd.Series | None = None,
    commodities: pd.DataFrame | None = None,
    cot_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Assembles alpha features for all assets into a single DataFrame.

    Per-asset columns prefixed with {ASSET}_ (uppercase asset name).
    Cross-asset columns shared across all rows.

    Returns a DataFrame with no NaN rows (ffill then dropna at end).
    """
    features = pd.DataFrame(index=prices.index)

    for pair in prices.columns:
        asset_upper = pair.upper()
        close = prices[pair].astype(float)

        # Align rate_diff to this asset's price index
        rd = (
            rate_diffs[pair].reindex(prices.index, method="ffill")
            if pair in rate_diffs.columns
            else pd.Series(0.0, index=prices.index)
        )

        features[f"{asset_upper}_carry_vol_adj"] = vol_adjusted_carry(close, rd)

        mom = momentum_features(close)
        for col in mom.columns:
            features[f"{asset_upper}_{col}"] = mom[col]

        features[f"{asset_upper}_zscore_20"] = zscore_reversion(close)
        features[f"{asset_upper}_vol_ratio"] = vol_regime_ratio(close)
        features[f"{asset_upper}_dow_signal"] = day_of_week_signal(close)

    # Cross-asset features
    if dxy is not None:
        features["dxy_mom_21d"] = dxy_momentum(dxy).reindex(features.index)
    else:
        logger.warning("dxy is None — skipping dxy_mom_21d feature")

    if vix is not None:
        features["vix_mom_5d"] = vix_momentum(vix).reindex(features.index)
    else:
        logger.warning("vix is None — skipping vix_mom_5d feature")

    if spx is not None:
        features["spx_mom_5d"] = spx_momentum(spx).reindex(features.index)
    else:
        logger.warning("spx is None — skipping spx_mom_5d feature")

    if commodities is not None:
        for comm in commodities.columns:
            features[f"{comm.upper()}_mom_21d"] = commodity_momentum(
                commodities[comm]
            ).reindex(features.index)
    else:
        logger.warning("commodities is None — skipping commodity features")

    if cot_data is not None:
        for pair in cot_data.columns:
            if pair in prices.columns:
                asset_upper = pair.upper()
                features[f"{asset_upper}_cot_z"] = cot_data[pair].reindex(
                    features.index
                )
    else:
        logger.info("cot_data is None — skipping COT features")

    return features.ffill().dropna()
