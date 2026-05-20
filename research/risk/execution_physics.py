"""Market microstructure degradation models for survival simulation.

Models stress-dependent execution physics that dominate portfolio survival
during crises:
  - Spread expansion as a function of volatility
  - Stop-loss gap risk (nonlinear during stress)
  - Partial fills / execution truncation under liquidity stress
  - Portfolio-level deleveraging feedback (drawdown → exposure reduction)

Usage:
    config = ExecutionConfig()
    vol_zscore = compute_vol_zscore(returns_array)
    degraded = apply_execution_degradation(returns_array, vol_zscore, rng, config)
    equity = apply_deleveraging(equity_curve, dd_threshold=-0.10)
"""

import os
import json
import numpy as np
import pandas as pd
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional


class VolRegime(IntEnum):
    """Volatility regime classification."""
    CALM = 0
    ELEVATED = 1
    CRISIS = 2


@dataclass
class ExecutionConfig:
    """Configurable parameters for execution degradation models.

    Sensible defaults for FX-major systematic strategies.  Tune per-asset
    for crypto, commodities, or emerging-market FX.
    """

    # ── Spread expansion ──────────────────────────────────────────
    base_spread_bps: float = 0.5       # 0.5 bps for FX majors
    spread_vol_slope: float = 2.0      # multiple per vol z-score > 1
    spread_max_bps: float = 50.0       # cap at 50 bps in extreme stress

    # ── Stop-loss gap risk ────────────────────────────────────────
    base_gap_bps: float = 0.5          # base gap noise (0.5 bps)
    gap_vol_slope: float = 3.0         # gap grows nonlinearly with vol
    gap_max_bps: float = 300.0         # 3% max gap (flash crash scenario)

    # ── Partial fills / liquidity ─────────────────────────────────
    fill_vol_threshold: float = 2.0    # vol z-score above this reduces fill rate
    fill_prob_slope: float = -0.12     # fill prob drops 12pp per z-score > threshold
    min_fill_prob: float = 0.60        # never below 60% fill rate

    # ── Execution delay ───────────────────────────────────────────
    delay_vol_threshold: float = 2.5   # vol z-score above this introduces delay
    delay_bars_max: int = 2            # max bars of execution delay

    # ── Volatility computation ────────────────────────────────────
    vol_window: int = 21               # rolling window for vol estimation


# ══════════════════════════════════════════════════════════════════════
#  I.  Volatility State Estimation
# ══════════════════════════════════════════════════════════════════════

def compute_vol_zscore(path_returns: np.ndarray, config: ExecutionConfig = None) -> np.ndarray:
    """Rolling volatility z-score for each day in each path.

    Vectorized via cumulative sums — no Python per-element loops.

    Args:
        path_returns: (n_paths, n_days) array of daily returns
        config: ExecutionConfig (for vol_window)

    Returns:
        (n_paths, n_days) array of vol z-scores (unitless)
    """
    if config is None:
        config = ExecutionConfig()
    window = config.vol_window
    n_paths, n_days = path_returns.shape

    # Global std per path for normalization
    full_std = np.std(path_returns, axis=1, keepdims=True)
    full_std = np.where(full_std < 1e-10, 1e-10, full_std)

    # Rolling std via cumulative sums: Var = E[X^2] - E[X]^2
    # cumsum[i] = sum of first i elements
    cumsum = np.zeros((n_paths, n_days + 1))
    cumsum2 = np.zeros((n_paths, n_days + 1))
    np.cumsum(path_returns, axis=1, out=cumsum[:, 1:])
    np.cumsum(path_returns ** 2, axis=1, out=cumsum2[:, 1:])

    # For each day i, window is [max(0, i-window+1), i]
    # Use expanding window for first `window` days
    roll_mean = np.zeros((n_paths, n_days))
    roll_var = np.zeros((n_paths, n_days))

    for i in range(n_days):
        start = 0 if i < window else i - window + 1
        n = i - start + 1
        s = cumsum[:, i + 1] - cumsum[:, start]
        s2 = cumsum2[:, i + 1] - cumsum2[:, start]
        roll_mean[:, i] = s / n
        roll_var[:, i] = np.maximum(0, s2 / n - roll_mean[:, i] ** 2)

    roll_std = np.sqrt(roll_var)
    scores = roll_std / full_std
    return scores


