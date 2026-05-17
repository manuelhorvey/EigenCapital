import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
from features.pair_specific import build_nzdjpy_features

WF_CONFIG = {'train_years': 5, 'test_years': 1, 'step_years': 1, 'min_trades': 20}


def fetch_data(start='2014-01-01', end='2026-12-31'):
    df = yf.download('NZDJPY=X', start=start, end=end, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close':'close','High':'high','Low':'low','Open':'open','Volume':'volume'})
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize('Europe/London')
    return df


def load_macro():
    m = pd.read_parquet('data/processed/macro_factors.parquet')
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m = m.iloc[90:]
    return m


def run_window(X_train, y_train, X_test):
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)
    preds = model.predict(X_test)
    return proba, preds


def simulate_trades(proba, preds, prices):
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


def run_walk_forward():
    print('Fetching NZDJPY data...')
    price = fetch_data()
    print(f'Price: {len(price)} rows')
    macro = load_macro()

    print('Building NZDJPY-specific features...')
    data, features = build_nzdjpy_features(price, macro)
    print(f'Features: {features}')
    print(f'Clean data: {len(data)} rows ({data.index[0].date()} to {data.index[-1].date()})')

    years = sorted(data.index.year.unique())
    test_years = [y for y in years if y >= 2018 and y <= 2024]
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
            print(f'  {ty}: insufficient data')
            continue

        proba, preds = run_window(X_train, y_train, X_test)
        trade_rets = simulate_trades(proba, preds, price['close'].reindex(X_test.index))
        metrics = compute_metrics(trade_rets)
        metrics['year'] = str(ty)
        metrics['train_rows'] = len(X_train)
        metrics['test_rows'] = len(X_test)
        metrics['n_long'] = int((preds == 2).sum())
        metrics['n_short'] = int((preds == 0).sum())
        results.append(metrics)

        if metrics['expectancy'] is None:
            print(f'  {ty}: {metrics["n_trades"]} trades — insufficient')
        else:
            print(f'  {ty}: exp={metrics["expectancy"]:.6f}  PF={metrics["pf"]:.2f}  '
                  f'Sharpe={metrics["sharpe"]:.2f}  trades={metrics["n_trades"]}  '
                  f'L={metrics["n_long"]} S={metrics["n_short"]}')

        if metrics['expectancy'] is not None and str(ty) in ('2022', '2023', '2024'):
            tv = trade_rets[trade_rets != 0].values
            if len(tv) >= 20:
                pf_boot = []
                for _ in range(1000):
                    b = np.random.choice(tv, size=len(tv), replace=True)
                    spf = b[b>0].sum()/abs(b[b<0].sum()) if (b<0).any() else float('inf')
                    pf_boot.append(spf)
                pf_boot = np.array(pf_boot)
                p_pf = (pf_boot < 1.0).mean()
                sig = 'SIGNAL' if p_pf < 0.05 else ('BORDERLINE' if p_pf < 0.10 else 'noise')
                ci = np.percentile(pf_boot, [5, 95])
                print(f'         bootstrap p(PF<1.0)={p_pf:.3f} {sig}  CI=[{ci[0]:.2f}, {ci[1]:.2f}]')

    print('\n' + '=' * 60)
    print('WALK-FORWARD — NZDJPY (VIX + carry features)')
    print('=' * 60)
    header = f'{"Year":>6s}  {"Exp":>10s}  {"PF":>6s}  {"Sharpe":>7s}  {"Trades":>7s}  {"L/S":>6s}  {"Train":>6s}  {"Test":>5s}'
    print(header)
    print('-' * len(header))
    for r in results:
        exp_str = f'{r["expectancy"]:.6f}' if r['expectancy'] is not None else '  N/A  '
        pf_str = f'{r["pf"]:.2f}' if r['pf'] is not None else ' N/A '
        sharpe_str = f'{r["sharpe"]:.2f}' if r['sharpe'] is not None else '  N/A '
        ls = f'{r["n_long"]}/{r["n_short"]}' if r['n_long'] + r['n_short'] > 0 else '0/0'
        print(f'{r["year"]:>6s}  {exp_str:>10s}  {pf_str:>6s}  {sharpe_str:>7s}  '
              f'{r["n_trades"]:>7d}  {ls:>6s}  {r["train_rows"]:>6d}  {r["test_rows"]:>5d}')

    pos = sum(1 for r in results if r['expectancy'] is not None and r['expectancy'] > 0)
    print(f'\nPositive windows: {pos}/{len(results)}')
    if pos >= 4:
        print('>>> GATE: 4/7 positive — PASS')
    else:
        print('>>> GATE: 4/7 positive — FAIL')

    return results


if __name__ == '__main__':
    results = run_walk_forward()
