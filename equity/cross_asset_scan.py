import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
from labels.triple_barrier import apply_triple_barrier
import time
import sys
import warnings
warnings.filterwarnings('ignore')

SYMBOLS = [
    'EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X', 'USDCAD=X',
    'NZDUSD=X', 'USDCHF=X', 'EURGBP=X', 'EURJPY=X', 'GBPJPY=X',
    'AUDJPY=X', 'CHFJPY=X', 'EURCHF=X', 'EURAUD=X', 'GBPAUD=X',
    'AUDCAD=X', 'NZDJPY=X', 'EURCAD=X', 'GBPCAD=X', 'AUDNZD=X',
    'CADJPY=X', 'EURNZD=X', 'GBPNZD=X', 'GBPCHF=X', 'CADCHF=X',
    'NZDCAD=X', 'NZDCHF=X', 'AUDCHF=X',
    'GC=F', 'BTC-USD',
]

ASSET_TYPES = {
    'GC=F': 'commodity',
    'BTC-USD': 'crypto',
}

FX_FEATURES = ['mom_63', 'mom_21', 'dxy_mom_63', 'rate_diff']
COMMODITY_FEATURES = ['mom_63', 'mom_21', 'dxy_mom_63', 'real_yield_10y']
CRYPTO_FEATURES = ['mom_63', 'mom_21', 'dxy_mom_63']

WF_CONFIG = {
    'train_years': 5,
    'test_years': 1,
    'step_years': 1,
    'min_trades': 20,
}


def fetch_price_data(symbol, start='2008-01-01', end='2026-12-31'):
    try:
        df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low',
                                'Open': 'open', 'Volume': 'volume'})
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize('Europe/London')
        else:
            df.index = df.index.tz_convert('Europe/London')
        return df
    except Exception as e:
        return None


def load_macro():
    m = pd.read_parquet('data/processed/macro_factors.parquet')
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['dxy_mom_63'] = m['dxy'].pct_change(63)
    m['dxy_mom_21'] = m['dxy'].pct_change(21)
    m = m.iloc[90:]
    return m


def build_features(price_df, macro_df, asset_type):
    labeled = apply_triple_barrier(price_df, pt_sl=[2, 2], vertical_barrier=20)
    pi = labeled.index.tz_localize(None)
    a = macro_df.reindex(pi, method='ffill')
    a.index = labeled.index

    a['mom_63'] = price_df['close'].pct_change(63)
    a['mom_21'] = price_df['close'].pct_change(21)

    if asset_type == 'commodity':
        features = COMMODITY_FEATURES
    elif asset_type == 'crypto':
        features = CRYPTO_FEATURES
    else:
        features = FX_FEATURES

    available = [f for f in features if f in a.columns]
    clean = a.dropna(subset=available)
    clean['label'] = (labeled.loc[clean.index, 'label'] + 1).astype(int)
    return clean, available


def run_window(X_train, y_train, X_test):
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=-1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)
    return proba, preds


def simulate_trades(preds, prices):
    long_mask = preds == 2
    short_mask = preds == 0
    rets = prices.pct_change()
    trade_rets = pd.Series(0.0, index=prices.index)
    trade_rets[long_mask] = rets[long_mask]
    trade_rets[short_mask] = -rets[short_mask]
    return trade_rets


def compute_metrics(trade_rets):
    trades = trade_rets[trade_rets != 0]
    n_trades = len(trades)
    if n_trades < WF_CONFIG['min_trades']:
        return {'n_trades': n_trades, 'expectancy': None, 'pf': None, 'sharpe': None}
    expectancy = trades.mean()
    pf = trades[trades > 0].sum() / abs(trades[trades < 0].sum()) if (trades < 0).any() else float('inf')
    sharpe = trades.mean() / trades.std() * np.sqrt(252) if trades.std() > 0 else 0.0
    return {'n_trades': n_trades, 'expectancy': expectancy, 'pf': pf, 'sharpe': sharpe}


def test_instrument(symbol, macro_df):
    asset_type = ASSET_TYPES.get(symbol, 'fx')
    label = symbol.replace('=X', '').replace('-', '_')

    price = fetch_price_data(symbol)
    if price is None or len(price) < 500:
        return label, None, f'insufficient data ({len(price) if price is not None else 0} rows)'

    data, features = build_features(price, macro_df, asset_type)
    if len(data) < 200:
        return label, None, f'insufficient clean rows ({len(data)})'

    years = sorted(data.index.year.unique())
    test_years = [y for y in years if 2018 <= y <= 2024]

    results = []
    for ty in test_years:
        tr_end = ty - 1
        tr_start = tr_end - WF_CONFIG['train_years'] + 1

        train_mask = (data.index >= f'{tr_start}-01-01') & (data.index <= f'{tr_end}-12-31')
        test_mask = (data.index >= f'{ty}-01-01') & (data.index <= f'{ty}-12-31')

        X_train = data.loc[train_mask, features]
        y_train = data.loc[train_mask, 'label'].astype(int)
        X_test = data.loc[test_mask, features]

        if len(X_train) < 100 or len(X_test) < 50:
            continue

        proba, preds = run_window(X_train, y_train, X_test)
        trade_rets = simulate_trades(preds, price['close'].reindex(X_test.index))
        metrics = compute_metrics(trade_rets)
        metrics['year'] = str(ty)
        results.append(metrics)

    if not results:
        return label, None, 'no windows completed'

    valid = [r for r in results if r['expectancy'] is not None]
    n_pos = sum(1 for r in valid if r['expectancy'] > 0)
    n_neg = sum(1 for r in valid if r['expectancy'] < 0)
    avg_exp = np.mean([r['expectancy'] for r in valid]) if valid else None
    avg_pf = np.mean([r['pf'] for r in valid]) if valid else 0.0

    summary = {
        'results': results,
        'n_valid': len(valid),
        'n_positive': n_pos,
        'n_negative': n_neg,
        'avg_expectancy': avg_exp,
        'avg_pf': avg_pf,
        'features': features,
    }
    return label, summary, 'ok'