# ══════════════════════════════════════════════════════════════════════
#  II.  Execution Effects
# ══════════════════════════════════════════════════════════════════════

def compute_slippage_cost(vol_zscore: np.ndarray, config: ExecutionConfig) -> np.ndarray:
    """Spread expansion as a function of volatility z-score.

    Below z-score = 1: no expansion (normal market).
    Above z-score = 1: linear expansion at spread_vol_slope rate.
    Capped at spread_max_bps to prevent numerical blowup.

    Returns: decimal fraction to subtract from returns.
    """
    excess = np.maximum(0.0, vol_zscore - 1.0)
    spread_bps = config.base_spread_bps * (1.0 + config.spread_vol_slope * excess)
    spread_bps = np.minimum(spread_bps, config.spread_max_bps)
    return spread_bps / 10000.0  # bps → decimal


def compute_gap_noise(vol_zscore: np.ndarray, config: ExecutionConfig,
                      rng: np.random.Generator) -> np.ndarray:
    """Stop-loss gap noise that grows nonlinearly with volatility.

    Gap probability increases with vol z-score.
    Gap magnitude scales with vol^1.5 (nonlinear).
    Always negative — stops gap through, never in your favor.

    Returns: array of gap magnitudes (negative decimals).
    """
    excess = np.maximum(0.0, vol_zscore - 1.0)
    gap_std_bps = config.base_gap_bps * (1.0 + config.gap_vol_slope * excess ** 1.5)
    gap_std_bps = np.minimum(gap_std_bps, config.gap_max_bps)
    gap_std = gap_std_bps / 10000.0

    # Gap probability: base 5% + 15pp per vol z-score above 1
    gap_prob = np.minimum(0.5, 0.05 + 0.15 * excess)

    shape = vol_zscore.shape
    gaps = np.zeros(shape)
    hit = rng.random(shape) < gap_prob
    if hit.any():
        gaps[hit] = -np.abs(rng.normal(0.0, gap_std[hit]))
    return gaps


def compute_fill_ratio(vol_zscore: np.ndarray, config: ExecutionConfig) -> np.ndarray:
    """Fill probability decreases in high volatility.

    Below fill_vol_threshold: full fill (1.0).
    Above threshold: linear decay at fill_prob_slope rate.
    Floored at min_fill_prob.

    Returns: array of fill multipliers in [min_fill_prob, 1.0].
    """
    excess = np.maximum(0.0, vol_zscore - config.fill_vol_threshold)
    ratio = 1.0 + config.fill_prob_slope * excess
    return np.clip(ratio, config.min_fill_prob, 1.0)


def apply_execution_degradation(path_returns: np.ndarray, vol_zscore: np.ndarray,
                                 config: ExecutionConfig,
                                 rng: np.random.Generator) -> np.ndarray:
    """Apply all execution degradation effects to a return path.

    Order of operations:
      1. Partial fills (scale returns down by fill ratio)
      2. Slippage cost (subtract spread from returns)
      3. Gap noise (subtract gap losses)

    Args:
        path_returns: (n_days,) array of daily returns
        vol_zscore: (n_days,) array of vol z-scores
        config: ExecutionConfig
        rng: numpy random generator

    Returns:
        Degraded return array, same shape.
    """
    degraded = path_returns.copy()

    # 1. Partial fills — scale returns
    fill = compute_fill_ratio(vol_zscore, config)
    degraded *= fill

    # 2. Slippage — subtract spread
    slippage = compute_slippage_cost(vol_zscore, config)
    degraded -= slippage

    # 3. Gap noise — subtract gap losses (stop gaps through)
    gaps = compute_gap_noise(vol_zscore, config, rng)
    degraded += gaps

    return degraded


