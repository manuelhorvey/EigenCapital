import pandas as pd
import numpy as np
import yfinance as yf
import sys

DRIVERS = [
    'fed_funds', 'ecb_rate', 'rate_diff', 'rate_diff_delta_3m',
    'us_2y', 'us_10y', 'yield_slope', 'breakeven_10y',
    'real_yield_10y', 'dxy', 'dxy_mom_21', 'dxy_mom_63',
    'fed_funds_delta_3m', 'vix', 'baa_spread',
    'jp_10y', 'de_10y', 'gb_10y', 'ca_10y', 'au_10y',
]


def load_asset(symbol, start='2014-01-01', end='2026-12-31'):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close': 'close', 'High': 'high',
                            'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
    df.index = pd.to_datetime(df.index)
    return df


def load_macro():
    m = pd.read_parquet('data/processed/macro_factors.parquet')
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['yield_slope'] = m['us_10y'] - m['us_2y']
    m['dxy_mom_21'] = m['dxy'].pct_change(21, fill_method=None)
    m['dxy_mom_63'] = m['dxy'].pct_change(63, fill_method=None)
    m['fed_funds_delta_3m'] = m['fed_funds'].diff(90)
    m['rate_diff_delta_3m'] = m['rate_diff'].diff(90)
    m = m.iloc[90:]
    return m


def phase1_rolling_corr(asset_returns, macro_df, window=90):
    print('\n--- PHASE 1: Rolling 90-day correlation with candidate drivers ---')
    results = []
    for driver in DRIVERS:
        if driver not in macro_df.columns:
            continue
        joint = pd.concat([asset_returns.rename('ret'),
                           macro_df[driver].rename('driver')], axis=1).dropna()
        if len(joint) < window:
            continue
        roll_corr = joint['ret'].rolling(window).corr(joint['driver']).dropna()
        if len(roll_corr) < 10:
            continue
        results.append({
            'driver': driver,
            'mean_corr': roll_corr.mean(),
            'std_corr': roll_corr.std(),
            'abs_mean': abs(roll_corr.mean()),
            'stability': abs(roll_corr.mean()) / roll_corr.std() if roll_corr.std() > 0 else 0,
            'pct_positive': (roll_corr > 0).mean(),
            'last_corr': roll_corr.iloc[-1],
        })
    df = pd.DataFrame(results)
    df = df.sort_values('stability', ascending=False)
    print(f'{"Driver":>20s}  {"MeanCorr":>8s}  {"Std":>6s}  {"Stability":>9s}  {"%Pos":>5s}  {"Last":>6s}')
    print('-' * 65)
    for _, r in df.head(10).iterrows():
        print(f'{r["driver"]:>20s}  {r["mean_corr"]:>+8.3f}  {r["std_corr"]:>6.3f}  '
              f'{r["stability"]:>9.3f}  {r["pct_positive"]:>5.0%}  {r["last_corr"]:>+6.3f}')
    return df


def phase2_asymmetry(asset_returns, macro_df, top_n=5):
    print('\n--- PHASE 2: Bull/Bear correlation asymmetry ---')
    bull = asset_returns[asset_returns > 0]
    bear = asset_returns[asset_returns < 0]
    results = []
    for driver in DRIVERS:
        if driver not in macro_df.columns:
            continue
        joint = pd.concat([asset_returns.rename('ret'),
                           macro_df[driver].rename('driver')], axis=1).dropna()
        if len(joint) < 50:
            continue
        bull_corr = joint.loc[bull.index].corr().loc['ret', 'driver'] if len(bull) > 10 else 0
        bear_corr = joint.loc[bear.index].corr().loc['ret', 'driver'] if len(bear) > 10 else 0
        diff = abs(bull_corr - bear_corr)
        results.append({
            'driver': driver,
            'bull_corr': bull_corr,
            'bear_corr': bear_corr,
            'asymmetry': diff,
        })
    df = pd.DataFrame(results)
    df = df.sort_values('asymmetry', ascending=False)
    print(f'{"Driver":>20s}  {"BullCorr":>8s}  {"BearCorr":>8s}  {"Asymmetry":>9s}')
    print('-' * 55)
    for _, r in df.head(top_n).iterrows():
        print(f'{r["driver"]:>20s}  {r["bull_corr"]:>+8.3f}  {r["bear_corr"]:>+8.3f}  {r["asymmetry"]:>9.3f}')
    return df


