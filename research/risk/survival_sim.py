"""Survival Monte Carlo — path-based portfolio risk simulation (v2).

v2 enhancements:
  - Correlated multi-asset bootstrap (same block indices across all assets)
  - Correlation spike + liquidity stress scenario
  - Portfolio variant system (full, no-BTC, BTC-capped, BTC-gated)
  - Marginal contribution analysis (leave-one-out per asset)
  - Multi-variant comparison output

Method:
  For each asset, run replay with plateau-center (SL,TP) to get daily return
  series.  Bootstrap ALL assets simultaneously using the same block indices to
  preserve empirical cross-asset correlation.  Aggregate via portfolio weights.
  Compute risk metrics on the ensemble.  Run stress scenarios with correlation
  breakdown.  Repeat for each variant.

Output:
  data/sandbox/risk/
    survival_results_{VARIANT}.json  — per-variant results
    marginal_contributions.json      — leave-one-out analysis
    variant_comparison.json          — aggregated comparison
    *_{VARIANT}.png                  — charts per variant
"""

import os, sys, json, logging, math, argparse, copy, pickle
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from research.execution_surface.replay_engine import replay, replay_regime, replay_meta_geometry, ReplayConfig, ReplayRegimeConfig
from research.execution_surface.mae_mfe_analyzer import compute_mae_mfe_for_trade
from research.risk.execution_physics import (
    ExecutionConfig, VolRegime, degrade_all_paths, apply_deleveraging,
    btc_execution_config,
    compute_composite_vol_index, classify_regimes, regime_aware_bootstrap,
    compute_exposure_telemetry, TelemetryResult, plot_exposure_telemetry,
)
from shared.meta_labeling import MetaModel, encode_regime, compute_vol_zscore
from research.risk.synthetic_stress import (
    inject_synthetic_blocks,
    validate_tail_statistics,
    print_validation_results,
    regime_fraction_report,
    STRESS_BLOCK_LIBRARY,
)

logger = logging.getLogger("quantforge.risk.survival")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ── paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SANDBOX_BASE = os.path.join(PROJECT_ROOT, 'data', 'sandbox')
REPORT_PATH = os.path.join(SANDBOX_BASE, 'sltp_analysis', 'aggregate_report.json')
RISK_DIR = os.path.join(SANDBOX_BASE, 'risk')

# ── config ────────────────────────────────────────────────────────────
N_PATHS = 1000
SIM_YEARS = 3
TRADE_DAYS = 252
BLOCK_LENGTH = 21
RUIN_THRESHOLD = -0.40
CONF_LEVELS = [0.95, 0.99]
PORTFOLIO_CAPITAL = 100_000
SYNTHETIC_INJECTION_RATE = 0.25  # fraction of series length to add as synthetic crisis blocks

# ── variant definitions ────────────────────────────────────────────────
VARIANTS = {
    'full': {
        'label': 'Full Portfolio (11 assets)',
        'description': 'All 11 assets at current allocations',
        'modify_alloc': None,  # use allocations from config
    },
    'no_btc': {
        'label': 'No BTC',
        'description': 'All assets except BTC, allocations renormalized',
        'modify_alloc': lambda allocs: {k: v for k, v in allocs.items() if k != 'BTC'},
    },
    'btc_capped_5': {
        'label': 'BTC Capped at 5%',
        'description': 'BTC allocation reduced to 5%, others scaled up',
        'modify_alloc': lambda allocs: _cap_asset(allocs, 'BTC', 0.05),
    },
    'btc_gated': {
        'label': 'BTC Regime-Gated',
        'description': 'BTC only active in favorable volatility regimes',
        'modify_alloc': None,  # handled separately via regime filtering
    },
    'synthetic_stress': {
        'label': 'Full Portfolio + Synthetic Stress Injection',
        'description': 'All 11 assets with synthetic CRISIS blocks injected into bootstrap',
        'modify_alloc': None,
    },
}

# ── stress scenarios ───────────────────────────────────────────────────
STRESS_SCENARIOS = {
    'crypto_bear_2022': {
        'label': 'Crypto Bear 2022-style',
        'assets': ['BTC'],
        'shock_duration_days': 252,
        'daily_return': -0.0045,
    },
    'flash_crash': {
        'label': 'Flash Crash (-30% single day)',
        'assets': '__ALL__',
        'shock_duration_days': 1,
        'daily_return': -0.30,
    },
    'correlation_spike': {
        'label': 'Correlation Spike + Liquidity Stress',
        'assets': '__ALL__',
        'shock_duration_days': 126,  # 6 months
        'daily_return': None,
        'vol_multiplier': 2.0,
        'correlation_target': 0.90,  # spike correlations toward 0.9
        'liquidity_gap': 0.15,  # 15% additional slippage on stops
    },
}


# ══════════════════════════════════════════════════════════════════════
#  I.  Data Loading
# ══════════════════════════════════════════════════════════════════════

def _apply_confidence_filter(predictions: pd.DataFrame, name: str,
                               threshold: float) -> tuple[pd.DataFrame, int]:
    """Override signals to NEUTRAL for bars below calibrated confidence threshold.

    Uses isotonic calibration model from data/sandbox/calibration/{NAME}/isotonic.pkl.
    Only assets with existing calibration models are filtered; others pass through.

    Args:
        predictions: predictions DataFrame with 'confidence' and 'signal' columns
        name: asset name (for model path lookup)
        threshold: calibrated confidence threshold [0,1]; bars below get signal=1

    Returns:
        (filtered_predictions, n_filtered_signals)
    """
    model_path = os.path.join(SANDBOX_BASE, 'calibration', name, 'isotonic.pkl')
    if not os.path.exists(model_path):
        logger.info('%s: no calibration model — skipping confidence filter', name)
        return predictions, 0

    with open(model_path, 'rb') as f:
        ir = pickle.load(f)

    conf_raw = predictions['confidence'].values / 100.0
    conf_calibrated = ir.transform(conf_raw)
    conf_calibrated = np.clip(conf_calibrated, 0, 1)

    n_dir_before = int((predictions['signal'] != 1).sum())
    preds = predictions.copy()
    low_conf = conf_calibrated < threshold
    preds.loc[low_conf, 'signal'] = 1  # NEUTRAL
    n_dir_after = int((preds['signal'] != 1).sum())
    n_filtered = n_dir_before - n_dir_after

    logger.info('%s: confidence filter @ %.2f — %d/%d directional signals filtered (%.1f%%)',
                name, threshold, n_filtered, n_dir_before,
                100 * n_filtered / max(1, n_dir_before))

    return preds, n_filtered

def _cap_asset(allocs: dict, asset: str, max_alloc: float) -> dict:
    """Cap a single asset's allocation, scale others proportionally."""
    allocs = dict(allocs)
    if asset in allocs and allocs[asset] > max_alloc:
        excess = allocs[asset] - max_alloc
        allocs[asset] = max_alloc
        # redistribute excess to other assets
        others = {k: v for k, v in allocs.items() if k != asset}
        other_total = sum(others.values())
        if other_total > 0:
            for k in others:
                allocs[k] += excess * (others[k] / other_total)
    return allocs


def load_best_configs() -> dict:
    """Load plateau-center SL/TP configs from aggregate report."""
    with open(REPORT_PATH) as f:
        report = json.load(f)

    configs = {}
    for name, r in report.items():
        if 'error' in r:
            logger.warning('%s: skipped (%s)', name, r['error'])
            continue
        plateau = r.get('plateau', {})
        if plateau and 'error' not in plateau and plateau.get('center_sl_mult'):
            configs[name] = {
                'sl_mult': plateau['center_sl_mult'],
                'tp_mult': plateau['center_tp_mult'],
                'source': 'plateau',
                'expected_sharpe': plateau.get('max_value', 0),
            }
        else:
            bs = r.get('best_sharpe', {})
            configs[name] = {
                'sl_mult': bs['sl_mult'],
                'tp_mult': bs['tp_mult'],
                'source': 'best_sharpe',
                'expected_sharpe': bs.get('sharpe', 0),
            }
        cur = r.get('current', {})
        if cur:
            configs[name]['current'] = {
                'sl_mult': cur['sl_mult'],
                'tp_mult': cur['tp_mult'],
                'sharpe': cur.get('sharpe'),
                'uplift_pct': cur.get('uplift_pct'),
            }
    return configs


def load_allocations() -> dict:
    """Load portfolio allocations from paper_trading.yaml."""
    import yaml
    config_path = os.path.join(PROJECT_ROOT, 'configs', 'paper_trading.yaml')
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return {name: acfg['allocation'] for name, acfg in cfg['assets'].items()}