def degrade_all_paths(paths_dict: dict, config: ExecutionConfig = None,
                       per_asset_configs: dict = None,
                       seed: int = 42) -> dict:
    """Apply execution degradation to all paths across all assets.

    Each asset's paths get independently computed vol z-scores and
    execution effects, preserving cross-asset correlation structure.

    Supports per-asset execution configs for markets with different
    microstructure (e.g., crypto vs FX majors).

    Args:
        paths_dict: {name: (n_paths, n_days) returns array}
        config: default ExecutionConfig (used if per_asset_configs has no entry)
        per_asset_configs: {name: ExecutionConfig} optional per-asset overrides
        seed: random seed for reproducibility

    Returns:
        Degraded paths dict, same structure.
    """
    if config is None and not per_asset_configs:
        raise ValueError('Must provide config or per_asset_configs')

    rng = np.random.default_rng(seed)
    degraded = {}

    for name, returns in paths_dict.items():
        # Use per-asset config if available, otherwise default
        asset_config = config
        if per_asset_configs and name in per_asset_configs:
            asset_config = per_asset_configs[name]
        if asset_config is None:
            asset_config = ExecutionConfig()

        vol_zscore = compute_vol_zscore(returns, asset_config)
        n_paths, n_days = returns.shape
        out = np.zeros_like(returns)

        for p in range(n_paths):
            out[p] = apply_execution_degradation(
                returns[p], vol_zscore[p], asset_config, rng)

        degraded[name] = out

    return degraded


# ══════════════════════════════════════════════════════════════════════
#  III.  Portfolio Deleveraging
# ══════════════════════════════════════════════════════════════════════

def apply_deleveraging(equity: np.ndarray, dd_threshold: float = -0.10,
                        max_delever: float = 0.50,
                        recovery_rate: float = 0.005) -> np.ndarray:
    """Portfolio-level deleveraging feedback loop.

    When drawdown exceeds dd_threshold, scale future exposure down
    linearly.  Scale gradually recovers as drawdown recedes.

    This models the real-world behavior of:
      - Risk limits being hit
      - Volatility-targeting position scaling
      - Forced de-risking after losses

    Args:
        equity: (n_paths, n_days+1) equity curves, starting at 1.0
        dd_threshold: drawdown that triggers deleveraging (e.g., -0.10 = 10%)
        max_delever: maximum fractional exposure reduction (e.g., 0.50 = cut 50%)
        recovery_rate: daily scale recovery when above threshold (e.g., 0.005 = 0.5%/day)

    Returns:
        Adjusted equity curves with deleveraging feedback applied.
    """
    n_paths, n_steps = equity.shape
    adjusted = equity.copy()

    for p in range(n_paths):
        scale = 1.0
        peak = float(equity[p, 0])

        for t in range(1, n_steps):
            prev_val = float(adjusted[p, t - 1])
            curr_val = float(equity[p, t])
            raw_ret = curr_val / prev_val - 1.0 if prev_val > 0 else 0.0

            # Update peak and compute drawdown
            peak = max(peak, prev_val)
            dd = (prev_val - peak) / peak if peak > 0 else 0.0

            # Adjust scale
            if dd < dd_threshold:
                dd_excess = abs(dd) - abs(dd_threshold)
                max_dd_room = 1.0 - abs(dd_threshold)
                if max_dd_room > 0:
                    scale = max(1.0 - max_delever,
                                1.0 - (dd_excess / max_dd_room) * max_delever)
            else:
                # Gradual recovery toward full exposure
                scale = min(1.0, scale + recovery_rate)

            # Apply scaled return
            adjusted[p, t] = prev_val * (1.0 + raw_ret * scale)

    return adjusted


# ══════════════════════════════════════════════════════════════════════
#  IV.  BTC-Specific Execution Config
# ══════════════════════════════════════════════════════════════════════

