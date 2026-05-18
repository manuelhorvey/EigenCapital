"""GC=F isolation test — dual-label (tb20 vs fwd60).

Directional check:
  2022: real yields surged → gold fell ~18% → expect SHORT
  2023: real yields peaked → gold rallied ~13% → expect LONG
  2024: real yields fell + safe haven → gold +27% → expect LONG

Features tested:
  - System default (tb20): rate_diff, 2y_yield_delta_63, gc_mom_63, gc_vs_spy_63
  - Real-yield variant (fwd60): real_yield_delta_63, rate_diff, gc_mom_63, vix_ma21
  - Real-yield + carry variant: real_yield_delta_63, breakeven_delta_63, dxy_mom_63, gc_mom_63
"""
import logging, os, sys
import pandas as pd
import numpy as np
import xgboost as xgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from labels.triple_barrier import apply_triple_barrier
from scripts.train_all_assets import fetch_history, load_macro, _slug

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('gc_test')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GC = "GC=F"
TRAIN_END = 2021
TEST_YEARS = [2022, 2023, 2024]

FWD60_THRESHOLD = 0.02
CONF_THRESHOLD = 0.45

FEATURE_SETS = {
    'tb20_system: rate_diff + 2y_yield + gc_mom_63 + dxy_mom': {
        'feats': ['rate_diff', '2y_yield_delta_63', 'gc_mom_63', 'dxy_mom_63'],
        'label': 'tb20',
    },
    'tb20: rate_diff + real_yield_delta + gc_mom + vix': {
        'feats': ['rate_diff', 'real_yield_delta_63', 'gc_mom_63', 'vix_ma21'],
        'label': 'tb20',
    },
    'fwd60_system: rate_diff + 2y_yield + gc_mom_63 + dxy_mom': {
        'feats': ['rate_diff', '2y_yield_delta_63', 'gc_mom_63', 'dxy_mom_63'],
        'label': 'fwd60',
    },
    'fwd60: real_yield_delta + rate_diff + gc_mom + vix': {
        'feats': ['real_yield_delta_63', 'rate_diff', 'gc_mom_63', 'vix_ma21'],
        'label': 'fwd60',
    },
    'fwd60: real_yield + breakeven + dxy + gc_mom': {
        'feats': ['real_yield_delta_63', 'breakeven_delta_63', 'dxy_mom_63', 'gc_mom_63'],
        'label': 'fwd60',
    },
}


def _tb_returns_label(df, vbar=20):
    """Triple barrier label."""
    labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=vbar)
    labeled['label'] = (labeled['label'] + 1).astype(int)
    return labeled


def _fwd_returns_label(df, horizon=60):
    """Forward return label."""
    ret = df['close'].pct_change(horizon).shift(-horizon)
    labels = ret.apply(lambda x: 2 if x > FWD60_THRESHOLD else (0 if x < -FWD60_THRESHOLD else 1)).astype(int)
    return pd.DataFrame({'label': labels}).dropna()


def compute_features(df, macro, feats, label_type='tb20'):
    if label_type == 'tb20':
        labeled = _tb_returns_label(df)
    else:
        labeled = _fwd_returns_label(df)

    pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labeled.index])
    a = macro.reindex(pi, method='ffill')
    a.index = labeled.index

    slug = _slug(GC)
    a['rate_diff'] = a['fed_funds'] - a['ecb_rate']
    a['2y_yield_delta_63'] = a['us_2y'].diff(63)
    a['real_yield_delta_63'] = a['real_yield_10y'].diff(63)
    a['breakeven_delta_63'] = a['breakeven_10y'].diff(63)
    a['dxy_mom_63'] = a['dxy'].pct_change(63)
    a['gc_mom_63'] = df['close'].pct_change(63)
    a['vix_ma21'] = a['vix'].rolling(21).mean()

    a['label'] = labeled['label']
    return a.dropna(subset=feats + ['label'])


