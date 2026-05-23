"""Phase A.2 — Freeze OOS predictions via HybridRegimeEnsemble walk-forward.

For each live asset:
1. Fetch OHLC + macro + SPY ref
2. Build base features via FeatureContract
3. Build regime features + run RegimeClassifier for P_trend/P_range/P_volatile
4. Build structural + interaction features
5. Align all to common index
6. Walk-forward (5yr train / 1yr test) with HybridRegimeEnsemble
7. Store OOS predictions + OHLC + metadata to parquet

Output: data/sandbox/{NAME}/ensemble_oos_predictions.parquet
"""

import os, sys, logging
import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from features.builder import compute_macro_derived, build_features
from features.registry import FEATURE_REGISTRY
from features.contract import KNOWN_MACRO_COLUMNS
from features.regime_features import generate_regime_features
from features.structural_features import generate_structural_features
from features.interaction_features import generate_interaction_features
from models.regime.regime_classifier import RegimeClassifier
from models.hybrid_ensemble import HybridRegimeEnsemble

logger = logging.getLogger("quantforge.execution_surface.ensemble_freeze")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SANDBOX_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            'data', 'sandbox')
WF_TRAIN_YEARS = 5
MIN_TRAIN_ROWS = 200
MIN_TEST_ROWS = 30


def _normalize(df):
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize('US/Eastern')
    else:
        df.index = df.index.tz_convert('US/Eastern')
    return df


def fetch_history(ticker, years=15):
    end = pd.Timestamp.now()
    start = f'{end.year - years}-01-01'
    df = yf.download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
    return _normalize(df)


def compute_volatility(close, span=100):
    returns = np.log(close / close.shift(1))
    return returns.ewm(span=span).std()


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high - low, np.maximum(
        abs(high - close.shift(1)), abs(low - close.shift(1))
    ))
    return tr.rolling(period).mean()


def classify_vol_regime(close):
    vol = compute_volatility(close)
    recent = vol.dropna().iloc[-min(252, len(vol)):]
    if len(recent) < 20:
        return 'unknown'
    low_thresh = recent.quantile(0.33)
    high_thresh = recent.quantile(0.67)
    latest = recent.iloc[-1]
    if latest <= low_thresh:
        return 'low_vol'
    elif latest >= high_thresh:
        return 'high_vol'
    return 'transition'