def btc_execution_config() -> ExecutionConfig:
    """BTC-specific execution parameters.

    Crypto markets have wider spreads, larger gaps, and worse liquidity
    during stress compared to FX majors.
    """
    return ExecutionConfig(
        base_spread_bps=2.0,        # 2 bps base (crypto is wider)
        spread_vol_slope=3.0,       # spreads widen faster
        spread_max_bps=150.0,       # up to 150 bps in crisis
        base_gap_bps=2.0,           # 2 bps base gap noise
        gap_vol_slope=5.0,          # gaps are far more severe for crypto
        gap_max_bps=1000.0,         # 10% max gap (crypto flash crash)
        fill_vol_threshold=1.5,     # fills degrade at lower vol threshold
        fill_prob_slope=-0.20,      # fills drop faster
        min_fill_prob=0.30,         # can go down to 30% fill rate
        delay_vol_threshold=2.0,    # delays start earlier
        delay_bars_max=3,           # longer delays
    )


# ══════════════════════════════════════════════════════════════════════
#  V.  Regime-Aware Bootstrap
# ══════════════════════════════════════════════════════════════════════

def compute_composite_vol_index(series_dict: dict, window: int = 21,
                                 weight_power: float = 3.0) -> np.ndarray:
    """Compute a tail-weighted market-wide composite volatility index.

    Weights each asset's rolling vol z-score by its long-term vol raised
    to *weight_power*.  This ensures high-vol assets (e.g. BTC) dominate
    crisis detection instead of being diluted by low-vol FX assets.

    Args:
        series_dict: {name: (n_days,) array of daily returns}
        window: rolling window for vol estimation
        weight_power: exponent for vol weighting.
            0 → equal weight (backward compatible),
            1 → proportional to vol,
            2 → vol-squared,
            3 → vol-cubed (default — high-vol dominates crisis detection)

    Returns:
        (n_days,) array of composite vol index (unitless z-score)
    """
    n_days = min(len(s) for s in series_dict.values())
    names = list(series_dict.keys())
    zscores = np.zeros((len(names), n_days))
    vol_weights = np.zeros(len(names))

    for i, name in enumerate(names):
        arr = series_dict[name][:n_days]
        full_std = float(np.std(arr))
        if full_std < 1e-10:
            full_std = 1e-10
        roll_std = pd.Series(arr).rolling(window, min_periods=1).std().values
        zscores[i] = roll_std / full_std
        vol_weights[i] = full_std ** weight_power

    # Tail-weighted average: high-vol assets dominate crisis detection
    vol_weights = vol_weights / vol_weights.sum()
    # Fill NaN from insufficient rolling windows (first value of rolling std)
    zscores = np.nan_to_num(zscores, nan=0.0)
    composite = zscores.T @ vol_weights
    return composite


def classify_regimes(composite_vol: np.ndarray,
                      calm_threshold: float = 1.0,
                      crisis_threshold: float = 2.0) -> np.ndarray:
    """Classify each day into a volatility regime.

    Args:
        composite_vol: (n_days,) composite vol index
        calm_threshold: below this is CALM (z-score < 1.0)
        crisis_threshold: above this is CRISIS (z-score > 2.0)
                         Between thresholds is ELEVATED

    Returns:
        (n_days,) array of VolRegime values
    """
    regimes = np.full(len(composite_vol), VolRegime.ELEVATED, dtype=int)
    regimes[composite_vol < calm_threshold] = VolRegime.CALM
    regimes[composite_vol > crisis_threshold] = VolRegime.CRISIS
    return regimes


