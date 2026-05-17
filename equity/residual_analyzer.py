import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
from features.pair_specific import build_eurusd_features


def load_asset(symbol, start='2014-01-01', end='2026-12-31'):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close': 'close', 'High': 'high',
                            'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
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


def train_model(data, features, train_end=2021):
    train = data[data.index.year <= train_end]
    test = data[data.index.year > train_end]
    if len(train) < 100 or len(test) < 50:
        return None, None, None, None
    X_train = train[features]
    y_train = train['label'].astype(int)
    X_test = test[features]
    y_test = test['label'].astype(int)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)
    return model, X_test, y_test, preds


CANDIDATE_MISSING_DRIVERS = [
    'vix', 'vix_lag1', 'vix_lag5', 'vix_lag21',
    'dxy', 'dxy_lag1', 'dxy_lag5',
    'baa_spread', 'baa_spread_lag5',
    'us_10y_delta_5', 'us_2y_delta_5',
    'yield_slope', 'yield_slope_delta_5',
    'breakeven_10y', 'breakeven_delta_5',
    'real_yield_10y', 'real_yield_delta_5',
    'de_10y', 'gb_10y', 'jp_10y',
    'rate_diff', 'rate_diff_delta_3m',
    'fed_funds_delta_3m',
]


def build_missing_drivers(macro_aligned, price_ret):
    """Construct candidate missing drivers from available macro + prices."""
    drivers = pd.DataFrame(index=macro_aligned.index)

    # Level and lagged VIX
    drivers['vix'] = macro_aligned['vix']
    drivers['vix_lag1'] = macro_aligned['vix'].shift(1)
    drivers['vix_lag5'] = macro_aligned['vix'].shift(5)
    drivers['vix_lag21'] = macro_aligned['vix'].shift(21)
    drivers['vix_ma21'] = macro_aligned['vix'].rolling(21).mean()

    # DXY
    drivers['dxy'] = macro_aligned['dxy'].pct_change(1)
    drivers['dxy_lag1'] = macro_aligned['dxy'].pct_change(1).shift(1)
    drivers['dxy_lag5'] = macro_aligned['dxy'].pct_change(5).shift(1)

    # Credit stress
    drivers['baa_spread'] = macro_aligned['baa_spread']
    drivers['baa_spread_lag5'] = macro_aligned['baa_spread'].shift(5)

    # Yield changes
    drivers['us_10y_delta_5'] = macro_aligned['us_10y'].diff(5)
    drivers['us_2y_delta_5'] = macro_aligned['us_2y'].diff(5)
    drivers['yield_slope'] = macro_aligned['us_10y'] - macro_aligned['us_2y']
    drivers['yield_slope_delta_5'] = drivers['yield_slope'].diff(5)

    # Breakevens / real yields
    drivers['breakeven_10y'] = macro_aligned['breakeven_10y']
    drivers['breakeven_delta_5'] = macro_aligned['breakeven_10y'].diff(5)
    drivers['real_yield_10y'] = macro_aligned['real_yield_10y']
    drivers['real_yield_delta_5'] = macro_aligned['real_yield_10y'].diff(5)

    # Bilateral yields
    drivers['de_10y'] = macro_aligned['de_10y']
    drivers['gb_10y'] = macro_aligned['gb_10y']
    drivers['jp_10y'] = macro_aligned['jp_10y']

    # Rate differentials
    drivers['rate_diff'] = macro_aligned['rate_diff']
    drivers['rate_diff_delta_3m'] = macro_aligned['rate_diff'].diff(90)

    # Cross-asset momentum (lagged)
    drivers['gc_mom_5'] = price_ret.reindex(drivers.index, method='ffill') if price_ret is not None else np.nan

    return drivers


