import json, os, sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE, 'data', 'live', 'state.json')
HISTORY_PATH = os.path.join(BASE, 'data', 'live', 'history.parquet')
LOG_PATH = os.path.join(BASE, 'data', 'live', 'weekly_log.csv')

# Backtest baselines for signal distribution comparison
BACKTEST_BASELINES = {
    'XLF': {'buy_pct': 35, 'sell_pct': 35, 'flat_pct': 30, 'mean_conf': 0.60},
    'BTC': {'buy_pct': 40, 'sell_pct': 30, 'flat_pct': 30, 'mean_conf': 0.55},
    'NZDJPY': {'buy_pct': 45, 'sell_pct': 25, 'flat_pct': 30, 'mean_conf': 0.55},
}


def run():
    state = load_state()
    if state is None:
        print('No state found.')
        return
    hist = load_history()

    print('\n' + '=' * 70)
    print(f'WEEKLY PORTFOLIO REPORT — {datetime.now().strftime("%Y-%m-%d")}')
    print('=' * 70)

    portfolio = state.get('portfolio', {})
    tv = portfolio.get('total_value', 0)
    tr = portfolio.get('total_return', 0)
    days = portfolio.get('days_running', 0)
    print(f'\nPortfolio: ${tv:,.2f}  Return: {tr:+.2f}%  Days: {days}')

    # Signal distribution check
    print(f'\n--- Signal Distribution Check ---')
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        sig_dist = metrics.get('signal_distribution', {})
        buy = sig_dist.get('BUY', 0)
        sell = sig_dist.get('SELL', 0)
        flat = sig_dist.get('FLAT', 0)
        total = buy + sell + flat
        buy_pct = buy / total * 100 if total > 0 else 0
        sell_pct = sell / total * 100 if total > 0 else 0
        baseline = BACKTEST_BASELINES.get(name, {})
        b_buy = baseline.get('buy_pct', 33)
        b_sell = baseline.get('sell_pct', 33)

        buy_drift = abs(buy_pct - b_buy)
        sell_drift = abs(sell_pct - b_sell)
        stable = buy_drift < 15 and sell_drift < 15

        print(f'  {name:8s}: Live B/S {buy_pct:.0f}/{sell_pct:.0f} vs BT {b_buy}/{b_sell} '
              f'→ {"STABLE" if stable else "DRIFT"} '
              f'(buy_d={buy_drift:.0f}pp sell_d={sell_drift:.0f}pp)')

    # Confidence drift check
    print(f'\n--- Confidence Trend Check ---')
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        mean_conf = metrics.get('mean_confidence', 0) / 100
        baseline_conf = BACKTEST_BASELINES.get(name, {}).get('mean_conf', 0.55)
        drift = abs(mean_conf - baseline_conf)
        print(f'  {name:8s}: Live conf={mean_conf:.2f} vs BT={baseline_conf:.2f} '
              f'→ {"STABLE" if drift < 0.15 else "DRIFT"} (d={drift:.3f})')

    # Drawdown warning
    print(f'\n--- Drawdown Status ---')
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        dd = metrics.get('drawdown', 0) / 100
        limits = {'XLF': -0.08, 'BTC': -0.15, 'NZDJPY': -0.06}
        limit = limits.get(name, -0.10)
        pct_to_halt = (dd - limit) / abs(limit) * 100 if limit < 0 else 0
        print(f'  {name:8s}: DD={dd:.2%} limit={limit:.0%} → {pct_to_halt:.0f}% of halt distance')

    # Weekly PnL
    if len(hist) > 5:
        print(f'\n--- Weekly PnL ---')
        recent = hist.tail(7)
        for _, r in recent.iterrows():
            date = r.get('date', '')
            pnl_pct = 0
            for name in ['XLF', 'BTC', 'NZDJPY']:
                pnl_pct += r.get(f'{name}_return', 0) / 3
            print(f'  {date}: avg return {pnl_pct:+.2f}%')

    # Log to CSV
    log_entry = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'portfolio_value': tv,
        'portfolio_return': tr,
        'days_running': days,
    }
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        log_entry[f'{name}_return'] = metrics.get('total_return', 0)
        log_entry[f'{name}_dd'] = metrics.get('drawdown', 0)
        log_entry[f'{name}_pf'] = metrics.get('profit_factor', 0)
        sig_dist = metrics.get('signal_distribution', {})
        log_entry[f'{name}_buy_pct'] = sig_dist.get('BUY', 0)
        log_entry[f'{name}_sell_pct'] = sig_dist.get('SELL', 0)
    log_df = pd.DataFrame([log_entry])
    if os.path.exists(LOG_PATH):
        existing = pd.read_csv(LOG_PATH)
        log_df = pd.concat([existing, log_df], ignore_index=True)
    log_df.to_csv(LOG_PATH, index=False)
    print(f'\nWeekly log saved to {LOG_PATH}')


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        return pd.read_parquet(HISTORY_PATH)
    return pd.DataFrame()


if __name__ == '__main__':
    run()