def regime_aware_bootstrap(series_dict: dict, regimes: np.ndarray,
                            n_days: int, n_paths: int,
                            block_len: int = 21, seed: int = 42) -> dict:
    """Block bootstrap that preserves volatility regime persistence.

    Samples contiguous blocks where the START day's regime matches the
    current regime state.  This naturally preserves:
      - Temporal persistence of volatility
      - Cross-asset correlation within regimes
      - Crisis clustering

    Works with any number of assets in series_dict.

    Args:
        series_dict: {name: (n_orig,) array of daily returns}
        regimes: (n_orig,) array of VolRegime — one per day
        n_days: number of days to simulate per path
        n_paths: number of paths
        block_len: block length in days
        seed: random seed

    Returns:
        {name: (n_paths, n_days) array of bootstrapped returns}
    """
    rng = np.random.default_rng(seed)
    names = list(series_dict.keys())
    n_orig = len(regimes)
    result = {n: np.zeros((n_paths, n_days)) for n in names}

    # Precompute valid start indices per regime
    valid_starts = {}
    for regime in VolRegime:
        idx = np.where(regimes == regime)[0]
        valid_starts[regime] = idx[idx < n_orig - block_len]

    # Default: if no valid starts for a regime, fall back to all indices
    all_valid = np.where(np.arange(n_orig) < n_orig - block_len)[0]

    for p in range(n_paths):
        # Start in a random regime (weighted by its frequency)
        current_regime = VolRegime(rng.choice(
            [r for r in VolRegime],
            p=[(regimes == r).mean() for r in VolRegime]))

        pos = 0
        while pos < n_days:
            # Get valid starts for current regime
            starts = valid_starts.get(current_regime, all_valid)
            if len(starts) == 0:
                starts = all_valid

            start = int(rng.choice(starts))
            take = min(block_len, n_days - pos)

            for name in names:
                result[name][p, pos:pos + take] = series_dict[name][start:start + take]

            # Determine next regime from the last day of the sampled block
            next_regime_idx = min(start + take - 1, n_orig - 1)
            current_regime = VolRegime(int(regimes[next_regime_idx]))

            pos += take

    return result


# ══════════════════════════════════════════════════════════════════════
#  VI.  Exposure Telemetry
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TelemetryResult:
    """Exposure and deleveraging diagnostics."""
    exposure_paths: np.ndarray        # (n_paths, n_steps) exposure multiplier
    delever_freq: float               # fraction of days any deleveraging active
    dd_exceed_freq: float             # fraction of days DD > threshold
    median_exposure_by_regime: dict   # regime → median exposure
    mean_exposure_by_regime: dict     # regime → mean exposure
    delever_trigger_rate: float       # fraction of paths that hit deleverage threshold


def compute_exposure_telemetry(equity: np.ndarray,
                                dd_threshold: float = -0.10,
                                max_delever: float = 0.50,
                                recovery_rate: float = 0.005,
                                regimes: Optional[np.ndarray] = None) -> TelemetryResult:
    """Track exposure scaling and deleveraging dynamics.

    Replays the deleveraging logic and records the exposure scale factor
    at each time step for each path.

    Args:
        equity: (n_paths, n_steps) equity curves
        dd_threshold: drawdown that triggers deleveraging
        max_delever: maximum fractional reduction
        recovery_rate: daily recovery when above threshold
        regimes: optional (n_steps-1,) array of VolRegime for regime-bucketed stats

    Returns:
        TelemetryResult
    """
    n_paths, n_steps = equity.shape
    exposure = np.ones_like(equity)

    delever_days = 0
    dd_exceed_days = 0
    total_days = n_paths * (n_steps - 1)
    paths_triggered = np.zeros(n_paths, dtype=bool)

    for p in range(n_paths):
        scale = 1.0
        peak = float(equity[p, 0])

        for t in range(1, n_steps):
            prev_val = float(equity[p, t - 1])
            curr_val = float(equity[p, t])
            peak = max(peak, prev_val)
            dd = (prev_val - peak) / peak if peak > 0 else 0.0

            if dd < dd_threshold:
                dd_excess = abs(dd) - abs(dd_threshold)
                max_dd_room = 1.0 - abs(dd_threshold)
                if max_dd_room > 0:
                    scale = max(1.0 - max_delever,
                                1.0 - (dd_excess / max_dd_room) * max_delever)
            else:
                scale = min(1.0, scale + recovery_rate)

            exposure[p, t] = scale
            if scale < 1.0:
                delever_days += 1
                paths_triggered[p] = True
            if dd < dd_threshold:
                dd_exceed_days += 1

    # Regime-bucketed statistics
    median_exposure_by_regime = {}
    mean_exposure_by_regime = {}

    if regimes is not None:
        n_days = n_steps - 1
        reg_array = np.array(regimes[:n_days])
        for regime in VolRegime:
            mask = reg_array == regime
            if mask.any():
                exp_vals = exposure[:, 1:][:, mask]
                median_exposure_by_regime[int(regime)] = round(float(np.median(exp_vals)), 4)
                mean_exposure_by_regime[int(regime)] = round(float(np.mean(exp_vals)), 4)

    return TelemetryResult(
        exposure_paths=exposure,
        delever_freq=delever_days / max(1, total_days),
        dd_exceed_freq=dd_exceed_days / max(1, total_days),
        median_exposure_by_regime=median_exposure_by_regime,
        mean_exposure_by_regime=mean_exposure_by_regime,
        delever_trigger_rate=float(paths_triggered.mean()),
    )


