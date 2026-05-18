"""Signal correlation check across CADJPY (fwd60) vs XLF, BTC, NZDJPY, USDCAD (tb20)."""
import logging, os, sys, pickle
import pandas as pd
import numpy as np
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from scripts.train_all_assets import (
    compute_features, fetch_history, load_macro, _slug, ticker_features,
)
from scripts.cadjpy_walk_forward import (
    compute_features_v7, FEATURES as CADJPY_FEATURES, FWD60_THRESHOLD,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('corr_check')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE, 'paper_trading', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

TICKER_MAP = {
    'CADJPY': 'CADJPY=X',
    'NZDJPY': 'NZDJPY=X',
    'USDCAD': 'USDCAD=X',
    'XLF':    'XLF',
    'BTC':    'BTC-USD',
}
NAMES = ['CADJPY', 'NZDJPY', 'USDCAD', 'XLF', 'BTC']

def train_cadjpy_fwd60(macro, force=True):
    model_path = os.path.join(MODEL_DIR, 'cadjpy_fwd60_model.pkl')
    if os.path.exists(model_path) and not force:
        with open(model_path, 'rb') as f:
            return pickle.load(f)
    logger.info('CADJPY: training fwd60 model...')
    df = fetch_history('CADJPY=X')
    features_df = compute_features_v7(df, macro)
    X = features_df[CADJPY_FEATURES]
    y = features_df['label'].astype(int)
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    split = int(len(X) * 0.8)
    model.fit(X.iloc[:split], y.iloc[:split],
              eval_set=[(X.iloc[split:], y.iloc[split:])], verbose=False)
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    return model

def train_tb20_model(ticker, macro, ref, force=True):
    slug_name = _slug(ticker)
    model_path = os.path.join(MODEL_DIR, f'{slug_name}_model.pkl')
    if os.path.exists(model_path) and not force:
        with open(model_path, 'rb') as f:
            return pickle.load(f)
    logger.info('%s: training tb20 model...', ticker)
    df = fetch_history(ticker)
    features_df, feats = compute_features(df, ref, macro, ticker)
    X = features_df[feats]
    y = features_df['label'].astype(int)
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    split = int(len(X) * 0.8)
    model.fit(X.iloc[:split], y.iloc[:split],
              eval_set=[(X.iloc[split:], y.iloc[split:])], verbose=False)
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    return model

def get_bias_cadjpy_fwd60(model, macro):
    """Raw probability bias P(long) - P(short) for CADJPY fwd60."""
    df = fetch_history('CADJPY=X')
    features_df = compute_features_v7(df, macro)
    proba = model.predict_proba(features_df[CADJPY_FEATURES])
    return pd.Series(proba[:, 2] - proba[:, 0], index=features_df.index, name='CADJPY')

def get_bias_tb20(model, ticker, macro, ref, name):
    """Raw probability bias P(long) - P(short) for tb20 model."""
    df = fetch_history(ticker)
    features_df, feats = compute_features(df, ref, macro, ticker)
    proba = model.predict_proba(features_df[feats])
    return pd.Series(proba[:, 2] - proba[:, 0], index=features_df.index, name=name)

def walk_forward_cadjpy_bias(macro, years_of_interest):
    """Walk-forward OOS predictions for CADJPY fwd60, returning bias by year."""
    from scripts.cadjpy_walk_forward import compute_features_v7, FEATURES as C_FEATS
    df = fetch_history('CADJPY=X')
    features_df = compute_features_v7(df, macro)
    closes = df['close'].reindex(features_df.index)

    train_years = 5
    all_years = sorted(features_df.index.year.unique())
    result = {}
    for oos_year in years_of_interest:
        if oos_year < all_years[0] + train_years:
            continue
        train_end = oos_year - 1
        train_start = oos_year - train_years
        train_mask = (features_df.index.year >= train_start) & (features_df.index.year <= train_end)
        oos_mask = features_df.index.year == oos_year
        X_train = features_df.loc[train_mask, C_FEATS]
        y_train = features_df.loc[train_mask, 'label'].astype(int)
        X_oos = features_df.loc[oos_mask, C_FEATS]
        if len(X_oos) == 0 or len(X_train) < 200:
            continue
        label_dist = y_train.value_counts(normalize=True)
        if label_dist.min() < 0.05:
            continue
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective='multi:softprob', num_class=3,
            random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
        )
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_oos)
        bias = pd.Series(proba[:, 2] - proba[:, 0], index=X_oos.index, name='CADJPY')
        result[oos_year] = bias
    return result

def walk_forward_tb20_bias(ticker, macro, ref, name, years_of_interest, window_years=3):
    """Walk-forward OOS predictions for tb20 asset, returning bias by year."""
    df = fetch_history(ticker)
    features_df, feats = compute_features(df, ref, macro, ticker)
    all_years = sorted(features_df.index.year.unique())
    result = {}
    for oos_year in years_of_interest:
        train_mask = features_df.index.year < oos_year
        oos_mask = features_df.index.year == oos_year
        if train_mask.sum() == 0 or oos_mask.sum() == 0:
            continue
        X_train = features_df.loc[train_mask, feats]
        y_train = features_df.loc[train_mask, 'label'].astype(int)
        X_oos = features_df.loc[oos_mask, feats]
        if len(X_oos) == 0 or len(X_train) < 200:
            continue
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective='multi:softprob', num_class=3,
            random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
        )
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_oos)
        bias = pd.Series(proba[:, 2] - proba[:, 0], index=X_oos.index, name=name)
        result[oos_year] = bias
    return result