def analyze_residuals(asset_symbol='EURUSD=X', train_until=2021, test_from=2022):
    print('Loading data...')
    price = load_asset(asset_symbol)
    macro = load_macro()
    rets = price['close'].pct_change().dropna()

    from features.pair_specific import apply_triple_barrier_caller
    from labels.triple_barrier import apply_triple_barrier
    labeled = apply_triple_barrier(price, pt_sl=[2, 2], vertical_barrier=20)
    pi = labeled.index.tz_localize(None) if hasattr(labeled.index, 'tz') and labeled.index.tz is not None else labeled.index
    macro_aligned = macro.reindex(pi, method='ffill')
    macro_aligned.index = labeled.index

    data, features = build_eurusd_features(price, macro)
    print(f'Current features: {features}')
    train_data = data[data.index.year <= train_until]
    test_data = data[data.index.year >= test_from]
    print(f'Train: {len(train_data)} rows (<= {train_until})')
    print(f'Test:  {len(test_data)} rows (>= {test_from})')

    X_train = train_data[features]
    y_train = train_data['label'].astype(int)
    X_test = test_data[features]
    y_test = test_data['label'].astype(int)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)
    preds = model.predict(X_test)

    # Compute residuals: actual return - model-implied return
    test_rets = price['close'].reindex(X_test.index).pct_change()
    long_mask = preds == 2
    short_mask = preds == 0
    model_return = pd.Series(0.0, index=X_test.index)
    model_return[long_mask] = test_rets[long_mask]
    model_return[short_mask] = -test_rets[short_mask]
    actual_return = test_rets
    residual = actual_return - model_return

    print(f'\n{"="*60}')
    print(f'RESIDUAL ANALYSIS — {asset_symbol}')
    print(f'{"="*60}')
    print(f'Model PF: {len(X_test)} test rows, '
          f'{long_mask.sum()} long / {short_mask.sum()} short / '
          f'{((preds==1).sum())} flat')
    print(f'Residual: mean={residual.mean():.6f}, std={residual.std():.6f}')

    # Build candidate missing drivers
    price_ret = price['close'].pct_change().reindex(residual.index)
    pi_resid = residual.index.tz_localize(None) if hasattr(residual.index, 'tz') and residual.index.tz is not None else residual.index
    macro_test = macro.reindex(pi_resid, method='ffill')
    macro_test.index = residual.index
    drivers = build_missing_drivers(macro_test, price_ret)

    print(f'\n{"--- PHASE: Residual correlation with candidate missing drivers ---"}')
    results = []
    for col in drivers.columns:
        joint = pd.concat([residual.rename('residual'),
                           drivers[col].rename('driver')], axis=1).dropna()
        if len(joint) < 20:
            continue
        corr = joint['residual'].corr(joint['driver'])
        abs_corr = abs(corr)
        results.append({'driver': col, 'corr': corr, 'abs_corr': abs_corr})

    df = pd.DataFrame(results)
    df = df.sort_values('abs_corr', ascending=False)

    print(f'{"Driver":>30s}  {"Correlation":>10s}  {"Abs":>6s}')
    print('-' * 50)
    for _, r in df.head(15).iterrows():
        print(f'{r["driver"]:>30s}  {r["corr"]:>+10.4f}  {r["abs_corr"]:>6.3f}')

    # Phase 2: Regime-conditional residual analysis
    print(f'\n{"--- PHASE: Regime-conditional residual analysis ---"}')
    high_vol = drivers['vix'] > drivers['vix'].rolling(63).mean()
    low_vol = drivers['vix'] <= drivers['vix'].rolling(63).mean()
    rising_rates = drivers['us_2y_delta_5'] > 0
    falling_rates = drivers['us_2y_delta_5'] <= 0

    regimes = [
        ('High VIX', high_vol),
        ('Low VIX', low_vol),
        ('Rising 2Y', rising_rates),
        ('Falling 2Y', falling_rates),
        ('VIX > 25', drivers['vix'] > 25),
        ('VIX < 15', drivers['vix'] < 15),
    ]
    for name, mask in regimes:
        sub = residual[mask.reindex(residual.index, fill_value=False)]
        if len(sub) >= 10:
            print(f'  {name:15s}: residual mean={sub.mean():+.6f}, std={sub.std():.6f}, n={len(sub)}')

    # Phase 3: Lagged cross-asset spillover
    print(f'\n{"--- PHASE: Lagged cross-asset spillover ---"}')
    cross_assets = {
        'GC=F': None,
        'USDJPY=X': None,
        'GBPUSD=X': None,
    }
    for sym in cross_assets:
        try:
            ca = load_asset(sym)
            ca_ret = ca['close'].pct_change().reindex(residual.index)
            for lag in [1, 2, 5]:
                ca_lag = ca_ret.shift(lag)
                joint = pd.concat([residual.rename('residual'),
                                   ca_lag.rename('lagged')], axis=1).dropna()
                if len(joint) >= 20:
                    c = joint['residual'].corr(joint['lagged'])
                    print(f'  {sym:15s} lag {lag:2d}: {c:+.4f}')
        except Exception:
            pass

    # Summary: top candidate missing driver
    if len(df) > 0:
        top = df.iloc[0]
        print(f'\n{"="*60}')
        print(f'MISSING DRIVER CANDIDATE: {top["driver"]} (corr={top["corr"]:+.4f})')
        print(f'{"="*60}')
        print(f'The residual correlates most strongly with {top["driver"]}.')
        print(f'This is a candidate for the missing basis vector in EURUSD.')

    return df


if __name__ == '__main__':
    analyze_residuals('EURUSD=X', train_until=2021, test_from=2022)
