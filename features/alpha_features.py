import logging

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger("eigencapital.alpha_features")


def vol_adjusted_carry(price: pd.Series, rate_diff: pd.Series, vol_window: int = 21) -> pd.Series:
    """
    Carry signal normalized by realized volatility.

    Theory: Interest rate differential adjusted for risk (realized vol).
    High carry relative to low vol => attractive long; negative carry with
    high vol => unattractive. Menkhoff et al. (2012) JFE.
    Expected decay: ~1-3 months.

    rate_diff: domestic minus foreign annualized rate in decimal (e.g. 0.05 = 5%)

    Clipping uses rolling-window quantiles (fixed lookback) so that the
    training and inference paths produce identical clipping thresholds
    regardless of data depth.  Fixed rolling = same sample size = same
    quantile estimate at the current observation.
    """
    log_returns = np.log(price / price.shift(1))
    realized_vol = log_returns.rolling(vol_window).std() * np.sqrt(252)
    carry_to_vol = rate_diff.reindex(price.index) / realized_vol.replace(0, np.nan)
    lo = carry_to_vol.rolling(window=252, min_periods=vol_window).quantile(0.05)
    hi = carry_to_vol.rolling(window=252, min_periods=vol_window).quantile(0.95)
    return carry_to_vol.clip(lo, hi)


def momentum_features(price: pd.Series, horizons: list = None) -> pd.DataFrame:
    """
    Multi-horizon momentum with skip-1-day to avoid bid-ask bounce.

    Returns both the raw momentum and direction-split components:
    - ``mom_{h}d``: raw momentum (signed, direction-agnostic)
    - ``mom_{h}d_up``: positive momentum only (0 when negative). Lets the
      model learn separate weight for up-momentum vs down-momentum.
    - ``mom_{h}d_dn``: absolute value of negative momentum (0 when positive).
      Together with ``_up`` this enables the model to learn asymmetric
      trend-following: both sides are positive features with opposite
      implications that the model can weight independently.

    Theory: Cross-sectional and time-series momentum documented across
    asset classes. Menkhoff et al. (2012) JFE; Jegadeesh & Titman (1993).
    The directional split addresses the BUY/SELL information asymmetry:
    the original single-coefficient per horizon forces the model to use
    the same weight for up-trends and down-trends, but SELL signal is
    stronger than BUY signal in the current feature space. Splitting lets
    the model learn different weights per direction.

    Expected decay: 1m momentum ~weeks; 12m momentum ~months.
    """
    if horizons is None:
        horizons = [21, 63, 126, 252]
    mom = pd.DataFrame(index=price.index)
    for h in horizons:
        ret = np.log(price / price.shift(h))
        raw = ret.clip(-0.20, 0.20)
        mom[f"mom_{h}d"] = raw
        mom[f"mom_{h}d_up"] = raw.clip(lower=0.0)  # positive momentum (0 when negative)
        mom[f"mom_{h}d_dn"] = (-raw).clip(lower=0.0)  # |negative momentum| (0 when positive)
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


def vol_regime_ratio(price: pd.Series, short_window: int = 5, long_window: int = 63) -> pd.Series:
    """
    Ratio of short-term to long-term realized volatility.

    Theory: When short-term vol exceeds long-term vol, market regime
    is shifting. Predicts momentum crashes and carry unwinding.
    Brunnermeier, Nagel & Pedersen (2008) JFE.
    Expected decay: 5-10 days.
    """
    log_returns = np.log(price / price.shift(1))
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
    ret = np.log(dxy_price / dxy_price.shift(horizon + 1))
    return ret.clip(-0.05, 0.05)


def commodity_momentum(commodity_price: pd.Series, horizon: int = 21) -> pd.Series:
    """
    Commodity price momentum for commodity-linked currencies.

    Theory: Australia (iron ore), Canada (oil), gold (XAU) are
    commodity-linked. Commodity price moves predict FX with 1-5 day lag.
    Chen & Rogoff (2003) JIE.
    Expected decay: 5-15 days.
    """
    ret = np.log(commodity_price / commodity_price.shift(horizon + 1))
    return ret.clip(-0.10, 0.10)


def vix_momentum(vix_price: pd.Series, horizon: int = 5) -> pd.Series:
    """
    VIX momentum — risk sentiment indicator.

    Theory: VIX spikes correlate with FX vol expansion and carry trade
    unwinding (JPY strengthens during risk-off).
    Brunnermeier, Nagel & Pedersen (2008).
    Expected decay: 2-10 days.
    """
    return vix_price.pct_change(horizon)