def compute_walk_forward_corr(macro, ref, years_of_interest):
    wf = {}
    cadjpy_wf = walk_forward_cadjpy_bias(macro, years_of_interest)
    if cadjpy_wf:
        wf['CADJPY'] = cadjpy_wf
    for name in ['NZDJPY', 'USDCAD', 'XLF', 'BTC']:
        ticker = TICKER_MAP[name]
        wf[name] = walk_forward_tb20_bias(ticker, macro, ref, name, years_of_interest)

    print('\n' + '=' * 90)
    print('WALK-FORWARD SIGNAL CORRELATION BY YEAR')
    print('=' * 90)
    for year in years_of_interest:
        year_dfs = {}
        for name in NAMES:
            if name in wf and year in wf[name]:
                year_dfs[name] = wf[name][year]
        if len(year_dfs) < 2:
            print(f'\n{year}: insufficient assets ({len(year_dfs)})')
            continue
        df_yr = pd.DataFrame(year_dfs).dropna()
        if len(df_yr) < 5:
            print(f'\n{year}: too few overlapping bars ({len(df_yr)})')
            continue
        print(f'\n{year} Walk-Forward Correlation ({len(df_yr)} bars):')
        print(df_yr.corr().round(4))

def main():
    logger.info('Loading macro and reference data...')
    macro = load_macro()
    ref = fetch_history('SPY', years=10)

    # ---- STEP 1: Train / load all models ----
    logger.info('=' * 60)
    logger.info('STEP 1: TRAINING / LOADING MODELS')
    logger.info('=' * 60)
    cadjpy_model = train_cadjpy_fwd60(macro, force=True)
    tb20_models = {}
    for name in ['NZDJPY', 'USDCAD', 'XLF', 'BTC']:
        tb20_models[name] = train_tb20_model(TICKER_MAP[name], macro, ref, force=True)

    # ---- STEP 2: Full-sample signal bias ----
    logger.info('=' * 60)
    logger.info('STEP 2: COMPUTING FULL-SAMPLE BIAS SIGNALS')
    logger.info('=' * 60)
    signals = {}
    signals['CADJPY'] = get_bias_cadjpy_fwd60(cadjpy_model, macro)
    for name in ['NZDJPY', 'USDCAD', 'XLF', 'BTC']:
        signals[name] = get_bias_tb20(tb20_models[name], TICKER_MAP[name], macro, ref, name)

    df_bias = pd.DataFrame(signals).dropna()
    df_bias = df_bias[
        (df_bias.index >= '2022-01-01') & (df_bias.index <= '2025-12-31')
    ]
    df_bias.index = pd.to_datetime(df_bias.index)

    print('\n' + '=' * 90)
    print('SIGNAL CORRELATION CHECK — FULL-SAMPLE (2022–2025)')
    print('Raw bias = P(long) - P(short) on overlapping dates')
    print('=' * 90)
    print(f'Date range: {df_bias.index[0].date()}  →  {df_bias.index[-1].date()}')
    print(f'Common bars: {len(df_bias)}')
    print()

    corr = df_bias.corr()
    print('5×5 Correlation Matrix:')
    print('=' * 60)
    print(corr.to_string(float_format=lambda x: f'{x:.4f}'))
    print()

    print('Key Pairs:')
    print('-' * 60)
    pairs = [
        ('CADJPY', 'NZDJPY', 'both JPY pairs — should be low'),
        ('CADJPY', 'USDCAD', 'both CAD exposure — could be problematic'),
        ('CADJPY', 'XLF',     'different drivers'),
        ('CADJPY', 'BTC',     'different drivers'),
    ]
    flags = []
    for a, b, note in pairs:
        r = df_bias[a].corr(df_bias[b])
        flag = '⚠ FLAGGED' if abs(r) > 0.35 else 'OK'
        if abs(r) > 0.35:
            flags.append((a, b, r))
        print(f'  {a:>8s} vs {b:<8s}  r = {r:7.4f}  [{flag}]  {note}')

    if flags:
        print(f'\n⚠  PAIRS EXCEEDING |r| > 0.35 THRESHOLD:')
        for a, b, r in flags:
            print(f'     {a:>8s} vs {b:<8s}  r = {r:.4f}')
    else:
        print(f'\n✓  No pairs exceed |r| > 0.35')

    print('\nSignal Statistics (2022–2025):')
    stats = df_bias.describe().loc[['mean', 'std', 'min', 'max', 'count']]
    print(stats.to_string(float_format=lambda x: f'{x:.4f}'))

    # ---- STEP 3: Walk-forward correlation by year ----
    logger.info('=' * 60)
    logger.info('STEP 3: WALK-FORWARD CORRELATION BY YEAR (OOS)')
    logger.info('=' * 60)
    compute_walk_forward_corr(macro, ref, [2022, 2023, 2024, 2025])

    print('\nDone.')

if __name__ == '__main__':
    main()
