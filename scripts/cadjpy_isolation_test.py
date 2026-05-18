import logging, os, sys
import pandas as pd
import numpy as np
import xgboost as xgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from labels.triple_barrier import apply_triple_barrier
from scripts.train_all_assets import fetch_history, load_macro, _slug

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('cadjpy_test')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CADJPY = "CADJPY=X"
TRAIN_END = 2021
TEST_YEARS = [2022, 2023]

LABEL_TYPES = ['tb20', 'tb60', 'fwd60']
FEATURE_SETS = {
    'V_default: system FX features': {
        'feats': ['us_jp_10y_spread', 'dxy_mom_21', 'cadjpy_mom_21', 'vix_ma21', 'vix_delta_5'],
        'label': 'tb20',
    },
    'V2: user-suggested carry features': {
        'feats': ['ca_jp_10y_spread', 'ca_jp_spread_mom_21', 'cadjpy_mom_63', 'vix_ma21'],
        'label': 'tb20',
    },
    'V3: spread velocity + short momentum': {
        'feats': ['ca_jp_spread_mom_5', 'ca_jp_spread_mom_21', 'cadjpy_mom_21', 'vix_ma21'],
        'label': 'tb20',
    },
    'V4: FX momentum + carry change': {
        'feats': ['cadjpy_mom_21', 'cadjpy_mom_63', 'vix_ma21', 'ca_jp_spread_mom_21'],
        'label': 'tb20',
    },
    'V5: spread z-score + velocity': {
        'feats': ['ca_jp_spread_z63', 'ca_jp_spread_mom_5', 'cadjpy_mom_21', 'vix_ma21'],
        'label': 'tb20',
    },
    'V6: spread z-score + mom63': {
        'feats': ['ca_jp_spread_z63', 'cadjpy_mom_63', 'ca_jp_spread_mom_5', 'vix_ma21'],
        'label': 'tb20',
    },
    'V7: V3 features, fwd60 label': {
        'feats': ['ca_jp_spread_mom_5', 'ca_jp_spread_mom_21', 'cadjpy_mom_21', 'vix_ma21'],
        'label': 'fwd60',
    },
    'V8: user features, fwd60 label': {
        'feats': ['ca_jp_10y_spread', 'ca_jp_spread_mom_21', 'cadjpy_mom_63', 'vix_ma21'],
        'label': 'fwd60',
    },
}


def compute_features(df, macro, feats, label_type='tb20'):
    if label_type == 'tb20':
        labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=20)
        labeled['label'] = (labeled['label'] + 1).astype(int)
    elif label_type == 'tb60':
        labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=60)
        labeled['label'] = (labeled['label'] + 1).astype(int)
    elif label_type == 'fwd60':
        ret = df['close'].pct_change(60).shift(-60)
        labeled = pd.DataFrame(index=df.index)
        labeled['label'] = ret.apply(
            lambda x: 2 if x > 0.02 else (0 if x < -0.02 else 1)
        ).astype(int)

    # macro is tz-naive, df/labeled is tz-aware; use tz-naive idx for reindex, then switch back
    tz_naive_idx = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labeled.index])
    a = macro.reindex(tz_naive_idx, method='ffill')
    a.index = labeled.index

    a['ca_jp_10y_spread'] = a['ca_10y'] - a['jp_10y']
    a['ca_jp_spread_mom_21'] = a['ca_jp_10y_spread'].diff(21)
    a['ca_jp_spread_mom_5'] = a['ca_jp_10y_spread'].diff(5)
    a['ca_jp_spread_z63'] = (
        (a['ca_jp_10y_spread'] - a['ca_jp_10y_spread'].rolling(63).mean())
        / a['ca_jp_10y_spread'].rolling(63).std()
    )
    a['dxy_mom_21'] = a['dxy'].pct_change(21)
    a['cadjpy_mom_21'] = df['close'].pct_change(21)
    a['cadjpy_mom_63'] = df['close'].pct_change(63)

    a['label'] = labeled['label']
    return a.dropna(subset=feats + ['label'])


