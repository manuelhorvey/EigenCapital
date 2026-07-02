"""Deprecated: use retrain_all_fixed.py instead."""

import logging
import os
import sys
import warnings

import pandas as pd
import xgboost as xgb
import yfinance as yf

warnings.warn(
    "scripts/training/train_all_assets.py uses the legacy feature pipeline "
    "(features.builder). Use retrain_all_fixed.py instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from features.builder import compute_macro_derived, compute_training_data, model_path  # noqa: E402
from features.registry import FEATURE_REGISTRY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_all")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE, "paper_trading", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

TICKERS = list(FEATURE_REGISTRY.keys())


def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Open": "open", "Volume": "volume"})


def _norm_index(df):
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("US/Eastern")
    else:
        df.index = df.index.tz_localize("US/Eastern")
    return df


def fetch_history(ticker, years=10):
    end = pd.Timestamp.now()
    start = f"{end.year - years}-01-01"
    df = yf.download(ticker, start=start, end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
    df = _flatten(df)
    df = _norm_index(df)
    return df


def evaluate_model(model, X_test, y_test):
    from sklearn.metrics import accuracy_score, log_loss

    y_pred = model.predict(X_test)
    proba = model.predict_proba(X_test)
    try:
        ll = log_loss(y_test, proba, labels=[0, 1, 2])
    except ValueError:
        ll = float("nan")
    return accuracy_score(y_test, y_pred), ll


def train_one(ticker, macro, ref, force=False):
    contract = FEATURE_REGISTRY[ticker]
    mp = model_path(ticker)
    if os.path.exists(mp) and not force:
        model = xgb.XGBClassifier()
        model.load_model(mp)
        logger.info("  %s: loaded cached model", ticker)
        return model, None

    logger.info("  %s: downloading history...", ticker)
    df = fetch_history(ticker)
    X, y, contract = compute_training_data(ticker, macro, ref, df)
    logger.info("  %s: %d feature rows, features=%s", ticker, len(X), contract.features)

    if len(X) < 200:
        logger.warning("  %s: insufficient data (%d rows), skipping", ticker, len(X))
        return None, None

    end_date = X.index[-1]
    start_date = end_date - pd.DateOffset(years=5)
    mask = X.index >= start_date
    X_train, y_train = X[mask], y[mask]
    if len(X_train) < 200:
        X_train, y_train = X, y

    split = int(len(X_train) * 0.8)
    X_tr, y_tr = X_train.iloc[:split], y_train.iloc[:split]
    # Ensure all 3 classes are present in training split
    present = set(y_tr.unique())
    if present != {0, 1, 2}:
        dummy = pd.DataFrame({c: [0.0] for c in X_tr.columns}, index=pd.RangeIndex(1))
        missing = [c for c in [0, 1, 2] if c not in present]
        for m in missing:
            X_tr = pd.concat([dummy, X_tr], ignore_index=True)
            y_tr = pd.concat([pd.Series([m]), y_tr], ignore_index=True)

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=2,
        learning_rate=0.02,
        objective="multi:softprob",
        num_class=3,
        random_state=42,
        n_jobs=1,
        tree_method="hist",
        verbosity=0,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_train.iloc[split:], y_train.iloc[split:])], verbose=False)

    acc, ll = evaluate_model(model, X_train.iloc[split:], y_train.iloc[split:])
    logger.info("  %s: val acc=%.4f logloss=%.4f", ticker, acc, ll)

    model.save_model(mp)
    return model, {"accuracy": acc, "logloss": ll, "n_train": len(X_train), "n_test": len(X_train) - split}


def main():
    logger.info("Loading macro data...")
    macro = load_macro_data()
    ref = fetch_history("SPY", years=10)

    results = []
    for ticker in TICKERS:
        try:
            model, stats = train_one(ticker, macro, ref, force=True)
            if stats:
                stats["ticker"] = ticker
                stats["name"] = FEATURE_REGISTRY[ticker].name
                stats["features"] = ",".join(FEATURE_REGISTRY[ticker].features)
                results.append(stats)
                logger.info("  ✓ %s: acc=%.4f logloss=%.4f", ticker, stats["accuracy"], stats["logloss"])
            else:
                logger.warning("  ✗ %s: failed (no data)", ticker)
        except Exception as e:  # noqa: BLE001
            logger.error("  ✗ %s: error: %s", ticker, e)
            import traceback

            traceback.print_exc()

    if results:
        df = pd.DataFrame(results).sort_values("accuracy", ascending=False)
        print("\n" + "=" * 80)
        print("TRAINING SUMMARY (sorted by validation accuracy)")
        print("=" * 80)
        for _, r in df.iterrows():
            print(
                f"  {r['ticker']:20s}  acc={r['accuracy']:.4f}  logloss={r['logloss']:.4f}  "
                f"n_train={r['n_train']:5d}  features={r['features']}"
            )
        print(f"\nAverage accuracy: {df['accuracy'].mean():.4f}")
        print(f"Average logloss: {df['logloss'].mean():.4f}")
        print(f"Trained {len(df)}/{len(TICKERS)} assets")
        df.to_csv(os.path.join(BASE, "data", "processed", "training_results.csv"), index=False)
        logger.info("Results saved to data/processed/training_results.csv")
    else:
        print("No models trained.")


def load_macro_data():
    m = pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet"))
    return compute_macro_derived(m)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Legacy training script (deprecated)")
    parser.add_argument("--allow-legacy", action="store_true", help="Run despite deprecation")
    args = parser.parse_args()
    if not args.allow_legacy:
        sys.exit(
            "This script is deprecated (uses legacy features.builder). "
            "Use retrain_all_fixed.py instead, or pass --allow-legacy to force execution."
        )
    main()