def spx_momentum(spx_price: pd.Series, horizon: int = 5) -> pd.Series:
    """
    S&P 500 momentum — equity risk appetite for FX.

    Theory: Risk-on = buy high-yield (AUD, NZD), sell low-yield (JPY, CHF).
    SPX returns lead FX risk appetite with ~1 day lag.
    Expected decay: 1-5 days.
    """
    ret = spx_price.pct_change(horizon)
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
    normalized = net_spec_long / open_interest.replace(0, np.nan)
    roll_mean = normalized.rolling(lookback, min_periods=26).mean()
    roll_std = normalized.rolling(lookback, min_periods=26).std()
    z = (normalized - roll_mean) / roll_std.replace(0, np.nan)
    return z.clip(-3, 3)


def macd_histogram(close: pd.Series) -> pd.Series:
    """
    MACD histogram — difference between MACD line and signal line,
    normalized by close price to produce a percentage-like measure.

    Positive = bullish momentum, negative = bearish momentum.
    Histogram expanding = momentum accelerating.
    Histogram contracting after extreme values = momentum exhausting.

    Normalization: ``(macd - signal) / close`` gives a %-of-price measure
    that is comparable across assets regardless of price level
    (CADCHF at 0.68 vs NQ at 18,000).

    Returns a Series with the same index as *close*, clipped to [-0.05, 0.05]
    (i.e. ±5% of price).
    """
    macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    hist = (macd.macd() - macd.macd_signal()) / close.replace(0, pd.NA)
    return hist.clip(-0.05, 0.05)


