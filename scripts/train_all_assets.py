import logging, os, sys, pickle
import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from labels.triple_barrier import apply_triple_barrier

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('train_all')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE, 'paper_trading', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

TICKERS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X", "USDCHF=X",
    "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "CHFJPY=X", "EURCHF=X", "EURAUD=X",
    "GBPAUD=X", "AUDCAD=X", "NZDJPY=X", "EURCAD=X", "GBPCAD=X", "AUDNZD=X", "CADJPY=X",
    "EURNZD=X", "GBPNZD=X", "GBPCHF=X", "CADCHF=X", "NZDCAD=X", "NZDCHF=X", "AUDCHF=X",
    "GC=F", "BTC-USD",
]

FX_TICKERS = {t for t in TICKERS if "=X" in t}
CRYPTO_TICKERS = {"BTC-USD"}
METAL_TICKERS = {"GC=F"}
EQUITY_TICKERS = set()


def _slug(name):
    return name.lower().replace("=", "").replace("-", "_")


def asset_type(ticker):
    if ticker in FX_TICKERS:
        return "fx"
    if ticker in CRYPTO_TICKERS:
        return "crypto"
    if ticker in METAL_TICKERS:
        return "metal"
    return "equity"


def ticker_features(name):
    s = _slug(name)
    atype = asset_type(name)
    if atype == "fx":
        maybe_dxy = "dxy_mom_21" if s in ("eurusd", "gbpusd", "usdchf", "usdcad",
                                           "audusd", "nzdusd", "eurjpy", "gbpjpy",
                                           "eurcad", "gbpcad", "audcad", "cadjpy") else None
        maybe_yield_spread = None
        if s in ("usdjpy", "eurjpy", "gbpjpy", "audjpy", "chfjpy", "nzdjpy", "cadjpy"):
            maybe_yield_spread = "us_jp_10y_spread"
        elif s in ("eurchf", "gbpchf", "cadchf", "nzdchf", "audchf", "chfjpy"):
            maybe_yield_spread = None
        features = ["vix_ma21", "vix_delta_5"]
        if maybe_yield_spread:
            features.append(maybe_yield_spread)
        if maybe_dxy:
            features.append(maybe_dxy)
        features.append(f"{s}_mom_21")
        return features
    else:
        return ["rate_diff", "2y_yield_delta_63", f"{s}_mom_63", f"{s}_vs_spy_63"]


def compute_features(df, ref, macro, name):
    labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=20)
    pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labeled.index])
    a = macro.reindex(pi, method='ffill')
    a.index = labeled.index

    s = _slug(name)
    a[f'{s}_mom_63'] = df['close'].pct_change(63)
    a[f'{s}_mom_21'] = df['close'].pct_change(21)
    if ref is not None:
        a[f'{s}_vs_spy_63'] = a[f'{s}_mom_63'] - ref['close'].pct_change(63)
    else:
        a[f'{s}_vs_spy_63'] = 0.0
    a['dxy_mom_21'] = a['dxy'].pct_change(21)
    a['us_jp_10y_spread'] = a['us_10y'] - a['jp_10y']

    a['label'] = (labeled.loc[a.index, 'label'] + 1).astype(int)
    feats = ticker_features(name)
    return a.dropna(subset=feats + ['label']), feats


def fetch_history(ticker, years=10):
    import yfinance as yf
    end = datetime.now()
    start = f'{end.year - years}-01-01'
    df = yf.download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert('US/Eastern')
    else:
        df.index = df.index.tz_localize('US/Eastern')
    return df


def load_macro():
    m = pd.read_parquet(os.path.join(BASE, 'data/processed/macro_factors.parquet'))
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['2y_yield_delta_63'] = m['us_2y'].diff(63)
    m['dxy_mom_63'] = m['dxy'].pct_change(63)
    m['vix_ma21'] = m['vix'].rolling(21).mean()
    m['vix_delta_5'] = m['vix'].diff(5)
    m['us_jp_10y_spread'] = m['us_10y'] - m['jp_10y']
    return m.iloc[90:]


def evaluate_model(model, X_test, y_test):
    from sklearn.metrics import accuracy_score, log_loss
    y_pred = model.predict(X_test)
    proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll = log_loss(y_test, proba)
    return acc, ll


def train_one(ticker, macro, ref, force=False):
    slug = _slug(ticker)
    name = slug
    model_path = os.path.join(MODEL_DIR, f'{name}_model.pkl')
    if os.path.exists(model_path) and not force:
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        logger.info('  %s: loaded cached model', ticker)
        return model, None

    logger.info('  %s: downloading history...', ticker)
    df = fetch_history(ticker)
    features_df, feats = compute_features(df, ref, macro, ticker)
    logger.info('  %s: %d feature rows, features=%s', ticker, len(features_df), feats)

    if len(features_df) < 200:
        logger.warning('  %s: insufficient data (%d rows), skipping', ticker, len(features_df))
        return None, None

    end_date = features_df.index[-1]
    start_date = end_date - pd.DateOffset(years=5)
    train = features_df[features_df.index >= start_date]
    if len(train) < 200:
        train = features_df

    X = train[feats]
    y = train['label'].astype(int)
    split = int(len(X) * 0.8)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective='multi:softprob', num_class=3,
        random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
    )
    model.fit(X.iloc[:split], y.iloc[:split],
              eval_set=[(X.iloc[split:], y.iloc[split:])], verbose=False)

    acc, ll = evaluate_model(model, X.iloc[split:], y.iloc[split:])
    logger.info('  %s: val acc=%.4f logloss=%.4f', ticker, acc, ll)

    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    return model, {"accuracy": acc, "logloss": ll, "n_train": len(train), "n_test": len(X) - split}


def main():
    logger.info('Loading macro data...')
    macro = load_macro()
    ref = fetch_history('SPY', years=10)

    results = []
    for ticker in TICKERS:
        try:
            model, stats = train_one(ticker, macro, ref, force=True)
            if stats:
                stats['ticker'] = ticker
                stats['slug'] = _slug(ticker)
                stats['features'] = ','.join(ticker_features(ticker))
                results.append(stats)
                logger.info('  ✓ %s: acc=%.4f logloss=%.4f', ticker, stats['accuracy'], stats['logloss'])
            else:
                logger.warning('  ✗ %s: failed (no data)', ticker)
        except Exception as e:
            logger.error('  ✗ %s: error: %s', ticker, e)
            import traceback; traceback.print_exc()

    if results:
        df = pd.DataFrame(results)
        df = df.sort_values('accuracy', ascending=False)
        print('\n' + '=' * 80)
        print('TRAINING SUMMARY (sorted by validation accuracy)')
        print('=' * 80)
        for _, r in df.iterrows():
            print(f'  {r["ticker"]:20s}  acc={r["accuracy"]:.4f}  logloss={r["logloss"]:.4f}  '
                  f'n_train={r["n_train"]:5d}  features={r["features"]}')
        print(f'\nAverage accuracy: {df["accuracy"].mean():.4f}')
        print(f'Average logloss: {df["logloss"].mean():.4f}')
        print(f'Trained {len(df)}/{len(TICKERS)} assets')
        df.to_csv(os.path.join(BASE, 'data', 'processed', 'training_results.csv'), index=False)
        logger.info('Results saved to data/processed/training_results.csv')
    else:
        print('No models trained.')


if __name__ == '__main__':
    main()
