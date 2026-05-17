import json, os, sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE, 'data', 'live', 'state.json')
HISTORY_PATH = os.path.join(BASE, 'data', 'live', 'history.parquet')
REPORT_PATH = os.path.join(BASE, 'data', 'live', 'dashboard.json')

HALT = {
    'xlf_drawdown': -0.08,
    'btc_drawdown': -0.15,
    'nzdjpy_drawdown': -0.06,
    'portfolio_dd': -0.10,
    'monthly_pf': 0.70,
    'prob_drift': 0.15,
    'signal_drought': 21,
    'correlation_spike': 0.50,
}


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        return pd.read_parquet(HISTORY_PATH)
    return pd.DataFrame()


def save_history(hist):
    hist.to_parquet(HISTORY_PATH)


def compute_pnl_correlation(hist):
    if len(hist) < 10:
        return None
    cols = [c for c in ['XLF', 'BTC', 'NZDJPY'] if c in hist.columns]
    if len(cols) < 2:
        return None
    return hist[cols].corr()


def check_halts(state, hist):
    flags = []
    assets = state.get('assets', {})
    portfolio = state.get('portfolio', {})

    # Asset-level drawdown halts
    for name, key in [('XLF', 'xlf_drawdown'), ('BTC', 'btc_drawdown'), ('NZDJPY', 'nzdjpy_drawdown')]:
        asset = assets.get(name, {})
        metrics = asset.get('metrics', {})
        dd = metrics.get('drawdown', 0) / 100
        limit = HALT[key]
        if dd <= limit:
            flags.append({'asset': name, 'type': 'drawdown',
                          f'current': round(dd, 4), 'limit': limit})
            print(f'  ⚠ HALT: {name} drawdown {dd:.1%} <= {limit:.0%}')

    # Portfolio-level drawdown
    total_value = portfolio.get('total_value', 0)
    capital = portfolio.get('capital', 100000)
    port_dd = (total_value - capital) / capital if capital > 0 else 0
    if port_dd <= HALT['portfolio_dd']:
        flags.append({'asset': 'PORTFOLIO', 'type': 'portfolio_dd',
                      'current': round(port_dd, 4), 'limit': HALT['portfolio_dd']})
        print(f'  ⚠ HALT: Portfolio DD {port_dd:.1%} <= {HALT["portfolio_dd"]:.0%}')

    # Correlation spike
    corr = compute_pnl_correlation(hist)
    if corr is not None:
        triu = corr.values[np.triu_indices_from(corr.values, k=1)]
        max_corr = max(abs(triu)) if len(triu) > 0 else 0
        if max_corr >= HALT['correlation_spike']:
            flags.append({'asset': 'PORTFOLIO', 'type': 'correlation_spike',
                          'current': round(max_corr, 3), 'limit': HALT['correlation_spike']})
            print(f'  ⚠ HALT: Portfolio PnL corr spike {max_corr:.3f} >= {HALT["correlation_spike"]:.2f}')

    # Prob drift
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = assets.get(name, {})
        metrics = asset.get('metrics', {})
        mean_conf = metrics.get('mean_confidence', 0) / 100
        expected_conf = {'XLF': 0.45, 'BTC': 0.45, 'NZDJPY': 0.45}
        drift = abs(mean_conf - expected_conf.get(name, 0.45))
        if drift > HALT['prob_drift']:
            flags.append({'asset': name, 'type': 'prob_drift',
                          'current': round(drift, 3), 'limit': HALT['prob_drift']})
            print(f'  ⚠ HALT: {name} confidence drift {drift:.3f} > {HALT["prob_drift"]:.2f}')

    # Signal drought
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = assets.get(name, {})
        metrics = asset.get('metrics', {})
        last_signal = metrics.get('last_signal_date')
        if last_signal:
            days_since = (datetime.now() - datetime.strptime(last_signal, '%Y-%m-%d')).days
            if days_since > HALT['signal_drought']:
                flags.append({'asset': name, 'type': 'signal_drought',
                              'current': days_since, 'limit': HALT['signal_drought']})
                print(f'  ⚠ HALT: {name} no signal for {days_since}d > {HALT["signal_drought"]}d')

    return flags


