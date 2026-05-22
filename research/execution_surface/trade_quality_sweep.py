"""Phase H.1 — Trade Outcome Quality Surface Sweep.

Goal: Find (sl_mult, tp_mult) geometries that maximize TP% and minimize SL%,
rather than maximizing Sharpe/PF alone.

Sweeps a focused region around the current plateau-center configs and reports
the trade-off frontier between (TP% - SL%) and Sharpe.

Output: data/sandbox/trade_quality_sweep.json
"""

import os, sys, json, logging
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from research.execution_surface.replay_engine import replay, ReplayConfig
from research.execution_surface.monte_carlo import compute_trade_metrics, MIN_TRADES

logger = logging.getLogger("quantforge.execution_surface.trade_quality")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SANDBOX_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            'data', 'sandbox')

# Tight target region where geometry changes most affect TP%/SL%
SL_RANGE = (0.30, 1.20)
TP_RANGE = (0.50, 2.50)
SL_STEP = 0.05
TP_STEP = 0.10

# Assets to sweep (calibrated assets + key ones)
TARGET_ASSETS = ['AUDJPY', 'CADJPY', 'EURAUD', 'NZDJPY', 'USDCAD', 'USDJPY',
                 'GBPUSD', 'EURCAD', 'CHFJPY', 'GBPJPY', 'USDCHF', 'GC', 'DJI']


def load_plateau_configs() -> dict:
    """Load current plateau-center configs from aggregate_report.json."""
    report_path = os.path.join(SANDBOX_BASE, 'sltp_analysis', 'aggregate_report.json')
    if not os.path.exists(report_path):
        logger.warning('No aggregate report at %s', report_path)
        return {}
    with open(report_path) as f:
        report = json.load(f)
    configs = {}
    for name, r in report.items():
        if 'error' in r:
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
    return configs


def sweep_asset(name: str, predictions: pd.DataFrame) -> list:
    """Sweep a focused (sl, tp) grid for one asset, collecting outcome metrics."""
    sl_vals = np.arange(SL_RANGE[0], SL_RANGE[1] + SL_STEP, SL_STEP)
    tp_vals = np.arange(TP_RANGE[0], TP_RANGE[1] + TP_STEP, TP_STEP)

    results = []
    total = len(sl_vals) * len(tp_vals)
    count = 0

    for sl in sl_vals:
        for tp in tp_vals:
            count += 1
            if count % 50 == 0:
                logger.info('  %s: %d/%d', name, count, total)

            config = ReplayConfig(sl_mult=round(float(sl), 4), tp_mult=round(float(tp), 4))
            trades = replay(predictions, config)
            metrics = compute_trade_metrics(trades, round(float(sl), 4), round(float(tp), 4))

            # Add composite quality score
            if metrics.get('valid'):
                tp_rate = metrics.get('tp_hit_freq', 0)
                sl_rate = metrics.get('stop_hit_freq', 0)
                metrics['tp_minus_sl'] = round(tp_rate - sl_rate, 4)
                metrics['trade_quality_score'] = round(
                    tp_rate - sl_rate + metrics.get('sharpe', 0) * 0.1, 4
                )
            results.append(metrics)

    return results


def find_best_by_metric(results: list, metric: str = 'tp_minus_sl') -> dict:
    """Find the config with the highest value for a given metric."""
    valid = [r for r in results if r.get('valid') and r.get(metric) is not None]
    if not valid:
        return {}
    best = max(valid, key=lambda r: r[metric])
    return {
        'sl_mult': best['sl_mult'],
        'tp_mult': best['tp_mult'],
        metric: best[metric],
        'sharpe': best.get('sharpe', 0),
        'tp_rate': best.get('tp_hit_freq', 0),
        'sl_rate': best.get('stop_hit_freq', 0),
        'flip_rate': best.get('flip_freq', 0),
        'n_trades': best.get('n_trades', 0),
    }


