import hashlib
import json
import logging
import os
import pickle
import sys
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
import xgboost as xgb
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from features.builder import compute_macro_derived, compute_training_data
from features.registry import FEATURE_REGISTRY
from shared.model import XGBoostModel
from backtests.model_comparator import (
    compare_models,
    compare_signals,
    compare_portfolio,
    compare_shadow_intel,
    build_summary,
    classify_regime,
)
from backtests.forward_test import run_forward_test
from backtests.mas import compute_mas
from backtests.model_evolution import append_trajectory, print_equilibrium_report, load_trajectory, compute_mas_velocity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quantforge.sandbox_retrain")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_BASE = os.path.join(BASE, "data", "sandbox")
TICKERS = list(FEATURE_REGISTRY.keys())


@dataclass
class DataLock:
    ticker: str
    date: str
    n_rows: int
    n_features: int
    feature_names: tuple
    index_hash: str
    index_start: str
    index_end: str

    def verify(self, df: pd.DataFrame) -> bool:
        if len(df) != self.n_rows:
            return False
        actual_hash = hashlib.md5(str(list(df.index)).encode()).hexdigest()
        return actual_hash == self.index_hash


def compute_data_lock(df: pd.DataFrame, ticker: str) -> DataLock:
    return DataLock(
        ticker=ticker,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        n_rows=len(df),
        n_features=len(df.columns),
        feature_names=tuple(df.columns.tolist()),
        index_hash=hashlib.md5(str(list(df.index)).encode()).hexdigest(),
        index_start=str(df.index[0]) if len(df) > 0 else "",
        index_end=str(df.index[-1]) if len(df) > 0 else "",
    )


def load_macro_data():
    path = os.path.join(BASE, "data", "processed", "macro_factors.parquet")
    m = pd.read_parquet(path)
    return compute_macro_derived(m)


def fetch_history(ticker, years=15):
    end = pd.Timestamp.now()
    start = f"{end.year - years}-01-01"
    df = yf.download(ticker, start=start, end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Open": "open", "Volume": "volume"})
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("US/Eastern")
    else:
        df.index = df.index.tz_localize("US/Eastern")
    return df


def load_production_model(ticker: str):
    contract = FEATURE_REGISTRY[ticker]
    path = os.path.join(BASE, "paper_trading", "models", f"{contract.name}_model.pkl")
    if not os.path.exists(path):
        logger.warning("  %s: no production model at %s", ticker, path)
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def sandbox_model_path(ticker: str, version: Optional[str] = None) -> str:
    contract = FEATURE_REGISTRY[ticker]
    asset_dir = os.path.join(SANDBOX_BASE, contract.name, "models")
    os.makedirs(asset_dir, exist_ok=True)
    if version:
        return os.path.join(asset_dir, f"{version}.pkl")
    return os.path.join(asset_dir, f"{contract.name}_sandbox.pkl")


def train_sandbox_model(
    ticker: str,
    macro: pd.DataFrame,
    ref: pd.DataFrame,
    force: bool = False,
    version: Optional[str] = None,
):
    out = sandbox_model_path(ticker, version)
    if os.path.exists(out) and not force:
        logger.info("  %s: using cached sandbox model", ticker)
        with open(out, "rb") as f:
            return pickle.load(f)

    contract = FEATURE_REGISTRY[ticker]
    df = fetch_history(ticker)
    X, y, _ = compute_training_data(ticker, macro, ref, df)
    logger.info("  %s: %d feature rows, features=%s", ticker, len(X), contract.features)

    if len(X) < 200:
        logger.warning("  %s: insufficient data (%d rows)", ticker, len(X))
        return None

    end_date = X.index[-1]
    start_date = end_date - pd.DateOffset(years=5)
    mask = X.index >= start_date
    X_train, y_train = X[mask], y[mask]
    if len(X_train) < 200:
        X_train, y_train = X, y

    split = int(len(X_train) * 0.8)
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=2, learning_rate=0.02,
        objective="multi:softprob", num_class=3,
        random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
    )
    model.fit(
        X_train.iloc[:split], y_train.iloc[:split],
        eval_set=[(X_train.iloc[split:], y_train.iloc[split:])],
        verbose=False,
    )

    with open(out, "wb") as f:
        pickle.dump(model, f)
    logger.info("  %s: sandbox model saved to %s", ticker, out)
    return model