def print_daily(state, hist):
    print('\n' + '=' * 65)
    print(f"PAPER PORTFOLIO DASHBOARD — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print('=' * 65)

    portfolio = state.get('portfolio', {})
    tv = portfolio.get('total_value', 0)
    tr = portfolio.get('total_return', 0)
    days = portfolio.get('days_running', 0)
    print(f'\nPortfolio: ${tv:,.2f}  Return: {tr:+.2f}%  Days: {days}')
    print(f'{"Asset":>8s}  {"Signal":>7s}  {"Conf":>5s}  {"Value":>10s}  {"Ret":>7s}  '
          f'{"DD":>6s}  {"PF":>5s}  {"WinR":>5s}  {"Trades":>6s}')
    print('-' * 75)

    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        last = asset.get('last_signal', {})

        val = metrics.get('current_value', 0)
        ret = metrics.get('total_return', 0)
        dd = metrics.get('drawdown', 0)
        pf = metrics.get('profit_factor', 0)
        wr = metrics.get('win_rate', 0)
        nt = metrics.get('n_trades', 0)
        sig = last.get('signal', '-')
        conf = last.get('confidence', 0)

        sig_display = f'{sig:>4s}' if sig != '-' else ' FLAT'
        pf_str = f'{pf:.2f}' if pf is not None else ' N/A'
        wr_str = f'{wr:.1f}%' if wr is not None else ' N/A'
        print(f'{name:>8s}  {sig_display:>7s}  {conf:>4.0f}%  ${val:>8,.2f}  '
              f'{ret:>+6.2f}%  {dd:>5.1f}%  {pf_str:>5s}  {wr_str:>5s}  {nt:>6d}')

    # Halt check
    flags = check_halts(state, hist)
    if not flags:
        print(f'\n  ✅ All halt conditions clear')
    else:
        print(f'\n  ⚠ {len(flags)} halt condition(s) active')


def update_history(state):
    hist = load_history()
    today = datetime.now().strftime('%Y-%m-%d')
    row = {'date': today}
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        row[f'{name}_value'] = metrics.get('current_value', 0)
        row[f'{name}_return'] = metrics.get('total_return', 0)
        row[f'{name}_dd'] = metrics.get('drawdown', 0)
        row[f'{name}_pf'] = metrics.get('profit_factor', 0)
        last = asset.get('last_signal', {})
        row[f'{name}_signal'] = last.get('signal', 'FLAT')
        row[f'{name}_conf'] = last.get('confidence', 0)
    portfolio = state.get('portfolio', {})
    row['portfolio_value'] = portfolio.get('total_value', 0)
    row['portfolio_return'] = portfolio.get('total_return', 0)

    if today not in hist['date'].values if len(hist) > 0 else True:
        new_row = pd.DataFrame([row])
        hist = pd.concat([hist, new_row], ignore_index=True)
        save_history(hist)
    return hist


def run():
    state = load_state()
    if state is None:
        print('No state found. Run paper trading engine first.')
        return
    hist = update_history(state)
    print_daily(state, hist)
    # Save report
    report = {
        'timestamp': datetime.now().isoformat(),
        'state': state,
        'halts': check_halts(state, hist),
        'correlation': compute_pnl_correlation(hist),
        'rolling_pf': compute_rolling_pf(state),
    }
    with open(REPORT_PATH, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f'\nReport saved to {REPORT_PATH}')


def compute_rolling_pf(state):
    """30-day rolling profit factor from trade history."""
    results = {}
    for name in ['XLF', 'BTC', 'NZDJPY']:
        asset = state.get('assets', {}).get(name, {})
        metrics = asset.get('metrics', {})
        trades = metrics.get('trade_log', [])
        if len(trades) < 5:
            results[name] = None
            continue
        td = pd.DataFrame(trades[-30:])
        profits = td[td['pnl'] > 0]['pnl'].sum()
        losses = abs(td[td['pnl'] < 0]['pnl'].sum())
        results[name] = round(profits / losses, 2) if losses > 0 else None
    return results


if __name__ == '__main__':
    run()
