"""Phase A.3 — Monte Carlo parameter sweep over execution surface.

For each asset with frozen OOS predictions:
1. Sample 500 random (sl_mult, tp_mult) pairs
2. Run replay for each sample
3. Compute trade metrics with statistical filters
4. Optionally run fixed grid for sharp heatmaps
5. Store results to parquet

Output: data/sandbox/{NAME}/sltp_surface.parquet
"""

import os, sys, logging
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from research.execution_surface.replay_engine import replay, ReplayConfig
from features.registry import FEATURE_REGISTRY

logger = logging.getLogger("quantforge.execution_surface.mc")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SANDBOX_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            'data', 'sandbox')
N_RANDOM = 500
N_GRID_SL = 8
N_GRID_TP = 8
MIN_TRADES = 30
TRADE_DAYS_PER_YEAR = 252


def compute_trade_metrics(trades: pd.DataFrame, sl_mult: float, tp_mult: float) -> dict:
    """Compute aggregate metrics from a trade log DataFrame.

    Applies statistical filters:
    - Reject if trade count < MIN_TRADES
    - Flag if PF driven by <5 largest winners (>50% of gross profit)
    """
    n_trades = len(trades)
    if n_trades < MIN_TRADES:
        return {
            'sl_mult': sl_mult, 'tp_mult': tp_mult,
            'n_trades': n_trades, 'valid': False,
        }

    returns = trades['return_pct'].values
    gross_win = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    n_winners = int((returns > 0).sum())
    n_losers = int((returns < 0).sum())

    # Profit factor
    pf = gross_win / gross_loss if gross_loss > 0 else (float('inf') if gross_win > 0 else 0.0)

    # Win rate
    win_rate = n_winners / n_trades if n_trades > 0 else 0.0

    # Expectancy
    expectancy = float(returns.mean())

    # Sharpe (annualized, using raw returns as daily)
    sharpe = 0.0
    if returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADE_DAYS_PER_YEAR))

    # Max drawdown from cumulative return series
    cumulative = (1 + returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    max_dd = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

    # Avg hold bars
    avg_hold = float(trades['hold_bars'].mean()) if n_trades > 0 else 0.0

    # Exit reason rates
    stop_hit = float((trades['reason'] == 'sl').mean()) if n_trades > 0 else 0.0
    tp_hit = float((trades['reason'] == 'tp').mean()) if n_trades > 0 else 0.0
    flip_rate = float((trades['reason'] == 'flip').mean()) if n_trades > 0 else 0.0
    expiry_rate = float((trades['reason'] == 'expiry').mean()) if n_trades > 0 else 0.0

    # Payoff asymmetry
    avg_win = float(returns[returns > 0].mean()) if n_winners > 0 else 0.0
    avg_loss = float(abs(returns[returns < 0].mean())) if n_losers > 0 else 0.0
    payoff_asym = avg_win / avg_loss if avg_loss > 0 else 0.0

    # Concentration: fraction of gross profit from top 5 trades
    top5 = np.sort(returns[returns > 0])[-5:] if n_winners >= 5 else returns[returns > 0]
    top5_share = top5.sum() / gross_win if gross_win > 0 else 0.0

    # Stability: yearly Sharpe dispersion (if multiple years present)
    if 'year' in trades.columns and trades['year'].nunique() > 1:
        yearly_sharpes = trades.groupby('year')['return_pct'].apply(
            lambda x: x.mean() / x.std() * np.sqrt(TRADE_DAYS_PER_YEAR) if x.std() > 0 else 0.0
        )
        sharpe_stability = float(yearly_sharpes.std())
    else:
        sharpe_stability = 0.0

    return {
        'sl_mult': sl_mult,
        'tp_mult': tp_mult,
        'n_trades': n_trades,
        'valid': True,
        'pf': pf,
        'win_rate': win_rate,
        'expectancy': expectancy,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'avg_hold_bars': avg_hold,
        'stop_hit_freq': stop_hit,
        'tp_hit_freq': tp_hit,
        'flip_freq': flip_rate,
        'expiry_freq': expiry_rate,
        'payoff_asym': payoff_asym,
        'top5_concentration': top5_share,
        'sharpe_stability': sharpe_stability,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'n_winners': n_winners,
        'n_losers': n_losers,
    }


def _grid_values():
    """Return fixed grid ranges for deterministic heatmaps."""
    sl_vals = np.linspace(0.5, 3.0, N_GRID_SL)
    tp_vals = np.linspace(0.5, 5.0, N_GRID_TP)
    return sl_vals, tp_vals


def sweep_one(name: str, predictions: pd.DataFrame, force: bool = False) -> str:
    """Run MC sweep for a single asset.

    Args:
        name: asset name (matches sandbox subdirectory)
        predictions: frozen OOS predictions DataFrame
        force: re-run even if results exist

    Returns:
        Path to output parquet file.
    """
    out_dir = os.path.join(SANDBOX_BASE, name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'sltp_surface.parquet')
    if os.path.exists(out_path) and not force:
        logger.info('%s: surface already exists at %s', name, out_path)
        return out_path

    # 1. Random samples (uniform over parameter space)
    np.random.seed(42)
    sl_random = np.random.uniform(0.5, 3.0, N_RANDOM)
    tp_random = np.random.uniform(0.5, 5.0, N_RANDOM)

    # 2. Grid samples for deterministic coverage
    sl_grid, tp_grid = _grid_values()
    sl_grid_2d, tp_grid_2d = np.meshgrid(sl_grid, tp_grid)
    sl_all = np.concatenate([sl_random, sl_grid_2d.ravel()])
    tp_all = np.concatenate([tp_random, tp_grid_2d.ravel()])

    results = []
    total = len(sl_all)
    for i, (sl, tp) in enumerate(zip(sl_all, tp_all)):
        if (i + 1) % 50 == 0:
            logger.info('  %s: %d/%d samples', name, i + 1, total)

        config = ReplayConfig(sl_mult=sl, tp_mult=tp)
        trades = replay(predictions, config)
        metrics = compute_trade_metrics(trades, sl, tp)
        results.append(metrics)

    df = pd.DataFrame(results)
    df.to_parquet(out_path)
    logger.info('  %s: saved %d samples to %s', name, len(df), out_path)
    return out_path


def sweep_all(force=False):
    """Run MC sweep for all assets with frozen predictions."""
    for name in sorted(os.listdir(SANDBOX_BASE)):
        name_path = os.path.join(SANDBOX_BASE, name)
        if not os.path.isdir(name_path) or name in ('evolution', 'historical', 'sltp_analysis'):
            continue
        oos_path = os.path.join(name_path, 'oos_predictions.parquet')
        if not os.path.exists(oos_path):
            logger.info('%s: no frozen predictions at %s, skipping', name, oos_path)
            continue
        predictions = pd.read_parquet(oos_path)
        if len(predictions) < 100:
            logger.info('%s: only %d predictions, skipping', name, len(predictions))
            continue
        logger.info('Running MC sweep for %s (%d predictions, %d features)',
                    name, len(predictions), len(predictions.columns))
        try:
            sweep_one(name, predictions, force=force)
        except Exception as e:
            logger.error('%s: FAILED — %s', name, e)
            import traceback; traceback.print_exc()


if __name__ == '__main__':
    sweep_all()