def test_feature_set(name, feats, df, macro, label_type='tb20'):
    features_df = compute_features(df, macro, feats, label_type)
    returns = df['close'].pct_change().shift(-1).reindex(features_df.index)

    train_mask = features_df.index.year <= TRAIN_END
    X_train = features_df.loc[train_mask, feats]
    y_train = features_df.loc[train_mask, 'label'].astype(int)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)

    importance = model.feature_importances_
    feat_imp = sorted(zip(feats, importance), key=lambda x: -x[1])

    corr_check = features_df[feats + ['label']].corr()['label'].drop('label')

    results = []
    for year in TEST_YEARS:
        mask = features_df.index.year == year
        X_test = features_df.loc[mask, feats]
        if len(X_test) == 0:
            continue

        proba = model.predict_proba(X_test)
        prob_long = proba[:, 2]
        prob_short = proba[:, 0]

        year_returns = returns.loc[X_test.index]
        actual_return = float(year_returns.sum())

        mean_long = float(prob_long.mean())
        mean_short = float(prob_short.mean())
        raw_dir_is_long = mean_long > mean_short
        pct_long_bias = float((prob_long > prob_short).mean())

        results.append({
            'year': year,
            'n_bars': len(X_test),
            'actual_return': round(actual_return, 4),
            'mean_p_long': round(mean_long, 4),
            'mean_p_short': round(mean_short, 4),
            'raw_dir_is_long': raw_dir_is_long,
            'pct_long_bias': round(pct_long_bias, 4),
            'n_train': len(X_train),
        })

    return results, feat_imp, corr_check


def main():
    logger.info('Loading data...')
    macro = load_macro()
    logger.info('Macro columns: %s', list(macro.columns))
    logger.info('Downloading CADJPY history...')
    df = fetch_history(CADJPY)

    all_results = {}

    for name, cfg in FEATURE_SETS.items():
        logger.info('')
        logger.info('=' * 70)
        logger.info('Testing: %s', name)
        logger.info('Features: %s', cfg['feats'])
        logger.info('Label:   %s', cfg.get('label', 'tb20'))
        logger.info('=' * 70)

        feats = cfg['feats']
        label_type = cfg.get('label', 'tb20')
        results, feat_imp, corr_check = test_feature_set(name, feats, df, macro, label_type)

        logger.info('Feature importance:')
        for fname, imp in feat_imp:
            logger.info('  %s: %.4f', fname, imp)

        logger.info('Correlation with label (train):')
        for fname in feats:
            logger.info('  %s: %+.4f', fname, corr_check[fname])

        for r in results:
            actual_dir = 'LONG' if r['actual_return'] > 0 else 'SHORT'
            predicted_dir = 'LONG' if r['raw_dir_is_long'] else 'SHORT'
            correct = 'CORRECT' if actual_dir == predicted_dir else 'WRONG'
            logger.info('  %d: P_long=%.3f P_short=%.3f → %s (%s) ret=%+.4f',
                         r['year'], r['mean_p_long'], r['mean_p_short'],
                         predicted_dir, correct, r['actual_return'])

        all_results[name] = results

    print('\n\n')
    print('=' * 80)
    print('CADJPY ISOLATION TEST — ALL FEATURE SETS')
    print('=' * 80)

    for name, results in all_results.items():
        print(f'\n  {name}')
        print(f'  {"-" * (len(name) + 2)}')
        for r in results:
            actual_dir = 'LONG' if r['actual_return'] > 0 else 'SHORT'
            predicted_dir = 'LONG' if r['raw_dir_is_long'] else 'SHORT'
            correct = '✓' if actual_dir == predicted_dir else '✗'
            sign = '+' if r['actual_return'] > 0 else ''
            print(f'    {r["year"]}: actual {actual_dir} ({sign}{r["actual_return"]:.4f})  '
                  f'→ model: {predicted_dir} {correct}  '
                  f'(P_long={r["mean_p_long"]:.3f} P_short={r["mean_p_short"]:.3f})')

    print('\n' + '=' * 80)
    print('VERDICT')
    print('=' * 80)
    for name, results in all_results.items():
        r1, r2 = results[0], results[1]
        d22 = r1['actual_return'] > 0
        d23 = r2['actual_return'] > 0
        p22_correct = r1['raw_dir_is_long'] == (r1['actual_return'] > 0)
        p23_correct = r2['raw_dir_is_long'] == (r2['actual_return'] > 0)
        consistent = r1['raw_dir_is_long'] == r2['raw_dir_is_long']
        passed = sum([p22_correct, p23_correct, consistent])
        print(f'\n  {name}')
        print(f'    Raw bias correct:  2022={p22_correct}, 2023={p23_correct}')
        print(f'    Consistent bias:   {consistent}')
        print(f'    Gates:             {passed}/3')
        print(f'    → {"✅ PASS" if p22_correct and p23_correct else "❌ FAIL"}')


if __name__ == '__main__':
    main()