def run_one_asset(
    ticker: str,
    macro: pd.DataFrame,
    ref: pd.DataFrame,
    force: bool = False,
    production_model=None,
    sandbox_model=None,
) -> dict:
    contract = FEATURE_REGISTRY[ticker]
    name = contract.name

    logger.info("=" * 60)
    logger.info("Asset: %s (%s)", ticker, name)
    logger.info("=" * 60)

    df = fetch_history(ticker)
    X, y, _ = compute_training_data(ticker, macro, ref, df)

    if len(X) < 200:
        msg = f"Insufficient data for {ticker} ({len(X)} rows)"
        logger.warning(msg)
        return {"ticker": ticker, "name": name, "error": msg}

    data_lock = compute_data_lock(X, ticker)
    lock_path = os.path.join(SANDBOX_BASE, name, "data_lock.json")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as f:
        json.dump(asdict(data_lock), f, indent=2, default=str)

    if production_model is None:
        production_model = load_production_model(ticker)
    if sandbox_model is None:
        sandbox_model = train_sandbox_model(ticker, macro, ref, force=force)

    if production_model is None or sandbox_model is None:
        return {"ticker": ticker, "name": name, "error": "model load/train failure"}

    close = df["close"].reindex(X.index).ffill()

    predict_fn = lambda m, x: XGBoostModel().predict(m, x)

    logger.info("  Model comparison...")
    model_result = compare_models(production_model, sandbox_model, X, y, predict_fn=predict_fn)

    logger.info("  Signal comparison...")
    signal_result = compare_signals(production_model, sandbox_model, X, close, predict_fn=predict_fn)

    logger.info("  Portfolio simulation...")
    portfolio_result = compare_portfolio(production_model, sandbox_model, X, close, predict_fn=predict_fn)

    logger.info("  Shadow intelligence...")
    shadow_result = compare_shadow_intel(production_model, sandbox_model, X, close, asset=name, predict_fn=predict_fn)

    logger.info("  Walk-forward test...")
    forward_result = run_forward_test(ticker, X, y, close, production_model, forward_months=6, predict_fn=predict_fn)

    logger.info("  Building summary...")
    summary = build_summary(model_result, signal_result, portfolio_result, shadow_result)

    logger.info("  Computing Model Acceptance Score...")
    mas_result = compute_mas(model_result, signal_result, portfolio_result, shadow_result, forward_result)

    append_trajectory(
        asset=name,
        mas=mas_result.get("mas", 0),
        delta_mas=mas_result.get("delta_mas", 0),
        decision=mas_result.get("decision", "N/A"),
        sub_scores=mas_result.get("sub_scores", {}),
        forward_result=forward_result,
    )
    traj = load_trajectory(name)
    velocities = compute_mas_velocity(traj, window=3)
    vel_str = f"∇={velocities[-1]:+.4f}" if velocities else ""
    logger.info("  %s MAS gradient: %s", name, vel_str)

    result = {
        "ticker": ticker,
        "name": name,
        "date": datetime.now().isoformat(),
        "data_lock": asdict(data_lock),
        "model_comparison": model_result,
        "signal_comparison": signal_result,
        "portfolio_comparison": portfolio_result,
        "shadow_intel": shadow_result,
        "forward_test": forward_result,
        "mas": mas_result,
        "summary": summary,
    }

    result_path = os.path.join(SANDBOX_BASE, name, "comparison.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("  Results saved to %s", result_path)

    log_verdict(name, model_result, signal_result, portfolio_result, shadow_result, summary)
    log_mas(name, mas_result)
    return result


def log_verdict(name, model_res, signal_res, portfolio_res, shadow_res, summary):
    logger.info("─" * 50)
    logger.info("VERDICT for %s: %s", name, summary["verdict"])
    for c in summary["checks"]:
        status = "✓" if c["pass"] else "✗"
        logger.info("  %s %s = %s", status, c["check"], c["value"])
    if "error" not in model_res:
        mr = model_res
        logger.info("  accuracy: old=%.4f new=%.4f", mr.get("old", {}).get("accuracy", 0), mr.get("new", {}).get("accuracy", 0))
    if "error" not in signal_res:
        sr = signal_res
        logger.info("  signal agreement=%.4f flips=%d", sr.get("overall_agreement", 0), sr.get("total_flips", 0))
    if "error" not in portfolio_res:
        pr = portfolio_res
        logger.info("  return: old=%.4f new=%.4f delta=%.4f",
                     pr.get("old", {}).get("total_return", 0),
                     pr.get("new", {}).get("total_return", 0),
                     pr.get("delta", {}).get("return_diff", 0))
    logger.info("─" * 50)


def log_mas(name, mas_result):
    if not mas_result:
        return
    logger.info("─" * 50)
    logger.info("MAS for %s: %.2f | %s", name, mas_result.get("mas", 0), mas_result.get("decision", "N/A"))
    if mas_result.get("gate_failures"):
        for f in mas_result["gate_failures"]:
            logger.info("  ✗ %s", f)
    ss = mas_result.get("sub_scores", {})
    if ss:
        logger.info("  model=%.4f  signal=%.4f  portfolio=%.4f  shadow=%.4f  forward=%.4f  stress=%.4f",
                     ss.get("model", 0), ss.get("signal", 0), ss.get("portfolio", 0),
                     ss.get("shadow", 0), ss.get("forward", 0), ss.get("stress", 0))
    delta = mas_result.get("delta_mas")
    if delta is not None:
        logger.info("  ΔMAS = %+.2f", delta)
    logger.info("─" * 50)


def main(force: bool = False, target_assets: Optional[list] = None):
    logger.info("Loading macro data...")
    macro = load_macro_data()
    ref = fetch_history("SPY", years=15)

    targets = target_assets if target_assets else TICKERS
    results = []

    for ticker in targets:
        if ticker not in FEATURE_REGISTRY:
            logger.warning("Unknown ticker: %s, skipping", ticker)
            continue
        try:
            r = run_one_asset(ticker, macro, ref, force=force)
            results.append(r)
        except Exception as e:
            logger.error("Fatal error for %s: %s", ticker, e)
            import traceback; traceback.print_exc()

    summary_path = os.path.join(SANDBOX_BASE, "summary.json")
    overview = []
    for r in results:
        mas_r = r.get("mas", {})
        overview.append({
            "ticker": r.get("ticker"),
            "name": r.get("name"),
            "verdict": r.get("summary", {}).get("verdict", "ERROR"),
            "accuracy_old": r.get("model_comparison", {}).get("old", {}).get("accuracy"),
            "accuracy_new": r.get("model_comparison", {}).get("new", {}).get("accuracy"),
            "signal_agreement": r.get("signal_comparison", {}).get("overall_agreement"),
            "flip_rate": r.get("signal_comparison", {}).get("flip_rate"),
            "return_old": r.get("portfolio_comparison", {}).get("old", {}).get("total_return"),
            "return_new": r.get("portfolio_comparison", {}).get("new", {}).get("total_return"),
            "entropy_shift": r.get("shadow_intel", {}).get("entropy_shift"),
            "mas": mas_r.get("mas"),
            "delta_mas": mas_r.get("delta_mas"),
            "mas_decision": mas_r.get("decision"),
            "mas_sub_scores": mas_r.get("sub_scores"),
        })

    with open(summary_path, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "assets": overview}, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("SANDBOX RETRAINING SUMMARY")
    print("=" * 80)
    for a in overview:
        verdict = a["verdict"]
        acc_old = a.get("accuracy_old") or 0
        acc_new = a.get("accuracy_new") or 0
        agree = a.get("signal_agreement") or 0
        ret_old = a.get("return_old") or 0
        ret_new = a.get("return_new") or 0
        mas = a.get("mas")
        mas_d = a.get("mas_decision", "")
        if mas is not None:
            print(f'  {a["name"]:10s} [{verdict:5s}]  MAS={mas:6.2f} ({mas_d:15s})  '
                  f'acc: {acc_old:.4f}→{acc_new:.4f}  agree: {agree:.4f}')
        else:
            print(f'  {a["name"]:10s} [{verdict:5s}]  MAS=  REJECTED                '
                  f'acc: {acc_old:.4f}→{acc_new:.4f}  agree: {agree:.4f}')
    print(f"\nResults saved to {summary_path}")
    print_equilibrium_report()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sandbox model retraining and comparison")
    parser.add_argument("--force", action="store_true", help="Retrain even if cached model exists")
    parser.add_argument("--assets", nargs="+", help="Specific assets to retrain (default: all)")
    args = parser.parse_args()
    main(force=args.force, target_assets=args.assets)
