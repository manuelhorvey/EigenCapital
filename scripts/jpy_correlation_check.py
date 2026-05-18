import logging, os, sys, pickle
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from scripts.train_all_assets import (
    compute_features, fetch_history, load_macro, _slug,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('jpy_check')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE, 'paper_trading', 'models')

PAIRS = ['NZDJPY=X', 'AUDJPY=X', 'CADJPY=X']


def load_model(ticker):
    slug = _slug(ticker)
    path = os.path.join(MODEL_DIR, f'{slug}_model.pkl')
    if not os.path.exists(path):
        logger.error('Model not found for %s at %s', ticker, path)
        return None
    with open(path, 'rb') as f:
        return pickle.load(f)


def generate_signals(ticker, macro, ref):
    model = load_model(ticker)
    if model is None:
        return None

    df = fetch_history(ticker, years=10)
    features_df, feats = compute_features(df, ref, macro, ticker)

    X = features_df[feats]
    proba = model.predict_proba(X)
    prob_long = proba[:, 2]
    prob_short = proba[:, 0]

    signals = pd.Series(0, index=X.index)
    signals[prob_long > 0.45] = 2
    signals[prob_short > 0.45] = 0

    return signals


def main():
    logger.info('Loading macro and reference data...')
    macro = load_macro()

    ref = None
    try:
        ref = fetch_history('SPY', years=10)
    except Exception:
        pass

    all_signals = {}
    for ticker in PAIRS:
        sigs = generate_signals(ticker, macro, ref)
        if sigs is not None:
            all_signals[ticker] = sigs
            n_long = (sigs == 2).sum()
            n_short = (sigs == 0).sum()
            n_flat = (sigs == 1).sum()  # shouldn't exist but just in case
            total = len(sigs)
            pct_active = (n_long + n_short) / total * 100
            logger.info('%s: LONG=%d SHORT=%d FLAT=%d active=%.1f%%',
                         ticker, n_long, n_short, total - n_long - n_short, pct_active)

    if len(all_signals) < 2:
        logger.error('Need at least 2 pairs with models')
        return

    df = pd.DataFrame(all_signals)
    df = df.dropna()

    print('\n' + '=' * 60)
    print('JPY CROSS SIGNAL CORRELATION CHECK')
    print('=' * 60)

    print(f'\nCommon date range: {df.index[0].date()} to {df.index[-1].date()}')
    print(f'Total bars: {len(df)}')

    corr = df.corr()
    print('\nSignal correlation matrix:')
    print(corr.round(3))

    print('\n' + '-' * 60)
    for i, a in enumerate(PAIRS):
        for b in PAIRS[i+1:]:
            if a in df.columns and b in df.columns:
                r = df[a].corr(df[b])
                verdict = '⚠ HIGH — concentration risk' if abs(r) > 0.40 else '✓ LOW — independent'
                print(f'  {a:12s} vs {b:12s}:  r = {r:.3f}  → {verdict}')

    print('\n' + '-' * 60)
    print('Overlap analysis (% of bars where both are active):')
    for i, a in enumerate(PAIRS):
        for b in PAIRS[i+1:]:
            if a not in df.columns or b not in df.columns:
                continue
            a_active = df[a] != 0
            b_active = df[b] != 0
            both_active = (a_active & b_active).sum()
            either_active = (a_active | b_active).sum()
            pct = both_active / max(either_active, 1) * 100
            same_dir = ((df[a] == df[b]) & a_active & b_active).sum()
            same_pct = same_dir / max(both_active, 1) * 100
            print(f'  {a:12s} & {b:12s}: both_active={both_active:5d} '
                  f'overlap={pct:.0f}% same_dir={same_pct:.0f}%')

    print('\n' + '=' * 60)
    print('RECOMMENDATION:')
    print('=' * 60)
    strong_corr = False
    for i, a in enumerate(PAIRS):
        for b in PAIRS[i+1:]:
            if a in df.columns and b in df.columns and abs(df[a].corr(df[b])) > 0.40:
                strong_corr = True

    if strong_corr:
        print('  JPY crosses show significant correlation (>0.40).')
        print('  → Add only the best-performing JPY cross to avoid concentration.')
        print('  → Based on walk-forward: AUDJPY (Sharpe 1.49, 88% windows) is the pick.')
    else:
        print('  JPY crosses are sufficiently independent.')
        print('  → AUDJPY and CADJPY can both enter isolation testing.')
        print('  → NZDJPY (existing) is independent from both.')

    print('')


if __name__ == '__main__':
    main()
