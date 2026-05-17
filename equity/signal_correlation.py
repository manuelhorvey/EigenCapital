import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
from labels.triple_barrier import apply_triple_barrier
from features.pair_specific import build_nzdjpy_features

WF_CONFIG = {'train_years': 5, 'test_years': 1, 'step_years': 1, 'min_trades': 20}


def yf_get(symbol, start='2014-01-01', end='2026-12-31', tz='Europe/London'):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close': 'close', 'High': 'high',
                            'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    return df


def load_macro():
    m = pd.read_parquet('data/processed/macro_factors.parquet')
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m = m.iloc[90:]
    return m


def run_model(X_train, y_train, X_test):
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)
    return model.predict(X_test)


def eurusd_signal(close, macro):
    m = macro.reindex(pd.date_range(macro.index.min(), macro.index.max(), freq='D')).ffill()
    labeled = apply_triple_barrier(close.to_frame(name='close').assign(
        high=close*1.01, low=close*0.99, open=close, volume=1),
        pt_sl=[2, 2], vertical_barrier=20)
    idx = labeled.index
    a = m.reindex(idx.tz_localize(None) if hasattr(idx, 'tz') and idx.tz is not None else idx, method='ffill')
    a.index = idx
    a['dxy_mom_21'] = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()['dxy'].pct_change(21).reindex(a.index)
    a['rate_diff'] = a['fed_funds'] - a['ecb_rate']
    a['dxy_lag1'] = a['dxy'].pct_change(1).shift(1)
    gc = yf_get('GC=F')
    gc_idx = gc.index.tz_localize(None) if hasattr(gc.index, 'tz') and gc.index.tz is not None else gc.index
    gc_ret = gc['close'].pct_change()
    a_idx_naive = idx.tz_localize(None) if hasattr(idx, 'tz') and idx.tz is not None else idx
    a['gc_lag1'] = gc_ret.shift(1).reindex(a_idx_naive, method='ffill').values
    features = ['dxy_mom_21', 'rate_diff', 'dxy_lag1', 'gc_lag1']
    clean = a.dropna(subset=features).copy()
    clean['label'] = (labeled.loc[clean.index, 'label'] + 1).astype(int)
    return clean, features


def generate_signals(asset_name):
    print(f'Generating signals: {asset_name}')

    if asset_name == 'XLF':
        price = yf_get('XLF')
        spy = yf_get('SPY')
        m = load_macro()
        m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
        m['2y_yield_delta_63'] = m['us_2y'].diff(63)
        labeled = apply_triple_barrier(price, pt_sl=[2, 2], vertical_barrier=20)
        idx = labeled.index
        a = m.reindex(idx.tz_localize(None) if hasattr(idx, 'tz') and idx.tz is not None else idx, method='ffill')
        a.index = idx
        a['xlf_mom_63'] = price['close'].pct_change(63)
        a['xlf_vs_spy_63'] = a['xlf_mom_63'] - spy['close'].pct_change(63)
        features = ['rate_diff', '2y_yield_delta_63', 'xlf_mom_63', 'xlf_vs_spy_63']
        clean = a.dropna(subset=features).copy()
        clean['label'] = (labeled.loc[clean.index, 'label'] + 1).astype(int)

    elif asset_name == 'BTC-USD':
        price = yf_get('BTC-USD')
        spy = yf_get('SPY')
        m = load_macro()
        labeled = apply_triple_barrier(price, pt_sl=[2, 2], vertical_barrier=20)
        idx = labeled.index
        a = m.reindex(idx.tz_localize(None) if hasattr(idx, 'tz') and idx.tz is not None else idx, method='ffill')
        a.index = idx
        a['mom_63'] = price['close'].pct_change(63)
        a['mom_21'] = price['close'].pct_change(21)
        a['dxy_mom_63'] = a['dxy'].pct_change(63)
        features = ['mom_63', 'mom_21', 'dxy_mom_63']
        clean = a.dropna(subset=features).copy()
        clean['label'] = (labeled.loc[clean.index, 'label'] + 1).astype(int)

    elif asset_name == 'NZDJPY':
        price = yf_get('NZDJPY=X')
        macro = load_macro()
        clean, features = build_nzdjpy_features(price, macro)

    else:
        raise ValueError(f'Unknown asset: {asset_name}')

    years = sorted(clean.index.year.unique())
    test_years = [y for y in years if y >= 2018 and y <= 2024]
    all_signals = pd.Series(dtype=float)

    for ty in test_years:
        tr_end = ty - 1
        tr_start = tr_end - WF_CONFIG['train_years'] + 1
        train = clean[(clean.index >= f'{tr_start}-01-01') & (clean.index <= f'{tr_end}-12-31')]
        test = clean[(clean.index >= f'{ty}-01-01') & (clean.index <= f'{ty}-12-31')]
        if len(train) < 100 or len(test) < 50:
            continue
        preds = run_model(train[features], train['label'].astype(int), test[features])
        signal = pd.Series(0, index=test.index)
        signal[preds == 2] = 1
        signal[preds == 0] = -1
        all_signals = pd.concat([all_signals, signal])

    return all_signals.sort_index()


def compute_metrics(asset_signals, price_rets):
    """Return daily PnL series for an asset given its signals."""
    common = asset_signals.index.intersection(price_rets.index)
    s = asset_signals.reindex(common)
    r = price_rets.reindex(common)
    pnl = s * r
    return pnl