def plot_exposure_telemetry(telemetry: TelemetryResult, out_dir: str, suffix: str = ''):
    """Plot exposure cone and deleveraging diagnostics."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Exposure cone (percentiles of exposure over time)
    exp = telemetry.exposure_paths
    n_steps = exp.shape[1]
    x = np.arange(n_steps) / 252
    percentiles = [5, 25, 50, 75, 95]
    p_vals = {p: np.percentile(exp, p, axis=0) for p in percentiles}

    ax = axes[0, 0]
    ax.fill_between(x, p_vals[5], p_vals[95], alpha=0.15, color='purple', label='90% CI')
    ax.fill_between(x, p_vals[25], p_vals[75], alpha=0.25, color='purple', label='50% CI')
    ax.plot(x, p_vals[50], 'purple', linewidth=2, label='Median')
    ax.axhline(y=1.0, color='gray', linestyle=':', alpha=0.5)
    ax.set_xlabel('Years')
    ax.set_ylabel('Exposure Scale')
    ax.set_title('Exposure Cone (deleveraging feedback)')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 2. Distribution of minimum exposure per path
    ax = axes[0, 1]
    min_exp = exp.min(axis=1)
    ax.hist(min_exp, bins=50, color='purple', alpha=0.7, edgecolor='white')
    ax.axvline(x=min_exp.mean(), color='darkred', linestyle='--',
               label=f'Mean: {min_exp.mean():.3f}')
    ax.set_xlabel('Minimum Exposure')
    ax.set_ylabel('Number of Paths')
    ax.set_title('Distribution of Min Exposure')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 3. Deleveraging frequency bar
    ax = axes[1, 0]
    bars = ['Delever\nDays', 'DD Exceed\nDays', 'Paths\nTriggered']
    vals = [telemetry.delever_freq * 100, telemetry.dd_exceed_freq * 100,
            telemetry.delever_trigger_rate * 100]
    colors = ['#8e44ad', '#e74c3c', '#f39c12']
    ax.bar(bars, vals, color=colors, alpha=0.8)
    for bar, val in zip(bars, vals):
        ax.text(bar, val + 1, f'{val:.1f}%', ha='center', fontsize=10)
    ax.set_ylabel('Frequency (%)')
    ax.set_title('Deleveraging & Risk-Limit Statistics')
    ax.grid(True, alpha=0.3, axis='y')

    # 4. Exposure by regime
    ax = axes[1, 1]
    if telemetry.median_exposure_by_regime:
        regimes = ['CALM', 'ELEVATED', 'CRISIS']
        med_vals = [telemetry.median_exposure_by_regime.get(i, 0) for i in range(3)]
        mean_vals = [telemetry.mean_exposure_by_regime.get(i, 0) for i in range(3)]
        x_pos = np.arange(len(regimes))
        w = 0.35
        ax.bar(x_pos - w/2, med_vals, w, label='Median', color='#3498db', alpha=0.8)
        ax.bar(x_pos + w/2, mean_vals, w, label='Mean', color='#2ecc71', alpha=0.8)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(regimes)
        ax.set_ylabel('Exposure Level')
        ax.set_title('Exposure by Volatility Regime')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle('Exposure Telemetry & Risk System Diagnostics', fontsize=14, y=1.02)
    fig.tight_layout()

    out_path = os.path.join(out_dir, f'exposure_telemetry{suffix}.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