def build_ensemble_features(df, macro, ref, contract):
    base = build_features(df, macro, ref, contract)
    regime_raw = generate_regime_features(df)
    classifier = RegimeClassifier()
    regime_meta = classifier.classify(regime_raw)
    struct = generate_structural_features(df)
    common = base.index.intersection(regime_meta.index).intersection(struct.index)
    # ema_spread and dist_ema_20 are needed by generate_interaction_features
    close = df['close'].reindex(base.index).ffill()
    ema_20 = close.ewm(span=20).mean()
    base['ema_spread'] = (close.ewm(span=5).mean() - ema_20) / ema_20
    base['dist_ema_20'] = (close - ema_20) / ema_20
    macro_in_base = [c for c in KNOWN_MACRO_COLUMNS if c in base.columns]
    avail_base = macro_in_base + [c for c in list(contract.features) + ['ema_spread', 'dist_ema_20'] if c in base.columns and c not in KNOWN_MACRO_COLUMNS]
    X = pd.concat([
        base.loc[common, avail_base],
        regime_meta.loc[common, ['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
        struct.loc[common],
    ], axis=1)
    interact = generate_interaction_features(base.loc[common], regime_meta.loc[common], struct.loc[common])
    X = pd.concat([X, interact.loc[common]], axis=1)
    y = base.loc[common, 'label'].astype(int)
    regimes = regime_meta.loc[common, 'regime']
    return X, y, regimes, base.loc[common]


def freeze_one(ticker, force=False):
    contract = FEATURE_REGISTRY[ticker]
    name = contract.name
    logger.info('=' * 60)
    logger.info('Ensemble freeze for %s (%s)', name, ticker)
    logger.info('=' * 60)

    out_dir = os.path.join(SANDBOX_BASE, name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'ensemble_oos_predictions.parquet')
    if os.path.exists(out_path) and not force:
        logger.info('%s: ensemble predictions already frozen at %s', name, out_path)
        return out_path

    logger.info('  Fetching data...')
    df = fetch_history(ticker)
    logger.info('  %d rows from %s to %s', len(df), df.index[0].date(), df.index[-1].date())

    logger.info('  Loading macro and ref...')
    macro_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              'data', 'processed', 'macro_factors.parquet')
    macro = compute_macro_derived(pd.read_parquet(macro_path))
    ref = fetch_history('SPY', years=15) if contract.requires_ref else None

    logger.info('  Building ensemble features...')
    X, y, regimes, base = build_ensemble_features(df, macro, ref, contract)
    logger.info('  %d feature rows, %d columns, %d features', len(X), X.shape[1], len(contract.features))

    close = df['close'].reindex(X.index).ffill()
    high = df['high'].reindex(X.index).ffill()
    low = df['low'].reindex(X.index).ffill()
    open_ = df['open'].reindex(X.index).ffill()
    volume = df['volume'].reindex(X.index).ffill()
    vol_series = compute_volatility(close)
    atr_series = compute_atr(high, low, close)

    years = sorted(X.index.year.unique())
    test_years = [y for y in years if y >= years[0] + WF_TRAIN_YEARS and y <= pd.Timestamp.now().year]
    if not test_years:
        logger.warning('  %s: no valid test years', name)
        return None

    chunks = []
    for ty in test_years:
        tr_end = ty - 1
        tr_start = tr_end - WF_TRAIN_YEARS + 1
        train_mask = ((X.index >= pd.Timestamp(f'{tr_start}-01-01', tz='US/Eastern'))
                      & (X.index <= pd.Timestamp(f'{tr_end}-12-31', tz='US/Eastern')))
        test_mask = ((X.index >= pd.Timestamp(f'{ty}-01-01', tz='US/Eastern'))
                     & (X.index <= pd.Timestamp(f'{ty}-12-31', tz='US/Eastern')))
        X_train = X[train_mask]
        y_train = y[train_mask]
        regimes_train = regimes[train_mask]
        X_test = X[test_mask]
        regimes_test = regimes[test_mask]

        if len(X_train) < MIN_TRAIN_ROWS or len(X_test) < MIN_TEST_ROWS:
            logger.info('  %s %d: insufficient data (train=%d, test=%d), skipping',
                        name, ty, len(X_train), len(X_test))
            continue

        ensemble = HybridRegimeEnsemble()
        ensemble.train(X_train, y_train, regimes_train)
        proba = ensemble.predict_proba(X_test, regimes_test)
        preds = np.argmax(proba, axis=1)

        chunk = pd.DataFrame(index=X_test.index)
        chunk['open'] = open_.reindex(X_test.index)
        chunk['high'] = high.reindex(X_test.index)
        chunk['low'] = low.reindex(X_test.index)
        chunk['close'] = close.reindex(X_test.index)
        chunk['volume'] = volume.reindex(X_test.index)
        chunk['signal'] = preds.astype(int)
        chunk['prob_long'] = proba[:, 2]
        chunk['prob_short'] = proba[:, 0]
        chunk['prob_neutral'] = proba[:, 1]
        chunk['confidence'] = proba.max(axis=1) * 100
        chunk['volatility'] = vol_series.reindex(X_test.index)
        chunk['atr'] = atr_series.reindex(X_test.index)
        chunk['year'] = ty
        chunk['regime'] = classify_vol_regime(close.loc[:X_test.index[-1]])

        chunks.append(chunk)
        n_l = int((preds == 2).sum())
        n_s = int((preds == 0).sum())
        n_h = int((preds == 1).sum())
        logger.info('  %s %d: %d predictions (%d L / %d S / %d H)',
                    name, ty, len(X_test), n_l, n_s, n_h)

    if not chunks:
        logger.warning('  %s: no ensemble OOS predictions generated', name)
        return None

    result = pd.concat(chunks).sort_index()
    result.to_parquet(out_path)
    logger.info('  %s: saved %d ensemble OOS predictions to %s', name, len(result), out_path)
    return out_path


def freeze_all(target_tickers=None, force=False):
    tickers = target_tickers or list(FEATURE_REGISTRY.keys())
    results = {}
    for ticker in tickers:
        try:
            path = freeze_one(ticker, force=force)
            if path:
                results[ticker] = path
        except Exception as e:
            logger.error('%s: FAILED — %s', ticker, e)
            import traceback; traceback.print_exc()
    logger.info('Frozen %d/%d assets with ensemble', len(results), len(tickers))
    return results


if __name__ == '__main__':
    freeze_all()