def main():
    print('=' * 60)
    print('SIGNAL CORRELATION ANALYSIS — Portfolio Diversification')
    print('=' * 60)

    assets = ['XLF', 'BTC-USD', 'NZDJPY']
    price_data = {}
    for a in assets:
        ticker = a if a != 'NZDJPY' else 'NZDJPY=X'
        df = yf_get(ticker)
        rets = df['close'].pct_change().dropna()
        rets.index = rets.index.tz_localize(None) if hasattr(rets.index, 'tz') and rets.index.tz is not None else rets.index
        price_data[a] = rets

    all_signals = {}
    for a in assets:
        sigs = generate_signals(a)
        sigs.index = sigs.index.tz_localize(None) if hasattr(sigs.index, 'tz') and sigs.index.tz is not None else sigs.index
        all_signals[a] = sigs

    # Build daily signal matrix
    signal_df = pd.DataFrame(all_signals).dropna()
    signal_df.columns = ['XLF', 'BTC', 'NZDJPY']
    signal_df = signal_df.replace(0, np.nan).dropna(how='all')

    print(f'\nSignal date range: {signal_df.index[0].date()} to {signal_df.index[-1].date()}')
    print(f'Total days with signals: {len(signal_df)}')

    # Correlation matrix
    corr = signal_df.corr()
    print(f'\n--- Signal correlation matrix ---')
    print(corr.to_string(float_format=lambda x: f'{x:+.3f}'))

    # Yearly breakdown
    print(f'\n--- Yearly signal correlations ---')
    years = sorted(signal_df.index.year.unique())
    for y in years:
        ydata = signal_df[signal_df.index.year == y]
        if len(ydata) < 20:
            continue
        ycorr = ydata.corr()
        print(f'  {y}: XLF/BTC={ycorr.loc["XLF","BTC"]:+.3f}  '
              f'XLF/NZD={ycorr.loc["XLF","NZDJPY"]:+.3f}  '
              f'BTC/NZD={ycorr.loc["BTC","NZDJPY"]:+.3f}  n={len(ydata)}')

    # 2022 specific: did all three go short simultaneously?
    print(f'\n--- 2022: Simultaneous short check ---')
    y2022 = signal_df[signal_df.index.year == 2022]
    all_short = ((y2022['XLF'] < 0) & (y2022['BTC'] < 0) & (y2022['NZDJPY'] < 0)).sum()
    any_short = ((y2022['XLF'] < 0) | (y2022['BTC'] < 0) | (y2022['NZDJPY'] < 0)).sum()
    total = len(y2022)
    print(f'  Days all three short:  {all_short}/{total} ({all_short/total*100:.1f}%)')
    print(f'  Days any short:        {any_short}/{total} ({any_short/total*100:.1f}%)')
    print(f'  XLF short days:        {(y2022["XLF"] < 0).sum()}')
    print(f'  BTC short days:        {(y2022["BTC"] < 0).sum()}')
    print(f'  NZDJPY short days:     {(y2022["NZDJPY"] < 0).sum()}')

    # Portfolio PnL analysis
    print(f'\n--- Combined portfolio PnL (equal signal weight) ---')
    col_map = {'XLF': 'XLF', 'BTC-USD': 'BTC', 'NZDJPY': 'NZDJPY'}
    pnl_data = {}
    for a in assets:
        col = col_map[a]
        r = price_data[a].reindex(signal_df.index)
        pnl_data[col] = signal_df[col] * r
    pnl_df = pd.DataFrame(pnl_data).dropna()

    for a in ['XLF', 'BTC', 'NZDJPY']:
        trades = pnl_df[a][pnl_df[a] != 0]
        exp = trades.mean()
        pf = trades[trades > 0].sum() / abs(trades[trades < 0].sum()) if (trades < 0).any() else float('inf')
        sharpe = trades.mean() / trades.std() * np.sqrt(252) if trades.std() > 0 else 0.0
        print(f'  {a:8s}: exp={exp:+.6f}  PF={pf:.2f}  Sharpe={sharpe:.2f}  trades={len(trades)}')

    combined_pnl = pnl_df.sum(axis=1)
    trades_c = combined_pnl[combined_pnl != 0]
    exp_c = trades_c.mean()
    pf_c = trades_c[trades_c > 0].sum() / abs(trades_c[trades_c < 0].sum()) if (trades_c < 0).any() else float('inf')
    sharpe_c = trades_c.mean() / trades_c.std() * np.sqrt(252) if trades_c.std() > 0 else 0.0
    print(f'  {"Combined":8s}: exp={exp_c:+.6f}  PF={pf_c:.2f}  Sharpe={sharpe_c:.2f}  trades={len(trades_c)}')

    # PnL correlation
    pnl_corr = pnl_df.corr()
    print(f'\n--- PnL correlation matrix (daily) ---')
    print(pnl_corr.to_string(float_format=lambda x: f'{x:+.3f}'))

    print(f'\n--- Assessment ---')
    max_corr = max(abs(pnl_corr.values[np.triu_indices_from(pnl_corr.values, k=1)]))
    if max_corr < 0.30:
        print(f'  GENUINE DIVERSIFICATION: max PnL correlation = {max_corr:.3f} (< 0.30)')
    elif max_corr < 0.50:
        print(f'  MODERATE DIVERSIFICATION: max PnL correlation = {max_corr:.3f}')
    else:
        print(f'  WARNING: High correlation = {max_corr:.3f} — same bet, different tickers')


if __name__ == '__main__':
    main()