def stochastic_oscillator(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator %K and %D lines.

    %K > 80 = overbought (SELL opportunity in uptrend).
    %K < 20 = oversold (BUY opportunity in downtrend).
    %K flat at extreme = exhaustion signal.
    %K/%D crossover in extreme zones = reversal confirmation.

    Returns (%K, %D) tuple with same index as *close*.
    """
    stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
    pct_k = stoch.stoch()
    pct_d = stoch.stoch_signal()
    return pct_k / 100.0, pct_d / 100.0  # Normalize to [0, 1]


def bb_pct_b(close: pd.Series, window: int = 20, std_dev: int = 2) -> pd.Series:
    """
    Bollinger Band %B — normalized position within the bands.

    %B = (close - lower) / (upper - lower).
    0 = at lower band, 1 = at upper band, >1 = above upper, <0 = below lower.
    Prolonged stay above 1 (strong trend) or below 0 (strong downtrend)
    followed by re-entry suggests trend exhaustion.

    Returns a Series with the same index as *close*.
    """
    bb = ta.volatility.BollingerBands(close, window=window, window_dev=std_dev)
    upper = bb.bollinger_hband()
    lower = bb.bollinger_lband()
    pct_b = (close - lower) / (upper - lower).replace(0, pd.NA)
    return pct_b.clip(-2, 3)


def adx_slope(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """
    ADX slope — rate of change of ADX over 5 days.

    ADX > 25 = trending market.
    ADX > 25 with negative slope = trend losing momentum (exhaustion).
    ADX < 20 with rising slope = trend about to start.

    Returns a Series with the same index as *close*.
    """
    adx_indicator = ta.trend.ADXIndicator(high, low, close, window=window)
    adx = adx_indicator.adx()
    slope = adx.diff(5)
    return slope.clip(-10, 10)


def day_of_week_signal(price: pd.Series) -> pd.Series:
    """
    Rolling day-of-week effect — mean forward return by weekday.

    Theory: Monday/Friday effects exist in FX due to weekend
    positioning and month-end rebalancing.
    Cornett, Schwarz & Szakmary (1995).
    Expected decay: 1 day (resets each week).

    Uses rolling(window=252, min_periods=63) to avoid look-ahead bias.
    """
    dt_index = pd.DatetimeIndex(price.index)
    forward_1d = price.pct_change(1, fill_method=None)
    result = pd.Series(0.0, index=price.index)
    if dt_index.dtype != "object":
        for d in range(5):
            mask = dt_index.dayofweek == d
            idx = price.index[mask]
            series = forward_1d.reindex(idx)
            rolling_mean = series.rolling(window=252, min_periods=63).mean()
            result.loc[idx] = rolling_mean.shift(1).fillna(0.0)
    return result


def _compute_trend_exhaustion_features(
    ohlcv: pd.DataFrame,
    price_index: pd.Index,
) -> dict[str, pd.Series]:
    """Compute trend-exhaustion indicators from OHLCV data once.

    These features are the same for all assets sharing the same OHLCV data.
    Computing them once and broadcasting via ``reindex`` avoids N redundant
    sequence-level computations (MACD, Stoch, BB, ADX, RSI all involve
    rolling-window operations over the full series).

    Returns a dict of ``{feature_name: pd.Series}`` where each Series is
    indexed by *price_index* (the aligned feature DataFrame index).  Returns
    an empty dict if *ohlcv* is None or empty.
    """
    if ohlcv is None or ohlcv.empty:
        return {}

    _h = ohlcv["high"].reindex(price_index).ffill()
    _l = ohlcv["low"].reindex(price_index).ffill()
    _c = ohlcv["close"].reindex(price_index).ffill()

    cache: dict[str, pd.Series] = {}
    cache["macd_hist"] = macd_histogram(_c)

    _k, _d = stochastic_oscillator(_h, _l, _c)
    cache["stoch_k"] = _k
    cache["stoch_d"] = _d

    cache["bb_pct_b"] = bb_pct_b(_c)
    cache["adx_slope"] = adx_slope(_h, _l, _c)

    try:
        from features.divergence import rsi_divergence

        cache["rsi_divergence"] = rsi_divergence(_h, _l, _c)
    except (ImportError, ValueError, TypeError):
        logger.debug("RSI divergence unavailable — defaulting to 0")
        cache["rsi_divergence"] = pd.Series(0.0, index=price_index)

    return cache


def _compute_narrative_features() -> dict[str, float]:
    """Load active FXStreet narrative and return numeric feature dict.

    Reads from ``narrative_active.json`` (written by the weekly FXStreet
    pipeline). Returns neutral defaults when no narrative is available
    (e.g. before the first weekly fetch, or after a fetch failure).

    The narrative is a weekly-frequency macro overlay that captures
    central bank hawkishness, currency biases, geopolitical risk, and
    the overall risk regime.  Adding these as cross-asset features lets
    the model learn the relationship between the macro narrative and
    forward returns for each direction.

    Returns 16 numeric features:
    - ``usd_strength_narr``, ``geopol_risk``, ``fed_hawk``,
      ``rbnz_hawk``, ``rba_hawk``, ``boj_intervene_risk``,
      ``energy_pressure``: floats in [0, 1]
    - ``usd_bias_num``, ``nzd_bias_num``, ``aud_bias_num``,
      ``jpy_bias_num``, ``cad_bias_num``, ``eur_bias_num``:
      {-1 = bearish, 0 = neutral, 1 = bullish}
    - ``regime_risk_on``, ``regime_geopol``: {0, 1} one-hot of
      overall_regime
    """
    try:
        from features.fxstreet_fetcher import NARRATIVE_DIR
        from pathlib import Path

        active_path = Path(NARRATIVE_DIR) / "narrative_active.json"
        if active_path.exists():
            from features.macro_narrative import load_narrative_json
            narr = load_narrative_json(str(active_path))
            return narr.to_feature_vector()
    except (ImportError, OSError, ValueError, TypeError):
        logger.debug("Narrative features unavailable — using neutral defaults")

    # Neutral fallback — all narratives neutral
    from features.macro_narrative import neutral_narrative
    return neutral_narrative().to_feature_vector()


def _compute_shared_features(
    dxy: pd.Series | None = None,
    vix: pd.Series | None = None,
    spx: pd.Series | None = None,
    commodities: pd.DataFrame | None = None,
    index: pd.Index | None = None,
) -> dict[str, pd.Series]:
    """Compute cross-asset features shared across all portfolio assets."""
    features: dict[str, pd.Series] = {}
    if dxy is not None:
        v = dxy_momentum(dxy)
        if index is not None:
            v = v.reindex(index)
        features["dxy_mom_21d"] = v
    if vix is not None:
        v = vix_momentum(vix)
        if index is not None:
            v = v.reindex(index)
        features["vix_mom_5d"] = v
    if spx is not None:
        v = spx_momentum(spx)
        if index is not None:
            v = v.reindex(index)
        features["spx_mom_5d"] = v
    if commodities is not None:
        for comm in commodities.columns:
            v = commodity_momentum(commodities[comm])
            if index is not None:
                v = v.reindex(index)
            features[f"{comm.upper()}_mom_21d"] = v
    return features


def build_alpha_features(
    prices: pd.DataFrame,
    rate_diffs: pd.DataFrame,
    dxy: pd.Series | None = None,
    vix: pd.Series | None = None,
    spx: pd.Series | None = None,
    commodities: pd.DataFrame | None = None,
    shared_features: dict[str, pd.Series] | None = None,
    ohlcv: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Assembles alpha features for all assets into a single DataFrame.

    Per-asset columns prefixed with {ASSET}_ (uppercase asset name).
    Cross-asset columns shared across all rows.

    Pass pre-computed *shared_features* (from _compute_shared_features)
    to avoid recomputing cross-asset features for every asset in the
    same inference cycle.

    When *ohlcv* is provided (DataFrame with 'open', 'high', 'low',
    'close', 'volume' columns), additional trend-exhaustion features
    are computed: MACD histogram, Stochastic %K/%D, BB %B, ADX slope,
    and RSI divergence.

    Returns a DataFrame with no NaN rows (ffill then dropna at end).
    """
    features = pd.DataFrame(index=prices.index)

    # Pre-compute trend-exhaustion indicators from shared OHLCV once.
    # These rolling-window computations (MACD, Stoch, BB, ADX, RSI) are
    # identical for all assets using the same OHLCV. Computing once and
    # broadcasting via reindex saves N× overhead for an N-asset portfolio.
    _trend_cache = _compute_trend_exhaustion_features(ohlcv, prices.index)

    for pair in prices.columns:
        asset_upper = pair.upper()
        close = prices[pair]

        # Align rate_diff to this asset's price index
        rd = (
            rate_diffs[pair].reindex(prices.index, method="ffill")
            if pair in rate_diffs.columns
            else pd.Series(0.0, index=prices.index)
        )

        carry_raw = vol_adjusted_carry(close, rd)
        features[f"{asset_upper}_carry_vol_adj"] = carry_raw
        # ── Asymmetric carry split (D-02 fix) ────────────────────────────
        # Split carry into positive and negative components. Carry trade
        # unwind is asymmetric: sharp during risk-off (positive carry ->
        # sharp reversal) vs gradual during risk-on. The original single
        # carry column forces the model to learn one coefficient that must
        # work for both regimes. Splitting lets it learn separate weights.
        features[f"{asset_upper}_carry_up"] = carry_raw.clip(lower=0.0)  # positive carry only
        features[f"{asset_upper}_carry_dn"] = (-carry_raw).clip(lower=0.0)  # |negative carry|

        mom = momentum_features(close)
        for col in mom.columns:
            features[f"{asset_upper}_{col}"] = mom[col]

        features[f"{asset_upper}_zscore_20"] = zscore_reversion(close)
        features[f"{asset_upper}_vol_ratio"] = vol_regime_ratio(close)
        features[f"{asset_upper}_dow_signal"] = day_of_week_signal(close)

        # ── Trend-exhaustion indicators (Tier 1) ─────────────────────
        # Pre-computed from shared OHLCV — broadcast to each asset via
        # reindex, which is a fast column-level operation rather than a
        # full sequence computation (MACD, Stoch, BB, ADX all involve
        # rolling-window operations over the full OHLCV series).
        for feat_name, feat_series in _trend_cache.items():
            features[f"{asset_upper}_{feat_name}"] = feat_series.reindex(close.index)

    # Cross-asset features (reuse pre-computed if provided)
    if shared_features is not None:
        for name, series in shared_features.items():
            features[name] = series.reindex(features.index)
    else:
        if dxy is not None:
            features["dxy_mom_21d"] = dxy_momentum(dxy).reindex(features.index)
        if vix is not None:
            features["vix_mom_5d"] = vix_momentum(vix).reindex(features.index)
        if spx is not None:
            features["spx_mom_5d"] = spx_momentum(spx).reindex(features.index)
        if commodities is not None:
            for comm in commodities.columns:
                features[f"{comm.upper()}_mom_21d"] = commodity_momentum(commodities[comm]).reindex(features.index)

    # ── FXStreet narrative features (weekly macro overlay) ────────────
    # These are constant across all rows in the same weekly window.
    # When no narrative is available (pre-first-fetch), neutral defaults
    # are used: all currency biases = 0 (neutral), risk regime = 0, etc.
    narr_vars = _compute_narrative_features()
    for name, value in narr_vars.items():
        features[name] = value

    # Final forward-fill and dropna to handle indicator warmup.
    # We also fill any remaining NaNs in cross-asset features with 0.0
    # to prevent an entirely NaN column from discarding all rows.
    features = features.ffill()
    for col in features.columns:
        if col in ["dxy_mom_21d", "vix_mom_5d", "spx_mom_5d"] or "WTI_mom" in col:
            features[col] = features[col].fillna(0.0)

    return features.dropna()