def load_asset_data(configs: dict, confidence_threshold: float = 0.0,
                     regime_config: ReplayRegimeConfig = None,
                     meta_geometry: bool = False) -> dict:
    """Load OOS predictions and compute daily returns for each asset.

    Uses correlated approach: all daily return series are aligned to the
    common date index (intersection of all asset date ranges).

    When meta_geometry is True, a two-pass flow is used:
      1. Baseline regime replay to generate trades
      2. Train MetaModel on trade outcomes, then second-pass replay
         with meta-model SL/TP adjustments

    Returns:
        asset_data: {name: {'daily_returns': Series, 'config': ..., ...}}
        common_index: DatetimeIndex aligned across all assets
    """
    raw = {}
    indices = []

    for name, cfg in configs.items():
        oos_path = os.path.join(SANDBOX_BASE, name, 'oos_predictions.parquet')
        if not os.path.exists(oos_path):
            continue

        predictions = pd.read_parquet(oos_path)
        replay_cfg = ReplayConfig(sl_mult=cfg['sl_mult'], tp_mult=cfg['tp_mult'])

        # Optional: filter low-confidence signals before replay
        n_filtered = 0
        if confidence_threshold > 0:
            predictions, n_filtered = _apply_confidence_filter(
                predictions, name, confidence_threshold)

        try:
            if meta_geometry:
                # Pass 1: baseline replay to collect trades for meta-model training
                if regime_config is not None:
                    trades_pass1 = replay_regime(predictions, regime_config)
                else:
                    trades_pass1 = replay(predictions, replay_cfg)
                if len(trades_pass1) < 50:
                    logger.warning('%s: %d trades from baseline (< 50), skipping meta-geometry',
                                   name, len(trades_pass1))
                    trades = trades_pass1
                else:
                    # Train meta-model on pass 1 outcomes with real features
                    mm = MetaModel()
                    feature_rows = []
                    labels = []
                    close_series = predictions['close']
                    regime_series = predictions.get('regime', pd.Series(index=predictions.index))
                    # Pre-compute regime change points for days_since_regime_change
                    regime_changed = regime_series != regime_series.shift(1)
                    regime_changed.iloc[0] = False
                    for idx, (_, tr) in enumerate(trades_pass1.iterrows()):
                        ret_pct = float(tr.get('return_pct', 0))
                        conf = float(tr.get('conf_at_entry', 50)) / 100.0
                        reg = str(tr.get('regime', 'unknown'))
                        entry_ts = tr.get('entry_time')
                        if entry_ts is not None and entry_ts in predictions.index:
                            loc = predictions.index.get_loc(entry_ts)
                            close_up_to_entry = close_series.iloc[:loc + 1]
                            vz = compute_vol_zscore(close_up_to_entry)
                            # Days since last regime change up to entry
                            if loc > 0:
                                last_change = regime_changed.iloc[:loc + 1].cumsum().iloc[-1]
                                change_indices = regime_changed.iloc[:loc + 1].values.nonzero()[0]
                                days_since = loc - change_indices[-1] if len(change_indices) > 0 else loc
                            else:
                                days_since = 0
                        else:
                            vz = 0.0
                            days_since = 1
                        # Stability penalty: 0 = very stable (many bars since last change),
                        # approaching 1.0 right after a change, capped at 7 days lookback
                        stability_penalty = max(0.0, 1.0 - days_since / 7.0)
                        feature_rows.append({
                            'primary_confidence': conf,
                            'regime_state_encoded': encode_regime(reg),
                            'feature_stability_penalty': stability_penalty,
                            'vol_zscore': vz,
                            'days_since_regime_change': float(days_since),
                        })
                        labels.append(1 if ret_pct > 0 else 0)
                    if len(feature_rows) >= 50:
                        mm.train(pd.DataFrame(feature_rows), pd.Series(labels))
                    else:
                        logger.warning('%s: only %d trades for meta training, using full only',
                                       name, len(feature_rows))

                    # Pass 2: replay with meta-model adjustments
                    trades = replay_meta_geometry(predictions, regime_config or ReplayRegimeConfig(), mm)
                    logger.info('%s: meta-geometry enabled (pass1=%d trades)', name, len(trades_pass1))
            elif regime_config is not None:
                trades = replay_regime(predictions, regime_config)
                logger.info('%s: regime-conditional geometry enabled', name)
            else:
                trades = replay(predictions, replay_cfg)
            if len(trades) == 0:
                logger.warning('%s: zero trades, skipping', name)
                continue

            daily = _trades_to_daily(trades, predictions.index)
            _n_trades = len(trades)

            # Compute MAE/MFE and exit reason stats per trade
            ohlc = pd.DataFrame({
                'high': predictions['high'],
                'low': predictions['low'],
                'close': predictions['close'],
            })
            trade_mae_mfe = []
            exit_reasons = {'tp': 0, 'sl': 0, 'flip': 0, 'expiry': 0}
            mae_vals, mfe_vals = [], []
            for _, tr in trades.iterrows():
                mm = compute_mae_mfe_for_trade(tr, ohlc)
                trade_mae_mfe.append(mm)
                mae_vals.append(mm['mae_pct'])
                mfe_vals.append(mm['mfe_pct'])
                reason = str(tr.get('reason', 'unknown'))
                if reason in exit_reasons:
                    exit_reasons[reason] += 1

            n_tp = exit_reasons['tp']
            n_sl = exit_reasons['sl']
            n_flip = exit_reasons['flip']
            n_expiry = exit_reasons['expiry']

            # For BTC-gated variant: also extract regime information
            regime_info = None
            if 'regime' in predictions.columns:
                regime_series = predictions['regime']
            else:
                regime_series = None

            raw[name] = {
                'daily_returns': daily,
                'daily_series_raw': daily,
                'n_trades': _n_trades,
                'config': cfg,
                'regime_series': regime_series,
                'predictions': predictions,
                'n_signals_filtered': n_filtered,
                'trade_quality': {
                    'n_trades': _n_trades,
                    'n_tp': n_tp,
                    'n_sl': n_sl,
                    'n_flip': n_flip,
                    'n_expiry': n_expiry,
                    'tp_rate': round(n_tp / _n_trades, 4) if _n_trades > 0 else 0,
                    'sl_rate': round(n_sl / _n_trades, 4) if _n_trades > 0 else 0,
                    'flip_rate': round(n_flip / _n_trades, 4) if _n_trades > 0 else 0,
                    'expiry_rate': round(n_expiry / _n_trades, 4) if _n_trades > 0 else 0,
                    'avg_mae_pct': round(float(pd.Series(mae_vals).mean()), 4) if mae_vals else 0,
                    'avg_mfe_pct': round(float(pd.Series(mfe_vals).mean()), 4) if mfe_vals else 0,
                    'med_mae_pct': round(float(pd.Series(mae_vals).median()), 4) if mae_vals else 0,
                    'med_mfe_pct': round(float(pd.Series(mfe_vals).median()), 4) if mfe_vals else 0,
                    'mae_mfe_ratio': round(
                        float(pd.Series(mae_vals).abs().mean() / pd.Series(mfe_vals).mean()), 4
                    ) if pd.Series(mfe_vals).mean() > 0 else 0,
                },
            }
            indices.append(daily.index)

            logger.info('%s: %d trades, %.0f days, mean=%.4f%%(%.4f%%)',
                        name, _n_trades, len(daily),
                        daily.mean() * 100, daily.std() * 100)

        except Exception as e:
            logger.error('%s: failed — %s', name, e)
            continue

    if not raw:
        raise RuntimeError('No asset data loaded')

    # Align all series to common date intersection
    common_idx = indices[0]
    for idx in indices[1:]:
        common_idx = common_idx.intersection(idx)

    logger.info('Aligning %d assets to common date range: %s to %s (%d days)',
                len(raw), common_idx[0].date(), common_idx[-1].date(), len(common_idx))

    for name, data in raw.items():
        data['daily_returns'] = data['daily_series_raw'].reindex(common_idx).fillna(0)
        data['n_days'] = len(common_idx)
        data['mean_daily_return'] = float(data['daily_returns'].mean())
        data['std_daily_return'] = float(data['daily_returns'].std())
        data['sharpe_implied'] = (
            float(data['daily_returns'].mean() / data['daily_returns'].std() * math.sqrt(252))
            if data['daily_returns'].std() > 0 else 0.0
        )

    return raw