def run():
    """Run trade quality sweep for all target assets."""
    plateau_configs = load_plateau_configs()
    logger.info('Loaded %d plateau configs', len(plateau_configs))

    report = {}

    for name in TARGET_ASSETS:
        oos_path = os.path.join(SANDBOX_BASE, name, 'oos_predictions.parquet')
        if not os.path.exists(oos_path):
            logger.warning('%s: no predictions at %s, skipping', name, oos_path)
            continue

        logger.info('=' * 60)
        logger.info('Sweeping %s...', name)
        logger.info('=' * 60)

        predictions = pd.read_parquet(oos_path)
        results = sweep_asset(name, predictions)

        # Find best by different metrics
        best_tp_minus_sl = find_best_by_metric(results, 'tp_minus_sl')
        best_sharpe = find_best_by_metric(results, 'sharpe')
        best_tp_rate = find_best_by_metric(results, 'tp_hit_freq')
        lowest_sl = find_best_by_metric(results, 'stop_hit_freq')
        # lowest SL = maximize negative SL rate
        valid_sl = [r for r in results if r.get('valid') and r.get('stop_hit_freq') is not None]
        if valid_sl:
            lowest_sl_raw = min(valid_sl, key=lambda r: r['stop_hit_freq'])
            lowest_sl = {
                'sl_mult': lowest_sl_raw['sl_mult'],
                'tp_mult': lowest_sl_raw['tp_mult'],
                'stop_hit_freq': lowest_sl_raw['stop_hit_freq'],
                'sharpe': lowest_sl_raw.get('sharpe', 0),
                'tp_rate': lowest_sl_raw.get('tp_hit_freq', 0),
                'sl_rate': lowest_sl_raw.get('stop_hit_freq', 0),
                'n_trades': lowest_sl_raw.get('n_trades', 0),
            }

        # Current plateau config metrics (nearest neighbor)
        plateau_cfg = plateau_configs.get(name, {})
        current_metrics = None
        if plateau_cfg:
            p_sl = plateau_cfg['sl_mult']
            p_tp = plateau_cfg['tp_mult']
            for r in results:
                if abs(r['sl_mult'] - p_sl) < 0.01 and abs(r['tp_mult'] - p_tp) < 0.01:
                    current_metrics = r
                    break
            if current_metrics is None:
                # nearest neighbor
                dists = [((r['sl_mult'] - p_sl)**2 + (r['tp_mult'] - p_tp)**2)**0.5 for r in results]
                nearest_idx = int(np.argmin(dists))
                current_metrics = results[nearest_idx]
                logger.info('  Current config (sl=%.2f, tp=%.2f) — nearest neighbor at dist=%.4f',
                            p_sl, p_tp, dists[nearest_idx])

        asset_result = {
            'n_configs_tested': len(results),
            'n_valid': len([r for r in results if r.get('valid')]),
            'plateau_config': plateau_cfg,
            'current_metrics': current_metrics,
            'best_by_tp_minus_sl': best_tp_minus_sl,
            'best_by_sharpe': best_sharpe,
            'best_by_tp_rate': best_tp_rate,
            'lowest_sl': lowest_sl,
        }
        report[name] = asset_result

        # Print per-asset summary
        print(f'\n{name}:')
        print(f'  Config                    SL    TP   TP%-SL%  Sharpe  TP%    SL%    Flip%  Trades')

        if current_metrics:
            print(f'  Current (plateau)      {current_metrics["sl_mult"]:.2f}  {current_metrics["tp_mult"]:.2f}  '
                  f'{current_metrics.get("tp_hit_freq", 0)-current_metrics.get("stop_hit_freq", 0):+.3f}  '
                  f'{current_metrics.get("sharpe", 0):.2f}  '
                  f'{current_metrics.get("tp_hit_freq", 0)*100:.0f}%  {current_metrics.get("stop_hit_freq", 0)*100:.0f}%  '
                  f'{current_metrics.get("flip_freq", 0)*100:.0f}%  {current_metrics.get("n_trades", 0)}')

        if best_tp_minus_sl:
            print(f'  Best TP%-SL%           {best_tp_minus_sl["sl_mult"]:.2f}  {best_tp_minus_sl["tp_mult"]:.2f}  '
                  f'{best_tp_minus_sl.get("tp_minus_sl", 0):+.3f}  '
                  f'{best_tp_minus_sl.get("sharpe", 0):.2f}  '
                  f'{best_tp_minus_sl.get("tp_rate", 0)*100:.0f}%  {best_tp_minus_sl.get("sl_rate", 0)*100:.0f}%  '
                  f'{best_tp_minus_sl.get("flip_rate", 0)*100:.0f}%  {best_tp_minus_sl.get("n_trades", 0)}')

        if best_sharpe and best_sharpe.get('sl_mult') != best_tp_minus_sl.get('sl_mult'):
            print(f'  Best Sharpe             {best_sharpe["sl_mult"]:.2f}  {best_sharpe["tp_mult"]:.2f}  '
                  f'{"N/A":>7s}  '
                  f'{best_sharpe.get("sharpe", 0):.2f}  '
                  f'{best_sharpe.get("tp_rate", 0)*100:.0f}%  {best_sharpe.get("sl_rate", 0)*100:.0f}%  '
                  f'{best_sharpe.get("flip_rate", 0)*100:.0f}%  {best_sharpe.get("n_trades", 0)}')

        if lowest_sl and lowest_sl.get('sl_mult') not in (
            best_tp_minus_sl.get('sl_mult'), best_sharpe.get('sl_mult')):
            print(f'  Lowest SL%              {lowest_sl["sl_mult"]:.2f}  {lowest_sl["tp_mult"]:.2f}  '
                  f'{"N/A":>7s}  '
                  f'{lowest_sl.get("sharpe", 0):.2f}  '
                  f'{lowest_sl.get("tp_rate", 0)*100:.0f}%  {lowest_sl.get("sl_rate", 0)*100:.0f}%  '
                  f'{"N/A":>6s}  {lowest_sl.get("n_trades", 0)}')

    # Save
    out_path = os.path.join(SANDBOX_BASE, 'trade_quality_sweep.json')
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    logger.info('Saved trade quality sweep to %s', out_path)

    # Cross-asset summary table
    print('\n' + '=' * 120)
    print('TRADE QUALITY SWEEP — CROSS-ASSET COMPARISON')
    print('=' * 120)
    hdr = '  {:>10s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}  {:>6s}'
    print(hdr.format('Asset', 'CurSL', 'CurTP', 'CurTP%', 'CurSL%',
                      'BestSL', 'BestTP', 'BestTP%', 'BestSL%'))
    print('  ' + '-' * 90)
    for name in sorted(report.keys()):
        r = report[name]
        cm = r.get('current_metrics', {}) or {}
        bt = r.get('best_by_tp_minus_sl', {}) or {}
        if not cm and not bt:
            continue
        print(hdr.format(
            name,
            f'{cm.get("sl_mult", 0):.2f}',
            f'{cm.get("tp_mult", 0):.2f}',
            f'{cm.get("tp_hit_freq", 0)*100:.0f}%',
            f'{cm.get("stop_hit_freq", 0)*100:.0f}%',
            f'{bt.get("sl_mult", 0):.2f}',
            f'{bt.get("tp_mult", 0):.2f}',
            f'{bt.get("tp_rate", 0)*100:.0f}%',
            f'{bt.get("sl_rate", 0)*100:.0f}%',
        ))
    print('=' * 120)

    return report


if __name__ == '__main__':
    run()