def phase3_optimal_lag(asset_returns, macro_df, top_n=3):
    print('\n--- PHASE 3: Optimal lookback lag ---')
    lags = [5, 10, 21, 42, 63, 126]
    results = []
    for driver in DRIVERS:
        if driver not in macro_df.columns:
            continue
        best_lag = None
        best_corr = 0
        for lag in lags:
            joint = pd.concat([asset_returns.rename('ret'),
                               macro_df[driver].shift(lag).rename('driver')], axis=1).dropna()
            if len(joint) < 50:
                continue
            c = joint['ret'].corr(joint['driver'])
            if abs(c) > abs(best_corr):
                best_corr = c
                best_lag = lag
        if best_lag is not None and abs(best_corr) > 0.03:
            results.append({
                'driver': driver,
                'best_lag': best_lag,
                'corr_at_lag': best_corr,
            })
    df = pd.DataFrame(results)
    if len(df) == 0:
        print('  No drivers with abs(corr) > 0.03 at any lag tested.')
        return df
    df = df.sort_values('corr_at_lag', key=abs, ascending=False)
    print(f'{"Driver":>20s}  {"BestLag":>7s}  {"Corr":>6s}')
    print('-' * 40)
    for _, r in df.head(top_n).iterrows():
        print(f'{r["driver"]:>20s}  {r["best_lag"]:>7d}  {r["corr_at_lag"]:>+6.3f}')
    return df


def run_analysis(symbol, name=None):
    if name is None:
        name = symbol
    print('\n' + '=' * 70)
    print(f'DRIVER ANALYSIS: {name} ({symbol})')
    print('=' * 70)
    price = load_asset(symbol)
    print(f'Data: {len(price)} rows from {price.index[0].date()} to {price.index[-1].date()}')
    rets = price['close'].pct_change().dropna()
    macro = load_macro()

    pi = rets.index.tz_localize(None) if hasattr(rets.index, 'tz') and rets.index.tz is not None else rets.index
    macro_aligned = macro.reindex(pi, method='ffill')
    macro_aligned.index = rets.index

    p1 = phase1_rolling_corr(rets, macro_aligned)
    p2 = phase2_asymmetry(rets, macro_aligned)
    p3 = phase3_optimal_lag(rets, macro_aligned)

    print('\n--- PRIMARY DRIVER SUMMARY ---')
    top_driver = p1.iloc[0]['driver'] if len(p1) > 0 else 'N/A'
    top_stable = p1.iloc[0]['stability'] if len(p1) > 0 else 0
    print(f'  Most stable driver: {top_driver} (stability={top_stable:.3f})')
    asym_row = p2[p2['driver'] == top_driver]
    if len(asym_row) > 0:
        asym = asym_row.iloc[0]['asymmetry']
        print(f'  Bull/bear asymmetry: {asym:.3f} {"(asymmetric)" if asym > 0.10 else "(symmetric)"}')
    lag_row = p3[p3['driver'] == top_driver]
    if len(lag_row) > 0:
        print(f'  Optimal lookback: {lag_row.iloc[0]["best_lag"]} days')

    return {'p1': p1, 'p2': p2, 'p3': p3}


if __name__ == '__main__':
    targets = [
        ('NZDJPY=X', 'NZDJPY'),
        ('EURUSD=X', 'EURUSD'),
        ('USDJPY=X', 'USDJPY'),
        ('GC=F', 'GC=F'),
    ]
    results = {}
    for symbol, name in targets:
        results[name] = run_analysis(symbol, name)