def _trades_to_daily(trades: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Convert trade log to a smooth daily return series.

    Distributes each trade's log-return evenly across its hold period.
    """
    daily = pd.Series(0.0, index=index)
    for t in trades.itertuples(index=False):
        ret = t.return_pct
        hold = t.hold_bars
        if hold <= 0 or np.isnan(ret) or np.isinf(ret) or ret <= -1:
            continue
        daily_log = math.log(1.0 + ret)
        per_bar = daily_log / hold
        entry_idx = index.get_loc(t.entry_time) if t.entry_time in index else -1
        exit_idx = index.get_loc(t.exit_time) if t.exit_time in index else -1
        if exit_idx < 0 or entry_idx < 0:
            continue
        for i in range(max(entry_idx, 0), min(exit_idx + 1, len(daily))):
            daily.iloc[i] += math.expm1(per_bar)
    return daily


# ══════════════════════════════════════════════════════════════════════
#  II.  Correlated Multi-Asset Bootstrap
# ══════════════════════════════════════════════════════════════════════

def multi_asset_bootstrap(asset_data: dict, n_days: int, n_paths: int,
                           block_len: int = BLOCK_LENGTH, seed: int = 42) -> dict:
    """Bootstrap ALL assets using the SAME block indices.

    This preserves the empirical cross-asset correlation structure because
    each path samples the same time blocks for every asset simultaneously.

    Returns:
        {name: (n_paths, n_days) array of daily returns}
    """
    rng = np.random.default_rng(seed)
    # Align all return series
    series_dict = {name: adata['daily_returns'].values for name, adata in asset_data.items()}
    names = list(series_dict.keys())
    n_orig = len(series_dict[names[0]])

    result = {name: np.zeros((n_paths, n_days)) for name in names}

    for p in range(n_paths):
        pos = 0
        while pos < n_days:
            start = rng.integers(0, max(1, n_orig - block_len))
            take = min(block_len, n_days - pos)
            for name in names:
                result[name][p, pos:pos + take] = series_dict[name][start:start + take]
            pos += take

    return result


def bootstrap_regime_gated(asset_data: dict, n_days: int, n_paths: int,
                            block_len: int = BLOCK_LENGTH, seed: int = 42,
                            gate_asset: str = 'BTC',
                            favorable_regimes: list = None) -> dict:
    """Bootstrap with regime gating for a specific asset.

    For the gated asset, only sample blocks where the regime is in the
    favorable list.  Other assets sample freely.

    Returns same format as multi_asset_bootstrap.
    """
    if favorable_regimes is None:
        favorable_regimes = ['low_vol', 'trending']

    rng = np.random.default_rng(seed)
    series_dict = {}
    regime_mask = None

    for name, adata in asset_data.items():
        series_dict[name] = adata['daily_returns'].values
        if name == gate_asset:
            regime_series = adata.get('regime_series')
            if regime_series is not None:
                regime_mask = regime_series.isin(favorable_regimes).values

    names = list(series_dict.keys())
    n_orig = len(series_dict[names[0]])

    result = {name: np.zeros((n_paths, n_days)) for name in names}

    for p in range(n_paths):
        pos = 0
        while pos < n_days:
            # For the gated asset, restrict block start to favorable regimes
            if regime_mask is not None:
                valid_starts = np.where(regime_mask)[0]
                valid_starts = valid_starts[valid_starts < n_orig - block_len]
                if len(valid_starts) == 0:
                    start = rng.integers(0, max(1, n_orig - block_len))
                else:
                    start = rng.choice(valid_starts)
            else:
                start = rng.integers(0, max(1, n_orig - block_len))

            take = min(block_len, n_days - pos)
            for name in names:
                result[name][p, pos:pos + take] = series_dict[name][start:start + take]
            pos += take

    return result


# ══════════════════════════════════════════════════════════════════════
#  III.  Portfolio Path Generation
# ══════════════════════════════════════════════════════════════════════

def generate_portfolio_paths(asset_data: dict, allocations: dict,
                              n_paths: int = N_PATHS, n_days: int = None,
                              seed: int = 42, variant: str = 'full',
                              execution_config: ExecutionConfig = None,
                              deleverage: bool = False,
                              regimes: np.ndarray = None,
                              synthetic_injection_rate: float = 0.0) -> dict:
    """Generate portfolio equity paths using correlated bootstrap.

    For the 'btc_gated' variant, uses regime-filtered bootstrap for BTC.
    When synthetic_injection_rate > 0, pre-pends synthetic stress blocks
    to extend CRISIS regime coverage.

    Returns:
        {
            'paths': (n_paths, n_days + 1) portfolio equity,
            'asset_paths': {name: (n_paths, n_days + 1) equity},
            'allocations': normalized allocations,
            'n_days': int,
            'variant': str,
            'n_synthetic_days': int,
        }
    """
    if n_days is None:
        n_days = SIM_YEARS * TRADE_DAYS

    # Filter asset_data to only those in allocations
    active_assets = {name: adata for name, adata in asset_data.items()
                     if name in allocations and allocations[name] > 0}

    if not active_assets:
        raise ValueError('No active assets in variant')

    n_synthetic_days = 0

    # Inject synthetic stress blocks into return series if requested
    if synthetic_injection_rate > 0:
        series_dict = {n: adata['daily_returns'].values
                       for n, adata in active_assets.items()}
        extended = inject_synthetic_blocks(
            series_dict, injection_rate=synthetic_injection_rate,
            seed=seed + 7777)
        # Determine how many synthetic days were added
        n_orig = min(len(v) for v in series_dict.values())
        n_ext = min(len(v) for v in extended.values())
        n_synthetic_days = n_ext - n_orig

        # Re-compute regimes on extended data if regime bootstrap was active
        if regimes is not None:
            extended_composite = compute_composite_vol_index(
                extended, window=BLOCK_LENGTH)
            extended_regimes = classify_regimes(extended_composite)
            # Override first n_synthetic_days to CRISIS (they are stress by construction)
            extended_regimes[:n_synthetic_days] = VolRegime.CRISIS
            regimes = extended_regimes

        # Rebuild active_assets with extended series
        for n, adata in active_assets.items():
            adata['daily_returns'] = pd.Series(extended[n][n_synthetic_days:],
                                                index=adata['daily_returns'].index)
            # Pre-pend synthetic portion as a synthetic return Series
            syn_index = pd.date_range(
                end=adata['daily_returns'].index[0] - pd.Timedelta(days=1),
                periods=n_synthetic_days, freq='D')
            full_index = pd.DatetimeIndex(np.concatenate([syn_index, adata['daily_returns'].index]))
            full_series = pd.Series(extended[n], index=full_index)
            adata['daily_returns'] = full_series

        logger.info('Synthetic stress injection: %d days added (%.1f%% of original)',
                     n_synthetic_days,
                     100 * n_synthetic_days / max(1, n_orig))

        # Log regime fractions after injection
        if regimes is not None:
            fracs = regime_fraction_report(regimes, n_synthetic_days)
            logger.info('Extended regime fractions: %s', fracs)

    # Bootstrap
    if regimes is not None:
        series_dict = {n: adata['daily_returns'].values
                       for n, adata in active_assets.items()}
        ret_paths = regime_aware_bootstrap(
            series_dict, regimes, n_days, n_paths,
            block_len=BLOCK_LENGTH, seed=seed)
    elif variant == 'btc_gated' and 'BTC' in active_assets:
        ret_paths = bootstrap_regime_gated(
            active_assets, n_days, n_paths, seed=seed,
            gate_asset='BTC', favorable_regimes=['low_vol', 'trending'])
    else:
        ret_paths = multi_asset_bootstrap(
            active_assets, n_days, n_paths, seed=seed)

    # Normalize allocations among active assets
    total_alloc = sum(allocations.values())
    norm_alloc = {n: allocations[n] / total_alloc for n in active_assets}

    # Apply execution degradation (market microstructure effects)
    if execution_config is not None:
        # Build per-asset configs if BTC-specific execution is requested
        per_asset = None
        if isinstance(execution_config, dict):
            per_asset = execution_config
            execution_config = None
        ret_paths = degrade_all_paths(
            ret_paths, config=execution_config,
            per_asset_configs=per_asset, seed=seed + 999)

    # Build equity curves
    asset_paths = {}
    for name, adata in active_assets.items():
        eq = np.ones((n_paths, n_days + 1))
        eq[:, 1:] = np.cumprod(1.0 + ret_paths[name], axis=1)
        asset_paths[name] = eq

    # Aggregate portfolio
    port_eq = np.zeros((n_paths, n_days + 1))
    for name, eq in asset_paths.items():
        port_eq += eq * norm_alloc[name]
    port_eq[:, 0] = 1.0

    # Apply portfolio deleveraging feedback (drawdown → exposure reduction)
    if deleverage:
        for name in asset_paths:
            asset_paths[name] = apply_deleveraging(asset_paths[name])
        port_eq = apply_deleveraging(port_eq)

    return {
        'paths': port_eq,
        'asset_paths': asset_paths,
        'allocations': norm_alloc,
        'n_days': n_days,
        'variant': variant,
        'n_synthetic_days': n_synthetic_days,
    }


# ══════════════════════════════════════════════════════════════════════
#  IV.  Risk Metrics
# ══════════════════════════════════════════════════════════════════════

def compute_drawdowns(equity: np.ndarray) -> np.ndarray:
    """(n_paths, n_steps) drawdown series as negative fractions."""
    running_max = np.maximum.accumulate(equity, axis=1)
    return (equity - running_max) / running_max


def compute_risk_metrics(port_result: dict) -> dict:
    """Full risk metrics from portfolio path ensemble."""
    equity = port_result['paths']
    n_paths, n_steps = equity.shape
    n_days = port_result['n_days']
    capital = PORTFOLIO_CAPITAL
    years = n_days / TRADE_DAYS

    terminal = equity[:, -1]
    terminal_returns = terminal - 1.0
    sorted_ret = np.sort(terminal_returns)

    # Drawdowns
    dd = compute_drawdowns(equity)
    min_dd = dd.min(axis=1)
    ruin_count = int((min_dd < RUIN_THRESHOLD).sum())

    # Per-path annualized metrics
    ann_rets = terminal ** (1.0 / years) - 1.0
    path_ann_vols = np.zeros(n_paths)
    for p in range(n_paths):
        daily_r = np.diff(equity[p]) / equity[p, :-1]
        path_ann_vols[p] = float(daily_r.std() * math.sqrt(TRADE_DAYS)) if daily_r.std() > 0 else 0.0

    ann_ret_p50 = float(np.median(ann_rets))
    ann_vol_p50 = float(np.median(path_ann_vols))

    # Build metrics
    metrics = {
        'ruin': {
            'threshold': RUIN_THRESHOLD,
            'probability': round(ruin_count / n_paths, 4),
            'n_ruined_paths': ruin_count,
            'n_total_paths': n_paths,
        },
        'terminal_wealth': {'capital': capital},
        'drawdown': {},
        'equity_horizons': {},
        'annualized': {},
        'path_distribution': {},
    }

    # Terminal percentiles
    for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        v = float(np.percentile(terminal, pct))
        metrics['terminal_wealth'][f'p{pct}_multiplier'] = round(v, 4)
        metrics['terminal_wealth'][f'p{pct}_return_pct'] = round((v - 1) * 100, 2)

    # VaR / CVaR
    for conf in CONF_LEVELS:
        idx = int((1 - conf) * n_paths)
        pct_ret = float(sorted_ret[idx]) if idx < len(sorted_ret) else float(sorted_ret[-1])
        tail_rets = sorted_ret[:idx + 1]
        var = max(0.0, -pct_ret)
        cvar = max(0.0, -float(tail_rets.mean())) if len(tail_rets) > 0 else var
        metrics['terminal_wealth'][f'var_{int(conf*100)}'] = round(var * 100, 2)
        metrics['terminal_wealth'][f'cvar_{int(conf*100)}'] = round(cvar * 100, 2)
        metrics['terminal_wealth'][f'pctile_return_{int(conf*100)}'] = round(pct_ret * 100, 2)

    # Return distribution summary
    metrics['path_distribution'] = {
        'mean_return_pct': round(float(terminal_returns.mean()) * 100, 2),
        'std_return_pct': round(float(terminal_returns.std()) * 100, 2),
        'skew': round(float(pd.Series(terminal_returns).skew()), 4),
        'min_return_pct': round(float(terminal_returns.min()) * 100, 2),
        'max_return_pct': round(float(terminal_returns.max()) * 100, 2),
        'fraction_positive': round(float((terminal_returns > 0).mean()), 4),
    }

    # Drawdown percentiles
    max_dds = -min_dd
    for pct in [1, 5, 25, 50, 75, 90, 95, 99]:
        metrics['drawdown'][f'p{pct}_max_dd'] = round(float(np.percentile(max_dds, pct)) * 100, 2)
    metrics['drawdown']['worst_case_dd'] = round(float(np.max(max_dds)) * 100, 2)
    metrics['drawdown']['median_max_dd'] = round(float(np.median(max_dds)) * 100, 2)

    # Horizon equity
    horizons = {'1y': min(252, n_steps - 1), '2y': min(504, n_steps - 1), '3y': n_steps - 1}
    for label, step in horizons.items():
        if step >= n_steps:
            continue
        vals = equity[:, step]
        metrics['equity_horizons'][label] = {}
        for pct in [5, 25, 50, 75, 95]:
            v = float(np.percentile(vals, pct))
            metrics['equity_horizons'][label][f'p{pct}'] = round(v, 4)
            metrics['equity_horizons'][label][f'p{pct}_return_pct'] = round((v - 1) * 100, 2)

    # Annualized
    metrics['annualized'] = {
        'return_pct': round(ann_ret_p50 * 100, 2),
        'vol_pct': round(ann_vol_p50 * 100, 2),
        'sharpe': round(ann_ret_p50 / ann_vol_p50, 2) if ann_vol_p50 > 0 else 0,
    }

    return metrics


# ══════════════════════════════════════════════════════════════════════
#  V.  Stress Scenarios (with correlation spike)
# ══════════════════════════════════════════════════════════════════════

def inject_correlation_spike(paths_dict: dict, allocations: dict,
                               shock_start: int, duration: int,
                               target_corr: float = 0.90,
                               vol_mult: float = 2.0) -> dict:
    """Inject correlation spike + vol multiplier into path ensemble.

    Adds a common Gaussian factor to all asset returns during the shock
    period, calibrated to push inter-asset correlations toward target_corr.
    Also scales return vol by vol_mult.

    Returns new paths_dict with shocked returns.
    """
    rng = np.random.default_rng(42)
    names = list(paths_dict.keys())
    n_paths, n_days = paths_dict[names[0]].shape
    shocked = {n: p.copy() for n, p in paths_dict.items()}

    end = min(shock_start + duration, n_days)
    shock_len = end - shock_start

    if shock_len <= 0:
        return shocked

    # Common factor: same shock applied proportionally to each asset
    # Target: correlation ~target_corr. We use a mixture:
    #   shocked_ret = (1 - w) * original_ret + w * common_factor
    # where common_factor ~ N(0, sigma_pooled)
    # w calibrated so that corr(shocked) ≈ target_corr

    # Pooled std across assets
    pooled_std = np.mean([np.std(paths_dict[n][:, shock_start:end], axis=1) for n in names])

    # Mixture weight: w = sqrt(target_corr) (simple approximation)
    w = math.sqrt(max(0, min(1, target_corr)))

    for t in range(shock_start, end):
        common_factor = rng.normal(0, pooled_std, n_paths)
        for name in names:
            # Scale vol
            shocked[name][:, t] *= vol_mult
            # Add common factor (mixture model)
            shocked[name][:, t] = (1 - w) * shocked[name][:, t] + w * common_factor

    return shocked


def _stress_execution_config(cfg: ExecutionConfig) -> ExecutionConfig:
    """Scale an execution config for stress conditions."""
    if cfg is None:
        return None
    return ExecutionConfig(
        base_spread_bps=cfg.base_spread_bps * 2.0,
        spread_vol_slope=cfg.spread_vol_slope * 1.5,
        spread_max_bps=min(cfg.spread_max_bps * 2.0, 200.0),
        base_gap_bps=cfg.base_gap_bps * 3.0,
        gap_vol_slope=cfg.gap_vol_slope * 2.0,
        gap_max_bps=min(cfg.gap_max_bps * 2.0, 1000.0),
        fill_vol_threshold=cfg.fill_vol_threshold * 0.7,
        fill_prob_slope=cfg.fill_prob_slope * 1.5,
        min_fill_prob=max(cfg.min_fill_prob * 0.5, 0.20),
        delay_vol_threshold=cfg.delay_vol_threshold * 0.7,
        delay_bars_max=cfg.delay_bars_max + 1,
    )


def apply_stress(asset_data: dict, allocations: dict,
                 port_result: dict, scenario: str,
                 execution_config: ExecutionConfig = None,
                 deleverage: bool = False,
                 synthetic_injection_rate: float = 0.0) -> dict:
    """Apply a stress scenario with full correlated bootstrap."""
    sconfig = STRESS_SCENARIOS[scenario]
    n_paths = port_result['paths'].shape[0]
    n_days = port_result['n_days']

    # Inject synthetic stress blocks if requested
    active = {n: asset_data[n] for n in port_result['allocations']}
    if synthetic_injection_rate > 0:
        series_dict = {n: adata['daily_returns'].values
                       for n, adata in active.items()}
        extended = inject_synthetic_blocks(
            series_dict, injection_rate=synthetic_injection_rate,
            seed=43 + 7777)
        # Replace daily_returns with the extended array for bootstrap
        class _WrappedArray:
            def __init__(self, arr): self.values = arr
        for n in active:
            active[n] = {**active[n], 'daily_returns': _WrappedArray(extended[n])}

    # Generate base paths using correlated bootstrap
    ret_paths = multi_asset_bootstrap(
        active, n_days, n_paths, seed=43)  # different seed for stress

    # Inject shock
    if scenario == 'correlation_spike':
        shock_start = n_days // 4
        ret_paths = inject_correlation_spike(
            ret_paths, allocations, shock_start,
            sconfig['shock_duration_days'],
            target_corr=sconfig.get('correlation_target', 0.90),
            vol_mult=sconfig.get('vol_multiplier', 2.0))
    elif sconfig.get('daily_return') is not None:
        shock_start = n_days // 4
        for name in ret_paths:
            target_assets = sconfig.get('assets', [])
            if target_assets == '__ALL__' or name in target_assets:
                dur = sconfig['shock_duration_days']
                end = min(shock_start + dur, n_days)
                ret_paths[name][:, shock_start:end] += sconfig['daily_return']
                if sconfig.get('vol_multiplier'):
                    ret_paths[name][:, shock_start:end] *= sconfig['vol_multiplier']

    # Execution degradation is particularly severe during stress
    # (spreads blow out, stops gap through, fills crater)
    if execution_config is not None:
        if isinstance(execution_config, dict):
            per_asset_stress = {
                name: _stress_execution_config(cfg)
                for name, cfg in execution_config.items()
            }
            ret_paths = degrade_all_paths(
                ret_paths, per_asset_configs=per_asset_stress, seed=43 + 999)
        else:
            stress_ex = _stress_execution_config(execution_config)
            ret_paths = degrade_all_paths(ret_paths, stress_ex, seed=43 + 999)

    # Build equity curves
    asset_eq = {}
    for name, rets in ret_paths.items():
        eq = np.ones((n_paths, n_days + 1))
        eq[:, 1:] = np.cumprod(1.0 + rets, axis=1)
        asset_eq[name] = eq

    # Aggregate
    norm_alloc = port_result['allocations']
    port_eq = np.zeros((n_paths, n_days + 1))
    for name, eq in asset_eq.items():
        port_eq += eq * norm_alloc.get(name, 0)
    port_eq[:, 0] = 1.0

    # Portfolio deleveraging also applies during stress
    if deleverage:
        for name in asset_eq:
            asset_eq[name] = apply_deleveraging(asset_eq[name])
        port_eq = apply_deleveraging(port_eq)

    result = {
        'paths': port_eq,
        'asset_paths': asset_eq,
        'allocations': norm_alloc,
        'n_days': n_days,
        'variant': port_result.get('variant', 'unknown'),
    }

    metrics = compute_risk_metrics(result)
    metrics['label'] = sconfig['label']
    metrics['scenario'] = scenario
    return metrics


def run_stress_scenarios(asset_data: dict, allocations: dict,
                          port_result: dict,
                          execution_config: ExecutionConfig = None,
                          deleverage: bool = False,
                          synthetic_injection_rate: float = 0.0) -> dict:
    """Run all stress scenarios."""
    scenarios = {}
    for name in STRESS_SCENARIOS:
        logger.info('  Running stress: %s', name)
        try:
            scenarios[name] = apply_stress(
                asset_data, allocations, port_result, name,
                execution_config=execution_config, deleverage=deleverage,
                synthetic_injection_rate=synthetic_injection_rate)
        except Exception as e:
            logger.error('  Stress %s failed: %s', name, e)
            import traceback; traceback.print_exc()
    return scenarios


# ══════════════════════════════════════════════════════════════════════
#  VI.  Per-Asset Risk
# ══════════════════════════════════════════════════════════════════════

def compute_asset_metrics(asset_data: dict, allocations: dict,
                           n_paths: int = N_PATHS, n_days: int = None,
                           seed: int = 42, variant: str = 'full') -> dict:
    """Individual asset risk metrics (still uses correlated bootstrap)."""
    if n_days is None:
        n_days = SIM_YEARS * TRADE_DAYS

    active = {n: asset_data[n] for n in allocations if allocations.get(n, 0) > 0}
    ret_paths = multi_asset_bootstrap(active, n_days, n_paths, seed=seed)

    results = {}
    for name in active:
        eq = np.ones((n_paths, n_days + 1))
        eq[:, 1:] = np.cumprod(1.0 + ret_paths[name], axis=1)
        dd = compute_drawdowns(eq)
        min_dd = dd.min(axis=1)
        terminal = eq[:, -1]

        tq = asset_data[name].get('trade_quality', {})
        results[name] = {
            'allocation': allocations.get(name, 0),
            'config': asset_data[name]['config'],
            'n_trades': asset_data[name]['n_trades'],
            'n_signals_filtered': asset_data[name].get('n_signals_filtered', 0),
            'daily_return_mean_pct': round(asset_data[name]['mean_daily_return'] * 100, 4),
            'daily_return_std_pct': round(asset_data[name]['std_daily_return'] * 100, 4),
            'sharpe_implied': round(asset_data[name]['sharpe_implied'], 2),
            'ruin_probability': round(float((min_dd < RUIN_THRESHOLD).mean()), 4),
            'median_max_dd_pct': round(float(np.median(-min_dd)) * 100, 2),
            'p95_max_dd_pct': round(float(np.percentile(-min_dd, 95)) * 100, 2),
            'terminal_equity_p50': round(float(np.median(terminal)), 4),
            'terminal_equity_p5': round(float(np.percentile(terminal, 5)), 4),
            'terminal_return_p50_pct': round((float(np.median(terminal)) - 1) * 100, 2),
            'terminal_return_p5_pct': round((float(np.percentile(terminal, 5)) - 1) * 100, 2),
            # Trade quality metrics (from replay, not bootstrap)
            'trade_quality': tq,
        }

    return results


# ══════════════════════════════════════════════════════════════════════
#  VII.  Marginal Contribution Analysis
# ══════════════════════════════════════════════════════════════════════

def compute_marginal_contributions(asset_data: dict, full_allocations: dict,
                                      n_paths: int = N_PATHS, n_days: int = None,
                                      seed: int = 42,
                                      execution_config: ExecutionConfig = None,
                                      deleverage: bool = False) -> dict:
    """Leave-one-out marginal contribution for each asset.

    For each asset, re-runs the full simulation without it, then computes
    the delta in key metrics.  Positive delta = asset improves the metric.
    """
    if n_days is None:
        n_days = SIM_YEARS * TRADE_DAYS

    # Full portfolio baseline
    logger.info('Marginal contribution: running full portfolio baseline...')
    full_result = generate_portfolio_paths(
        asset_data, full_allocations, n_paths, n_days, seed + 100,
        execution_config=execution_config, deleverage=deleverage)
    full_metrics = compute_risk_metrics(full_result)

    contributions = {}
    for name in sorted(full_allocations.keys()):
        logger.info('Marginal contribution: removing %s...', name)
        reduced = {k: v for k, v in full_allocations.items() if k != name}
        total = sum(reduced.values())
        if total <= 0:
            continue
        reduced = {k: v / total for k, v in reduced.items()}

        try:
            red_result = generate_portfolio_paths(
                asset_data, reduced, n_paths, n_days, seed + 200 + hash(name) % 10000,
                execution_config=execution_config, deleverage=deleverage)
            red_metrics = compute_risk_metrics(red_result)

            contributions[name] = {
                'allocation': full_allocations[name],
                'delta_sharpe': round(
                    full_metrics['annualized']['sharpe'] - red_metrics['annualized']['sharpe'], 4),
                'delta_ann_return_pp': round(
                    full_metrics['annualized']['return_pct'] - red_metrics['annualized']['return_pct'], 2),
                'delta_cvar95_pp': round(
                    full_metrics['terminal_wealth']['cvar_95'] - red_metrics['terminal_wealth']['cvar_95'], 2),
                'delta_worst_dd_pp': round(
                    full_metrics['drawdown']['worst_case_dd'] - red_metrics['drawdown']['worst_case_dd'], 2),
                'delta_median_max_dd_pp': round(
                    full_metrics['drawdown']['median_max_dd'] - red_metrics['drawdown']['median_max_dd'], 2),
                'delta_ruin_prob': round(
                    full_metrics['ruin']['probability'] - red_metrics['ruin']['probability'], 4),
                'delta_fraction_positive': round(
                    full_metrics['path_distribution']['fraction_positive'] -
                    red_metrics['path_distribution']['fraction_positive'], 4),
                # Summary: positive delta = asset helps portfolio
                'summary': _summarize_contribution(name, full_metrics, red_metrics),
            }
        except Exception as e:
            logger.error('  Marginal contribution failed for %s: %s', name, e)
            contributions[name] = {'error': str(e), 'allocation': full_allocations[name]}

    return contributions


def _summarize_contribution(name: str, full: dict, reduced: dict) -> str:
    """Generate a human-readable assessment of an asset's contribution."""
    d_sharpe = full['annualized']['sharpe'] - reduced['annualized']['sharpe']
    d_return = full['annualized']['return_pct'] - reduced['annualized']['return_pct']
    d_dd = full['drawdown']['worst_case_dd'] - reduced['drawdown']['worst_case_dd']
    d_cvar = full['terminal_wealth']['cvar_95'] - reduced['terminal_wealth']['cvar_95']

    # Positive delta = asset HELPS
    signals = []
    if d_sharpe > 0.1:
        signals.append('+Sharpe')
    elif d_sharpe < -0.1:
        signals.append('-Sharpe')

    if d_return > 1.0:
        signals.append('+Return')
    elif d_return < -1.0:
        signals.append('-Return')

    if d_dd < -1.0:
        signals.append('+TailRisk')

    if d_cvar > 0.5:
        signals.append('+CVaR')
    elif d_cvar < -0.5:
        signals.append('-CVaR')

    if not signals:
        return 'neutral'

    return ' | '.join(signals)


# ══════════════════════════════════════════════════════════════════════
#  VIII.  Variant Runner
# ══════════════════════════════════════════════════════════════════════

def run_variant(asset_data: dict, base_allocations: dict,
                variant_name: str, n_paths: int, n_days: int, seed: int,
                execution_config: ExecutionConfig = None,
                deleverage: bool = False,
                regimes: np.ndarray = None,
                synthetic_injection_rate: float = 0.0) -> dict:
    """Run full simulation for a single portfolio variant."""
    alloc = base_allocations
    vdef = VARIANTS.get(variant_name, {})

    if vdef.get('modify_alloc') is not None:
        alloc = vdef['modify_alloc'](alloc)

    # Apply synthetic stress injection if variant is synthetic_stress
    effective_rate = synthetic_injection_rate
    if variant_name == 'synthetic_stress' and synthetic_injection_rate <= 0:
        effective_rate = SYNTHETIC_INJECTION_RATE

    logger.info('=' * 60)
    logger.info('Variant: %s', vdef.get('label', variant_name))
    logger.info('Assets: %d, total alloc: %.2f', len(alloc), sum(alloc.values()))
    if effective_rate > 0:
        logger.info('Synthetic stress injection: %.0f%% of original series length',
                     100 * effective_rate)
    logger.info('=' * 60)

    # Generate portfolio paths
    port_result = generate_portfolio_paths(
        asset_data, alloc, n_paths, n_days,
        seed=seed + hash(variant_name) % 10000,
        variant=variant_name,
        execution_config=execution_config,
        deleverage=deleverage,
        regimes=regimes,
        synthetic_injection_rate=effective_rate)

    # Compute metrics
    base_metrics = compute_risk_metrics(port_result)

    # Per-asset metrics (for active assets)
    asset_metrics = compute_asset_metrics(
        asset_data, alloc, n_paths, n_days,
        seed=seed + hash(variant_name) % 10000 + 500,
        variant=variant_name)

    # Stress scenarios
    stress_metrics = run_stress_scenarios(
        asset_data, alloc, port_result,
        execution_config=execution_config, deleverage=deleverage,
        synthetic_injection_rate=effective_rate)

    return {
        'variant': variant_name,
        'label': vdef.get('label', variant_name),
        'allocations': port_result['allocations'],
        'port_result': port_result,
        'metrics': base_metrics,
        'asset_metrics': asset_metrics,
        'stress_metrics': stress_metrics,
        'n_synthetic_days': port_result.get('n_synthetic_days', 0),
    }


# ══════════════════════════════════════════════════════════════════════
#  IX.  Output & Plotting
# ══════════════════════════════════════════════════════════════════════

def plot_equity_fan(port_result: dict, metrics: dict, out_dir: str, suffix: str = ''):
    """Fan chart of portfolio equity paths."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    equity = port_result['paths']
    n_steps = equity.shape[1]
    percentiles = [5, 25, 50, 75, 95]
    p_vals = {p: np.percentile(equity, p, axis=0) for p in percentiles}
    x = np.arange(n_steps) / TRADE_DAYS

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.fill_between(x, p_vals[5], p_vals[95], alpha=0.15, color='blue', label='90% CI')
    ax.fill_between(x, p_vals[25], p_vals[75], alpha=0.25, color='blue', label='50% CI')
    ax.plot(x, p_vals[50], 'b-', linewidth=2, label='Median')
    ax.axhline(y=1.0 + RUIN_THRESHOLD, color='red', linestyle='--', linewidth=1, alpha=0.7,
               label=f'Ruin (-{abs(RUIN_THRESHOLD)*100:.0f}%)')
    ax.axhline(y=1.0, color='gray', linestyle=':', linewidth=1, alpha=0.5)

    ax.set_xlabel('Years', fontsize=12)
    ax.set_ylabel('Equity Multiplier', fontsize=12)
    ax.set_title(f'Portfolio Equity Fan{suffix}', fontsize=14)
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, x[-1] + 0.5)

    out_path = os.path.join(out_dir, f'equity_fan{suffix}.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def plot_drawdown_cones(port_result: dict, out_dir: str, suffix: str = ''):
    """Drawdown cone chart."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    equity = port_result['paths']
    n_steps = equity.shape[1]
    dd = compute_drawdowns(equity)
    percentiles = [5, 25, 50, 75, 95]
    p_vals = {p: np.percentile(dd, p, axis=0) * 100 for p in percentiles}
    x = np.arange(n_steps) / TRADE_DAYS

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.fill_between(x, p_vals[5], p_vals[95], alpha=0.15, color='red', label='90% CI')
    ax.fill_between(x, p_vals[25], p_vals[75], alpha=0.25, color='red', label='50% CI')
    ax.plot(x, p_vals[50], 'r-', linewidth=2, label='Median DD')
    ax.axhline(y=RUIN_THRESHOLD * 100, color='darkred', linestyle='--', linewidth=1.5, alpha=0.8,
               label=f'Ruin ({RUIN_THRESHOLD*100:.0f}%)')

    ax.set_xlabel('Years', fontsize=12)
    ax.set_ylabel('Drawdown (%)', fontsize=12)
    ax.set_title(f'Portfolio Drawdown Cones{suffix}', fontsize=14)
    ax.legend(loc='lower left')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, x[-1] + 0.1)

    out_path = os.path.join(out_dir, f'drawdown_cones{suffix}.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def plot_stress_comparison(base_metrics: dict, stress_metrics: dict,
                            out_dir: str, suffix: str = ''):
    """Stress scenario comparison bar chart."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    labels = ['Base'] + [s['label'] for s in stress_metrics.values()]
    ruin = [base_metrics['ruin']['probability'] * 100]
    rets = [base_metrics['annualized']['return_pct']]
    dds = [base_metrics['drawdown']['worst_case_dd']]
    p5 = [base_metrics['terminal_wealth'].get('return_percentiles', {}).get('p5',
          base_metrics['terminal_wealth'].get('p5_return_pct', 0))]

    for s in stress_metrics.values():
        ruin.append(s['ruin']['probability'] * 100)
        rets.append(s['annualized']['return_pct'])
        dds.append(s['drawdown']['worst_case_dd'])
        rp = s['terminal_wealth'].get('return_percentiles', {})
        p5.append(rp.get('p5', s['terminal_wealth'].get('p5_return_pct', 0)))

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    colors = ['#2ecc71'] + ['#e74c3c'] * (len(labels) - 1)

    axes[0, 0].bar(labels, ruin, color=colors)
    axes[0, 0].set_title('Ruin Probability (%)')
    axes[0, 0].tick_params(axis='x', rotation=20)

    axes[0, 1].bar(labels, rets, color=colors)
    axes[0, 1].set_title('Median Ann. Return (%)')
    axes[0, 1].tick_params(axis='x', rotation=20)

    axes[1, 0].bar(labels, dds, color=colors)
    axes[1, 0].set_title('Worst-Case Drawdown (%)')
    axes[1, 0].tick_params(axis='x', rotation=20)

    axes[1, 1].bar(labels, p5, color=colors)
    axes[1, 1].set_title('P5 Terminal Return (%)')
    axes[1, 1].tick_params(axis='x', rotation=20)

    fig.suptitle(f'Stress Scenario Comparison{suffix}', fontsize=16, y=1.02)
    fig.tight_layout()

    out_path = os.path.join(out_dir, f'stress_comparison{suffix}.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def plot_variant_comparison(results: dict, out_dir: str):
    """Compare key metrics across portfolio variants."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    labels = [r['label'] for r in results.values()]
    metrics_list = [r['metrics'] for r in results.values()]

    sharpe = [m['annualized']['sharpe'] for m in metrics_list]
    ann_ret = [m['annualized']['return_pct'] for m in metrics_list]
    ann_vol = [m['annualized']['vol_pct'] for m in metrics_list]
    ruin = [m['ruin']['probability'] * 100 for m in metrics_list]
    worst_dd = [m['drawdown']['worst_case_dd'] for m in metrics_list]
    median_term = [m['terminal_wealth']['p50_multiplier'] for m in metrics_list]
    p5_term = [m['terminal_wealth']['p5_multiplier'] for m in metrics_list]

    fig, axes = plt.subplots(2, 3, figsize=(16, 10))

    metrics_data = [
        (axes[0, 0], sharpe, 'Sharpe (annualized)', '#2ecc71'),
        (axes[0, 1], ann_ret, 'Median Ann. Return (%)', '#3498db'),
        (axes[0, 2], ann_vol, 'Median Ann. Vol (%)', '#e74c3c'),
        (axes[1, 0], ruin, 'Ruin Probability (%)', '#e67e22'),
        (axes[1, 1], worst_dd, 'Worst-Case Drawdown (%)', '#c0392b'),
        (axes[1, 2], [m['path_distribution']['fraction_positive'] * 100 for m in metrics_list],
         'Fraction of Paths Positive (%)', '#27ae60'),
    ]

    for ax, data, title, color in metrics_data:
        bars = ax.bar(labels, data, color=color, alpha=0.8)
        ax.set_title(title, fontsize=11)
        ax.tick_params(axis='x', rotation=15)
        # Add value labels on bars
        for bar, val in zip(bars, data):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f'{val:.2f}', ha='center', va='bottom', fontsize=9)

    fig.suptitle('Portfolio Variant Comparison', fontsize=16, y=1.02)
    fig.tight_layout()

    out_path = os.path.join(out_dir, 'variant_comparison.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info('Variant comparison saved to %s', out_path)


def plot_marginal_contributions(contributions: dict, out_dir: str):
    """Bar chart of marginal contributions per asset."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    names = []
    d_sharpe = []
    d_return = []
    d_dd = []

    for name, c in sorted(contributions.items()):
        if 'error' in c:
            continue
        names.append(name)
        d_sharpe.append(c['delta_sharpe'])
        d_return.append(c['delta_ann_return_pp'])
        d_dd.append(c['delta_worst_dd_pp'])

    fig, axes = plt.subplots(1, 3, figsize=(16, 6))

    for ax, data, title, colors in [
        (axes[0], d_sharpe, 'Marginal Sharpe Contribution',
         ['#2ecc71' if v > 0 else '#e74c3c' for v in d_sharpe]),
        (axes[1], d_return, 'Marginal Ann. Return (pp)',
         ['#2ecc71' if v > 0 else '#e74c3c' for v in d_return]),
        (axes[2], d_dd, 'Marginal Worst DD (pp, neg = adds risk)',
         ['#e74c3c' if v < 0 else '#2ecc71' for v in d_dd]),
    ]:
        bars = ax.bar(names, data, color=colors, alpha=0.8)
        ax.set_title(title, fontsize=11)
        ax.tick_params(axis='x', rotation=45)
        ax.axhline(y=0, color='black', linewidth=0.5)
        for bar, val in zip(bars, data):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f'{val:+.3f}', ha='center', va='bottom' if val >= 0 else 'top',
                    fontsize=8)

    fig.suptitle('Marginal Contribution Analysis (leave-one-out)', fontsize=14, y=1.02)
    fig.tight_layout()

    out_path = os.path.join(out_dir, 'marginal_contributions.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info('Marginal contributions chart saved to %s', out_path)


# ══════════════════════════════════════════════════════════════════════
#  X.  Console Output
# ══════════════════════════════════════════════════════════════════════

def print_variant_summary(name: str, result: dict):
    """Print formatted summary for a single variant."""
    m = result['metrics']
    tw = m['terminal_wealth']

    print(f'\n  ┌─ {result["label"]}')
    print(f'  │  Assets: {len(result["allocations"])}  |  '
          f'Ruin: {m["ruin"]["probability"]*100:.2f}%  |  '
          f'Sharpe: {m["annualized"]["sharpe"]:.2f}  |  '
          f'Ann.Ret: {m["annualized"]["return_pct"]:+.1f}%')
    print(f'  │  Terminal: P50={tw["p50_multiplier"]:.3f}x  P5={tw["p5_multiplier"]:.3f}x  '
          f'P1={tw.get("p1_multiplier", 0):.3f}x  |  '
          f'Worst DD: {m["drawdown"]["worst_case_dd"]:.1f}%  |  '
          f'Med DD: {m["drawdown"]["median_max_dd"]:.1f}%')
    print(f'  │  Positive paths: {m["path_distribution"]["fraction_positive"]*100:.1f}%  |  '
          f'Return skew: {m["path_distribution"]["skew"]:.2f}')
    print(f'  └─')


def print_comparison_summary(variant_results: dict, marginal: dict = None):
    """Print multi-variant comparison table."""
    print('\n' + '=' * 120)
    print('  PORTFOLIO VARIANT COMPARISON')
    print('=' * 120)

    header = ('  {:>24s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  '
              '{:>8s}  {:>8s}  {:>8s}')
    print(header.format('Variant', 'Assets', 'Ruin%', 'Sharpe', 'Ann.Ret%',
                        'MedDD%', 'WstDD%', 'TermP50x', 'TermP5x', 'Pos%'))
    print('  ' + '-' * 116)

    for name, r in variant_results.items():
        m = r['metrics']
        tw = m['terminal_wealth']
        print(header.format(
            r['label'][:24],
            str(len(r['allocations'])),
            f'{m["ruin"]["probability"]*100:.2f}',
            f'{m["annualized"]["sharpe"]:.2f}',
            f'{m["annualized"]["return_pct"]:+.1f}',
            f'{m["drawdown"]["median_max_dd"]:.1f}',
            f'{m["drawdown"]["worst_case_dd"]:.1f}',
            f'{tw["p50_multiplier"]:.2f}',
            f'{tw["p5_multiplier"]:.2f}',
            f'{m["path_distribution"]["fraction_positive"]*100:.1f}',
        ))

    # Stress impact per variant (flash crash + correlation spike)
    print('\n  ── Flash Crash Impact ──')
    print(header.format('Variant', '', 'Ruin%', 'Sharpe', 'Ann.Ret%',
                        'MedDD%', 'WstDD%', 'P50x', 'P5x', 'Pos%'))
    print('  ' + '-' * 116)
    for name, r in variant_results.items():
        sm = r.get('stress_metrics', {}).get('flash_crash')
        if not sm:
            continue
        tw2 = sm['terminal_wealth']
        print(header.format(
            r['label'][:24], '',
            f'{sm["ruin"]["probability"]*100:.2f}',
            f'{sm["annualized"]["sharpe"]:.2f}',
            f'{sm["annualized"]["return_pct"]:+.1f}',
            f'{sm["drawdown"]["median_max_dd"]:.1f}',
            f'{sm["drawdown"]["worst_case_dd"]:.1f}',
            f'{tw2["p50_multiplier"]:.2f}',
            f'{tw2["p5_multiplier"]:.2f}',
            f'{sm["path_distribution"]["fraction_positive"]*100:.1f}',
        ))

    print('\n  ── Correlation Spike + Liquidity Stress ──')
    print(header.format('Variant', '', 'Ruin%', 'Sharpe', 'Ann.Ret%',
                        'MedDD%', 'WstDD%', 'P50x', 'P5x', 'Pos%'))
    print('  ' + '-' * 116)
    for name, r in variant_results.items():
        sm = r.get('stress_metrics', {}).get('correlation_spike')
        if not sm:
            continue
        tw2 = sm['terminal_wealth']
        print(header.format(
            r['label'][:24], '',
            f'{sm["ruin"]["probability"]*100:.2f}',
            f'{sm["annualized"]["sharpe"]:.2f}',
            f'{sm["annualized"]["return_pct"]:+.1f}',
            f'{sm["drawdown"]["median_max_dd"]:.1f}',
            f'{sm["drawdown"]["worst_case_dd"]:.1f}',
            f'{tw2["p50_multiplier"]:.2f}',
            f'{tw2["p5_multiplier"]:.2f}',
            f'{sm["path_distribution"]["fraction_positive"]*100:.1f}',
        ))

    # Marginal contribution
    if marginal:
        print('\n  ── Marginal Contribution (leave-one-out) ──')
        mc_header = '  {:>10s}  {:>6s}  {:>10s}  {:>10s}  {:>12s}  {:>14s}'
        print(mc_header.format('Asset', 'Alloc%', 'Δ Sharpe', 'Δ Ann.Ret%',
                                'Δ Worst DD%', 'Assessment'))
        print('  ' + '-' * 70)
        for name, c in sorted(marginal.items()):
            if 'error' in c:
                print(f'  {name:>10s}  ERROR: {c["error"]}')
                continue
            print(mc_header.format(
                name,
                f'{c["allocation"]*100:.1f}',
                f'{c["delta_sharpe"]:+.4f}',
                f'{c["delta_ann_return_pp"]:+.2f}',
                f'{c["delta_worst_dd_pp"]:+.2f}',
                c.get('summary', ''),
            ))

    # Trade quality per asset
    print('\n  ── Per-Asset Trade Quality (MAE/MFE & Exit Reason) ──')
    tq_header = '  {:>10s}  {:>5s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}  {:>5s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}'
    print(tq_header.format('Asset', 'Trades', 'TP%', 'SL%', 'Flip%', 'Exp%',
                            'Filt', 'AvgMAE%', 'AvgMFE%', 'MedMAE%', 'M/M Rat'))
    print('  ' + '-' * 100)

    # Use first variant's asset_metrics for trade quality (same for all variants)
    first_variant = next(iter(variant_results.values()))
    for name, am in sorted(first_variant['asset_metrics'].items()):
        tq = am.get('trade_quality', {})
        if not tq:
            continue
        n_filt = am.get('n_signals_filtered', 0)
        print(tq_header.format(
            name,
            str(tq.get('n_trades', 0)),
            f'{tq.get("tp_rate", 0) * 100:.1f}',
            f'{tq.get("sl_rate", 0) * 100:.1f}',
            f'{tq.get("flip_rate", 0) * 100:.1f}',
            f'{tq.get("expiry_rate", 0) * 100:.1f}',
            str(n_filt) if n_filt > 0 else '—',
            f'{tq.get("avg_mae_pct", 0):.2f}',
            f'{tq.get("avg_mfe_pct", 0):.2f}',
            f'{tq.get("med_mae_pct", 0):.2f}',
            f'{tq.get("mae_mfe_ratio", 0):.2f}',
        ))

    print('\n' + '=' * 120 + '\n')


# ══════════════════════════════════════════════════════════════════════
#  XI.  Main
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Portfolio Survival Monte Carlo (v2)')
    parser.add_argument('--paths', type=int, default=N_PATHS)
    parser.add_argument('--years', type=int, default=SIM_YEARS)
    parser.add_argument('--no-plots', action='store_true')
    parser.add_argument('--no-stress', action='store_true')
    parser.add_argument('--no-marginal', action='store_true')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--variant', nargs='+',
                        default=list(VARIANTS.keys()),
                        choices=list(VARIANTS.keys()) + ['all'],
                        help='Portfolio variants to run')
    parser.add_argument('--execution-physics', action='store_true',
                        help='Enable execution degradation (spread/gaps/fills)')
    parser.add_argument('--btc-execution', action='store_true',
                        help='Use BTC-specific execution parameters')
    parser.add_argument('--deleverage', action='store_true',
                        help='Enable portfolio deleveraging feedback')
    parser.add_argument('--regime-bootstrap', action='store_true',
                        help='Use regime-aware block bootstrap')
    parser.add_argument('--exposure-telemetry', action='store_true',
                        help='Track exposure scaling and deleveraging diagnostics')
    parser.add_argument('--synthetic-stress', type=float, default=0.0, nargs='?',
                        const=SYNTHETIC_INJECTION_RATE,
                        help=f'Inject synthetic crisis blocks (default rate: {SYNTHETIC_INJECTION_RATE})')
    parser.add_argument('--validate-tails', action='store_true',
                        help='Run tail validation against historical crisis benchmarks')
    parser.add_argument('--confidence-filter', type=float, default=0.0,
                        help='Calibrated confidence threshold [0-1]; bars below get signal=NEUTRAL (default: 0.0 = off)')
    parser.add_argument('--regime-geometry', type=str, default=None, nargs='?',
                        const='research/execution_surface/recommended_geometries.json',
                        help='Use regime-conditional SL/TP geometry. Optionally provide custom config JSON path (default: recommended_geometries.json)')
    parser.add_argument('--meta-geometry', action='store_true',
                        help='Two-pass meta-labeling: train MetaModel on baseline trades, then adjust SL/TP per trade')
    args = parser.parse_args()

    n_paths = args.paths
    n_days = args.years * TRADE_DAYS
    variants = [v for v in VARIANTS if v in args.variant or 'all' in args.variant]

    deleverage = args.deleverage

    os.makedirs(RISK_DIR, exist_ok=True)

    # 1. Load data
    logger.info('Loading configs and allocations...')
    configs = load_best_configs()
    base_allocations = load_allocations()

    # Build regime-conditional geometry config if requested
    regime_config = None
    if args.regime_geometry:
        geom_path = os.path.join(PROJECT_ROOT, args.regime_geometry)
        if os.path.exists(geom_path):
            with open(geom_path) as f:
                geom_data = json.load(f)
            rc = geom_data.get('regime_conditional', {})
            regime_config = ReplayRegimeConfig(
                regime_geom={
                    'low_vol':    rc.get('low_vol',    {'sl_mult': 0.52, 'tp_mult': 1.96}),
                    'transition': rc.get('transition', {'sl_mult': 0.65, 'tp_mult': 1.65}),
                    'high_vol':   rc.get('high_vol',   {'sl_mult': 0.75, 'tp_mult': 1.50}),
                },
                default_geom={'sl_mult': 0.65, 'tp_mult': 1.65},
            )
            logger.info('Regime-conditional geometry loaded from %s', geom_path)
            for regime, g in regime_config.regime_geom.items():
                logger.info('  %s: sl=%.2f, tp=%.2f', regime, g['sl_mult'], g['tp_mult'])
        else:
            logger.warning('Regime geometry file not found at %s — using defaults',
                           geom_path)

    asset_data = load_asset_data(configs, confidence_threshold=args.confidence_filter,
                                  regime_config=regime_config,
                                  meta_geometry=args.meta_geometry)

    # Compute composite vol index and regimes (for regime-aware bootstrap)
    regimes = None
    if args.regime_bootstrap:
        series_dict = {n: adata['daily_returns'].values for n, adata in asset_data.items()}
        composite_vol = compute_composite_vol_index(series_dict, window=BLOCK_LENGTH)
        regimes = classify_regimes(composite_vol)
        r_counts = {int(r): (regimes == r).sum() for r in VolRegime}
        logger.info('Regime classification: CALM=%d ELEVATED=%d CRISIS=%d',
                     r_counts[0], r_counts[1], r_counts[2])

    # Build execution config (after asset_data so we know asset names)
    execution_config = None
    if args.execution_physics:
        if args.btc_execution:
            # Per-asset configs: FX assets use moderate defaults, BTC uses crypto
            fx_cfg = ExecutionConfig()
            btc_cfg = btc_execution_config()
            execution_config = {name: (btc_cfg if name == 'BTC' else fx_cfg)
                                for name in asset_data}
            logger.info('Execution physics enabled with BTC-specific params')
        else:
            execution_config = ExecutionConfig()
            logger.info('Execution physics enabled (FX defaults)')
    if deleverage:
        logger.info('Portfolio deleveraging enabled')

    # 2. Run each variant
    variant_results = {}
    synthetic_injection_rate = args.synthetic_stress or 0.0
    for vname in variants:
        logger.info('Running variant: %s', vname)
        result = run_variant(asset_data, base_allocations, vname,
                              n_paths, n_days, args.seed,
                              execution_config=execution_config,
                              deleverage=deleverage, regimes=regimes,
                              synthetic_injection_rate=synthetic_injection_rate)
        variant_results[vname] = result

        # Save individual variant results
        v_results_data = {
            'simulation_params': {
                'n_paths': n_paths, 'n_days': n_days,
                'years': args.years, 'ruin_threshold': RUIN_THRESHOLD,
                'block_length': BLOCK_LENGTH, 'variant': vname,
                'synthetic_injection_rate': synthetic_injection_rate,
            },
            'portfolio': result['metrics'],
            'assets': result['asset_metrics'],
            'stress_scenarios': {
                k: v for k, v in result['stress_metrics'].items()
            },
            'n_synthetic_days': result.get('n_synthetic_days', 0),
        }
        vpath = os.path.join(RISK_DIR, f'survival_results_{vname}.json')
        with open(vpath, 'w') as f:
            json.dump(v_results_data, f, indent=2)
        logger.info('  Saved to %s', vpath)

        # Print per-variant summary
        print_variant_summary(vname, result)

        # Generate per-variant plots
        if not args.no_plots:
            suffix = f'_{vname}'
            plot_equity_fan(result['port_result'], result['metrics'],
                            RISK_DIR, suffix)
            plot_drawdown_cones(result['port_result'], RISK_DIR, suffix)
            plot_stress_comparison(result['metrics'], result['stress_metrics'],
                                   RISK_DIR, suffix)

    # 3. Exposure telemetry (on each variant)
    telemetry_results = {}
    if args.exposure_telemetry:
        for vname, result in variant_results.items():
            eq = result['port_result']['paths']
            telemetry = compute_exposure_telemetry(eq, regimes=regimes)
            telemetry_results[vname] = {
                'delever_freq': telemetry.delever_freq,
                'dd_exceed_freq': telemetry.dd_exceed_freq,
                'delever_trigger_rate': telemetry.delever_trigger_rate,
                'median_exposure_by_regime': telemetry.median_exposure_by_regime,
                'mean_exposure_by_regime': telemetry.mean_exposure_by_regime,
            }
            if not args.no_plots:
                plot_exposure_telemetry(telemetry, RISK_DIR, f'_{vname}')

        tpath = os.path.join(RISK_DIR, 'exposure_telemetry.json')
        with open(tpath, 'w') as f:
            json.dump(telemetry_results, f, indent=2)
        logger.info('Exposure telemetry saved to %s', tpath)

    # 5. Marginal contribution (on full portfolio only)
    marginal = None
    if not args.no_marginal and 'full' in variant_results:
        logger.info('Computing marginal contributions (leave-one-out)...')
        marginal = compute_marginal_contributions(
            asset_data, base_allocations, n_paths, n_days, args.seed,
            execution_config=execution_config, deleverage=deleverage)
        mpath = os.path.join(RISK_DIR, 'marginal_contributions.json')
        with open(mpath, 'w') as f:
            json.dump(marginal, f, indent=2)
        logger.info('Marginal contributions saved to %s', mpath)

        if not args.no_plots:
            plot_marginal_contributions(marginal, RISK_DIR)

    # 6. Comparison output
    print_comparison_summary(variant_results, marginal)

    # 7. Variant comparison plot
    if not args.no_plots and len(variant_results) > 1:
        plot_variant_comparison(variant_results, RISK_DIR)

    # 8. Save consolidated comparison
    comparison = {
        'variants': {
            vname: {
                'label': r['label'],
                'allocations': r['allocations'],
                'metrics': r['metrics'],
                'stress_metrics': r['stress_metrics'],
            }
            for vname, r in variant_results.items()
        },
        'marginal_contributions': marginal,
    }
    cpath = os.path.join(RISK_DIR, 'variant_comparison.json')
    with open(cpath, 'w') as f:
        json.dump(comparison, f, indent=2)
    logger.info('Consolidated comparison saved to %s', cpath)

    # 9. Tail validation against historical crisis benchmarks
    if args.validate_tails and 'full' in variant_results:
        logger.info('Running bootstrap tail validation...')
        port_eq = variant_results['full']['port_result']['paths']
        val_results = validate_tail_statistics(port_eq)
        print_validation_results(val_results)
        vpath = os.path.join(RISK_DIR, 'tail_validation.json')
        with open(vpath, 'w') as f:
            json.dump([{
                'metric': r.metric,
                'historical_value': r.historical_value,
                'simulated_p50': r.simulated_p50,
                'plausible': r.plausible,
                'note': r.note,
            } for r in val_results], f, indent=2)
        logger.info('Tail validation saved to %s', vpath)

    logger.info('Done.')


if __name__ == '__main__':
    main()