def test_one(name, feats, label_type, df, macro):
    features_df = compute_features(df, macro, feats, label_type)
    returns = df['close'].pct_change().shift(-1).reindex(features_df.index)

    train_mask = features_df.index.year <= TRAIN_END
    X_train = features_df.loc[train_mask, feats]
    y_train = features_df.loc[train_mask, 'label'].astype(int)

    if len(np.unique(y_train)) < 3:
        logger.warning('  %s: only %d classes in training, skipping', name, len(np.unique(y_train)))
        return None

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X_train, y_train)

    imp = sorted(zip(feats, model.feature_importances_), key=lambda x: -x[1])
    corr = features_df[feats + ['label']].corr()['label'].drop('label')

    results = []
    for year in TEST_YEARS:
        mask = features_df.index.year == year
        X_test = features_df.loc[mask, feats]
        if len(X_test) == 0:
            continue

        proba = model.predict_proba(X_test)
        prob_long = proba[:, 2]
        prob_short = proba[:, 0]
        yr_ret = returns.loc[X_test.index]

        actual_dir = 'SHORT' if yr_ret.sum() < 0 else 'LONG'
        predicted_dir = 'LONG' if prob_long.mean() > prob_short.mean() else 'SHORT'
        correct = actual_dir == predicted_dir

        results.append({
            'year': year,
            'n_bars': len(X_test),
            'actual_return': round(float(yr_ret.sum()), 4),
            'actual_dir': actual_dir,
            'predicted_dir': predicted_dir,
            'correct': correct,
            'mean_p_long': round(float(prob_long.mean()), 3),
            'mean_p_short': round(float(prob_short.mean()), 3),
            'pct_long_bias': round(float((prob_long > prob_short).mean()), 3),
            'n_long': int((prob_long > CONF_THRESHOLD).sum()),
            'n_short': int((prob_short > CONF_THRESHOLD).sum()),
        })
        logger.info('  %d: ret=%+.4f actual=%s predicted=%s %s  P_long=%.3f P_short=%.3f',
                     year, yr_ret.sum(), actual_dir, predicted_dir,
                     '✓' if correct else '✗', prob_long.mean(), prob_short.mean())

    return {'name': name, 'feats': feats, 'label': label_type,
            'importance': imp, 'corr': corr, 'results': results}


def main():
    logger.info('Loading data...')
    macro = load_macro()
    df = fetch_history(GC)

    all_out = []
    for name, cfg in FEATURE_SETS.items():
        logger.info('')
        logger.info('=' * 60)
        logger.info('Testing: %s', name)
        logger.info('=' * 60)
        out = test_one(name, cfg['feats'], cfg['label'], df, macro)
        if out:
            all_out.append(out)

    print('\n\n' + '=' * 90)
    print('GC=F DUAL-LABEL ISOLATION TEST')
    print('=' * 90)

    for out in all_out:
        print(f'\n  {out["name"]}')
        print(f'  {"-" * (len(out["name"]) + 2)}')
        print(f'  Features: {out["feats"]}')
        print(f'  Label:    {out["label"]}')
        print(f'  Importance: {dict(out["importance"])}')
        for r in out['results']:
            sign = '+' if r['actual_return'] > 0 else ''
            mark = '✓' if r['correct'] else '✗'
            print(f'    {r["year"]}: actual {r["actual_dir"]} ({sign}{r["actual_return"]:.4f})  '
                  f'→ {r["predicted_dir"]} {mark}  '
                  f'(P_long={r["mean_p_long"]:.3f} P_short={r["mean_p_short"]:.3f})')

    print('\n' + '=' * 90)
    print('VERDICT')
    print('=' * 90)
    for out in all_out:
        correct_years = [r for r in out['results'] if r['correct']]
        wrong_years = [r for r in out['results'] if not r['correct']]
        n_pass = len(correct_years)
        print(f'\n  {out["name"]}')
        print(f'    Correct: {n_pass}/{len(out["results"])} '
              f'({[r["year"] for r in correct_years]}) '
              f'Wrong: {[r["year"] for r in wrong_years]}')
        if n_pass >= 2:
            print(f'    → ✅ RECOMMENDED for {"fwd60" if "fwd60" in out["label"] else "tb20"} label')
        else:
            print(f'    → ❌ FAIL')


if __name__ == '__main__':
    main()