def print_summary(all_results):
    print('\n')
    print('=' * 120)
    print('CROSS-ASSET WALK-FORWARD SCAN — XLF Methodology')
    print('=' * 120)
    header = (f'{"Symbol":>10s}  {"Feat":>4s}  {"Win%":>5s}  {"AvgExp":>10s}  '
              f'{"AvgPF":>6s}  {"Status":>20s}')
    print(header)
    print('-' * 120)

    candidates = []
    for label, summary, status in all_results:
        if summary is None:
            print(f'{label:>10s}  {"-":>4s}  {"-":>5s}  {"-":>10s}  {"-":>6s}  {status:>20s}')
            continue

        win_pct = summary['n_positive'] / summary['n_valid'] * 100 if summary['n_valid'] > 0 else 0
        avg_exp = f'{summary["avg_expectancy"]:.6f}' if summary['avg_expectancy'] is not None else 'N/A'
        avg_pf = f'{summary["avg_pf"]:.2f}' if summary['avg_pf'] is not None else 'N/A'
        n_feat = len(summary['features'])

        status_str = f'{summary["n_positive"]}/{summary["n_valid"]} pos, {n_feat}f'
        print(f'{label:>10s}  {str(n_feat):>4s}  {win_pct:>5.0f}%  {avg_exp:>10s}  {avg_pf:>6s}  {status_str:>20s}')

        if summary['n_valid'] >= 4 and summary['avg_pf'] is not None and summary['avg_pf'] > 1.05:
            candidates.append((label, summary))

    print('-' * 120)
    print(f'\nCANDIDATES WITH AVG PF > 1.05 (>=4 valid windows):')
    if candidates:
        for label, s in sorted(candidates, key=lambda x: x[1]['avg_pf'], reverse=True):
            print(f'  {label:>10s}  PF={s["avg_pf"]:.3f}  Exp={s["avg_expectancy"]:.6f}  '
                  f'{s["n_positive"]}/{s["n_valid"]} positive')
    else:
        print('  None found.')

    return candidates


def main():
    print('Loading macro data...')
    macro_df = load_macro()
    print(f'Macro: {macro_df.index[0].date()} to {macro_df.index[-1].date()} ({len(macro_df)} days)')

    all_results = []
    for i, symbol in enumerate(SYMBOLS):
        t0 = time.time()
        label, summary, status = test_instrument(symbol, macro_df)
        elapsed = time.time() - t0
        sys.stdout.write(f'  [{i+1:>2d}/{len(SYMBOLS)}] {symbol:>10s} -> {status} ({elapsed:.1f}s)\n')
        sys.stdout.flush()
        all_results.append((label, summary, status))

    candidates = print_summary(all_results)

    if candidates:
        print('\n' + '=' * 120)
        print('DETAILED RESULTS: PROMISING CANDIDATES')
        print('=' * 120)
        for label, s in sorted(candidates, key=lambda x: x[1]['avg_pf'], reverse=True):
            print(f'\n--- {label} (avg PF={s["avg_pf"]:.3f}, exp={s["avg_expectancy"]:.6f}) ---')
            print(f'  Features: {s["features"]}')
            print(f'  {"Year":>6s}  {"Exp":>10s}  {"PF":>6s}  {"Sharpe":>7s}  {"Trades":>7s}  {"L/S":>6s}')
            for r in s['results']:
                exp_str = f'{r["expectancy"]:.6f}' if r['expectancy'] is not None else '  N/A  '
                pf_str = f'{r["pf"]:.2f}' if r['pf'] is not None else ' N/A '
                sharpe_str = f'{r["sharpe"]:.2f}' if r['sharpe'] is not None else '  N/A  '
                ls_left = r.get('n_long', 0)
                ls_right = r.get('n_short', 0)
                ls = f'{ls_left}/{ls_right}' if 'n_long' in r else '-'
                print(f'  {r["year"]:>6s}  {exp_str:>10s}  {pf_str:>6s}  {sharpe_str:>7s}  '
                      f'{r["n_trades"]:>7d}  {ls:>6s}')

    print('\nDone.')


if __name__ == '__main__':
    main()
