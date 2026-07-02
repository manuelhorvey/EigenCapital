import hashlib
import json
import logging
import os
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
from backtests import compute_per_fold_labels
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
from backtests.model_promotion_engine import evaluate_promotion
from backtests.adversarial_manifold import evaluate_adversarial_manifold

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.sandbox_retrain")

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
    path = os.path.join(BASE, "paper_trading", "models", f"{contract.name}_model.json")
    if not os.path.exists(path):
        logger.warning("  %s: no production model at %s", ticker, path)
        return None
    model = xgb.XGBClassifier()
    model.load_model(path)
    return model


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
    X, y, _ = compute_training_data(ticker, macro, ref, df, compute_labels=False)
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

    y_vals = set(y_train.unique())
    if y_vals != {0, 1, 2}:
        logger.warning("  %s: training labels only %s — need all 3 classes, skipping", ticker, sorted(y_vals))
        return None
    from sklearn.model_selection import train_test_split

    min_class_count = y_train.value_counts().min()
    strat = y_train if min_class_count >= 2 else None
    X_tr, X_ev, y_tr, y_ev = train_test_split(
        X_train,
        y_train,
        test_size=0.2,
        random_state=42,
        stratify=strat,
    )
    if set(y_tr.unique()) != {0, 1, 2}:
        logger.warning("  %s: train split has only classes %s — skipping", ticker, sorted(set(y_tr.unique())))
        return None
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
    model.fit(
        X_tr,
        y_tr,
        eval_set=[(X_ev, y_ev)],
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
    X, y, _ = compute_training_data(ticker, macro, ref, df, compute_labels=False)

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

    logger.info("  Adversarial manifold projection...")
    manifold = evaluate_adversarial_manifold(
        asset=name,
        model=sandbox_model,
        X=X,
        close=close,
        predict_fn=predict_fn,
    )
    logger.info("  %s CMSS=%.4f class=%s", name, manifold.get("cmss", 0), manifold.get("stability_class", "N/A"))

    # ── Observe-only expectations for statistical sub-checks ──
    # If results diverge from below, investigate wiring (not asset quality):
    #   CADCHF, AUDUSD, NZDCHF: should clear all three (PSR≥0.95, n≥MinTRL, CRS≥0.70)
    #   USDCAD, NZDUSD: should fail PSR (both negative Sharpe per portfolio backtest)
    #   ^DJI, ES, NQ: should clear PSR due to SELL_ONLY filter (are net-positive)
    #   EURAUD: weakest evidence asset — pass/fail is informative either way
    logger.info("  Evaluating promotion protocol...")
    promotion = evaluate_promotion(
        asset=name,
        mas_result=mas_result,
        forward_result=forward_result,
        model_result=model_result,
        signal_result=signal_result,
        portfolio_result=portfolio_result,
        shadow_result=shadow_result,
        trajectory=traj,
    )
    log_promotion(name, promotion)

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
        "adversarial_manifold": manifold,
        "promotion": promotion,
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
        logger.info(
            "  accuracy: old=%.4f new=%.4f", mr.get("old", {}).get("accuracy", 0), mr.get("new", {}).get("accuracy", 0)
        )
    if "error" not in signal_res:
        sr = signal_res
        logger.info("  signal agreement=%.4f flips=%d", sr.get("overall_agreement", 0), sr.get("total_flips", 0))
    if "error" not in portfolio_res:
        pr = portfolio_res
        logger.info(
            "  return: old=%.4f new=%.4f delta=%.4f",
            pr.get("old", {}).get("total_return", 0),
            pr.get("new", {}).get("total_return", 0),
            pr.get("delta", {}).get("return_diff", 0),
        )
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
        logger.info(
            "  model=%.4f  signal=%.4f  portfolio=%.4f  shadow=%.4f  forward=%.4f  stress=%.4f",
            ss.get("model", 0),
            ss.get("signal", 0),
            ss.get("portfolio", 0),
            ss.get("shadow", 0),
            ss.get("forward", 0),
            ss.get("stress", 0),
        )
    delta = mas_result.get("delta_mas")
    if delta is not None:
        logger.info("  ΔMAS = %+.2f", delta)
    logger.info("─" * 50)


def log_promotion(name, promotion):
    if not promotion:
        return
    logger.info("─" * 50)
    logger.info(
        "PROMOTION for %s: %s | cond=%s | conf=%.2f",
        name,
        promotion.get("decision", "N/A"),
        promotion.get("conditions_met", "?"),
        promotion.get("confidence", 0),
    )
    for fm in promotion.get("failure_modes", []):
        logger.info("  ⚠ %s", fm)
    logger.info("  action: %s", promotion.get("recommended_action", "?"))
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
            import traceback

            traceback.print_exc()

    summary_path = os.path.join(SANDBOX_BASE, "summary.json")
    overview = []
    for r in results:
        mas_r = r.get("mas", {})
        prom = r.get("promotion", {})
        overview.append(
            {
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
                "promotion_decision": prom.get("decision"),
                "promotion_confidence": prom.get("confidence"),
                "promotion_conditions": prom.get("conditions_met"),
                "promotion_action": prom.get("recommended_action"),
            }
        )

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
            print(
                f"  {a['name']:10s} [{verdict:5s}]  MAS={mas:6.2f} ({mas_d:15s})  "
                f"acc: {acc_old:.4f}→{acc_new:.4f}  agree: {agree:.4f}"
            )
        else:
            print(
                f"  {a['name']:10s} [{verdict:5s}]  MAS=  REJECTED                "
                f"acc: {acc_old:.4f}→{acc_new:.4f}  agree: {agree:.4f}"
            )
    print(f"\nResults saved to {summary_path}")
    print_equilibrium_report()


def augment_features(
    X: pd.DataFrame,
    ticker: str,
    macro: pd.DataFrame,
    ref: pd.DataFrame,
    df: pd.DataFrame,
    close: pd.Series,
) -> pd.DataFrame:
    contract = FEATURE_REGISTRY[ticker]
    name = contract.name
    aug = X.copy()
    pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in X.index])
    m = macro.reindex(pi, method="ffill")
    m.index = X.index
    c = close.reindex(X.index)
    slug = name.lower()

    if name in ("GC", "BTC", "CADJPY", "NZDJPY", "USDCAD", "EURAUD"):
        aug["vix_delta_5"] = m["vix_delta_5"]
        aug["dxy_mom_21"] = m["dxy_mom_21"]

    if name == "BTC":
        aug["vix_ma21"] = m["vix_ma21"]
        aug[f"{slug}_mom_10"] = c.pct_change(10)
        aug[f"{slug}_mom_21"] = c.pct_change(21)
        ref_c = ref["close"].reindex(X.index)
        spy_mom_21 = ref_c.pct_change(21)
        aug["btc_vs_spy_21"] = aug["btc_mom_21"] - spy_mom_21

    elif name == "CADJPY":
        aug["us_jp_10y_spread"] = m["us_jp_10y_spread"]
        aug["ca_jp_10y_spread"] = m["ca_jp_10y_spread"]
        aug[f"{slug}_mom_63"] = c.pct_change(63)
        aug[f"{slug}_mom_10"] = c.pct_change(10)

    elif name == "GC":
        aug["vix_ma21"] = m["vix_ma21"]
        aug[f"{slug}_mom_21"] = c.pct_change(21)

    elif name == "NZDJPY":
        aug[f"{slug}_mom_63"] = c.pct_change(63)

    elif name == "USDCAD":
        aug[f"{slug}_mom_63"] = c.pct_change(63)

    elif name == "EURAUD":
        aug[f"{slug}_mom_63"] = c.pct_change(63)
        aug["vix_ma21"] = m["vix_ma21"]

    return aug.dropna(how="any")


def run_historical(
    force: bool = False, target_assets: Optional[list] = None, augmented: bool = False, tb20_cadjpy: bool = False
):
    logger.info("Loading macro data...")
    macro = load_macro_data()
    ref = fetch_history("SPY", years=15)
    targets = target_assets if target_assets else TICKERS
    now = pd.Timestamp.now()
    test_years = [now.year - i for i in range(1, 6) if now.year - i >= 2016][::-1]

    all_results = {}
    for ticker in targets:
        if ticker not in FEATURE_REGISTRY:
            continue
        contract = FEATURE_REGISTRY[ticker]
        name = contract.name
        logger.info("=" * 60)
        logger.info(
            "Historical: %s (%s) — %d yearly windows%s",
            ticker,
            name,
            len(test_years),
            " [AUGMENTED]" if augmented else "",
        )
        if tb20_cadjpy and name == "CADJPY":
            from features.contract import FeatureContract

            contract = FeatureContract(
                ticker=ticker,
                name=name,
                label_type="tb20",
                label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
                macro_filters=contract.macro_filters,
                price_mom_windows=contract.price_mom_windows,
                vs_spy_windows=contract.vs_spy_windows,
            )
            logger.info("  %s: using tb20 labels (pt_sl=[2,2], vb=20) instead of fwd60", name)
        logger.info("=" * 60)
        df = fetch_history(ticker)
        from features.builder import build_features

        features_df = build_features(df, macro, ref, contract, compute_labels=False)
        X = features_df[list(contract.features)]
        close = df["close"].reindex(X.index).ffill()
        if len(X) < 200:
            logger.warning("  %s: insufficient data", ticker)
            continue
        if augmented:
            X_aug = augment_features(X, ticker, macro, ref, df, close)
            logger.info(
                "  %s: augmented %d features → %d features (%d rows)", name, X.shape[1], X_aug.shape[1], len(X_aug)
            )
            X = X_aug
            close = close.reindex(X.index).ffill()
        if len(X) < 200:
            logger.warning("  %s: insufficient data after augmentation", ticker)
            continue
        predict_fn = lambda m, x: XGBoostModel().predict(m, x)
        year_results = []
        for ty in test_years:
            cutoff = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
            end_of_year = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
            train_mask = X.index < cutoff
            test_mask = (X.index >= cutoff) & (X.index <= end_of_year)
            if test_mask.sum() < 30:
                logger.info("  %s %d: too few test rows (%d), skipping", name, ty, int(test_mask.sum()))
                continue
            X_train_hist = X[train_mask]
            y_train_hist, y_test = compute_per_fold_labels(close, train_mask, test_mask, contract)
            X_test = X[test_mask]
            close_test = close[test_mask]
            if len(X_train_hist) < 200:
                logger.info("  %s %d: insufficient train data (%d), skipping", name, ty, len(X_train_hist))
                continue
            from sklearn.model_selection import train_test_split

            y_vals = set(y_train_hist.unique())
            if y_vals != {0, 1, 2}:
                logger.info("  %s %d: skipping — train labels only %s, need all 3 classes", name, ty, sorted(y_vals))
                continue
            min_class_count = y_train_hist.value_counts().min()
            strat = y_train_hist if min_class_count >= 2 else None
            X_tr, X_ev, y_tr, y_ev = train_test_split(
                X_train_hist,
                y_train_hist,
                test_size=0.2,
                random_state=42,
                stratify=strat,
            )
            # After-split guard: training must have all 3 classes for multi:softprob
            if set(y_tr.unique()) != {0, 1, 2}:
                logger.info("  %s %d: skipping — train split labels only %s", name, ty, sorted(set(y_tr.unique())))
                continue
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
            model.fit(
                X_tr,
                y_tr,
                eval_set=[(X_ev, y_ev)],
                verbose=False,
            )
            from backtests.forward_test import _forward_metrics, _regime_metrics, _classify_vol_regime
            from sklearn.metrics import accuracy_score

            proba = predict_fn(model, X_test)
            max_probs = proba.max(axis=1)
            pct_above_045 = float((max_probs > 0.45).mean())
            pct_above_033 = float((max_probs > 0.33).mean())
            class_dist = [float((proba.argmax(axis=1) == c).mean()) for c in range(3)]
            logger.info(
                "  %s %d: max_p=%.3f >0.45=%.1f%% >0.33=%.1f%% dist=[%.2f %.2f %.2f]",
                name,
                ty,
                float(max_probs.mean()),
                pct_above_045 * 100,
                pct_above_033 * 100,
                class_dist[0],
                class_dist[1],
                class_dist[2],
            )
            fwd = _forward_metrics(proba, close_test)
            yr_regime = _classify_vol_regime(close_test)
            reg = _regime_metrics(proba, close_test, yr_regime)
            acc = accuracy_score(y_test, proba.argmax(axis=1))
            year_results.append(
                {
                    "year": ty,
                    "n_train": len(X_train_hist),
                    "n_test": len(X_test),
                    "accuracy": round(float(acc), 4),
                    "sharpe": fwd["sharpe"],
                    "hit_rate": fwd["hit_rate"],
                    "max_drawdown": fwd["max_drawdown"],
                    "stability": fwd["stability"],
                    "regime_metrics": reg,
                }
            )
        if year_results:
            all_results[name] = year_results
    if not all_results:
        logger.warning("No historical results generated.")
        return
    suffix = "_augmented" if augmented else ""
    if tb20_cadjpy:
        suffix += "_tb20"
    out_dir = os.path.join(SANDBOX_BASE, "historical")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"historical_results{suffix}.json")
    with open(out_path, "w") as f:
        json.dump({"test_years": test_years, "assets": all_results, "augmented": augmented}, f, indent=2, default=str)
    label = "5-YEAR HISTORICAL WALK-FORWARD RESULTS"
    if augmented:
        label += " (AUGMENTED)"
    if tb20_cadjpy:
        label += " + TB20 CADJPY"
    print("\n" + "=" * 100)
    print(label)
    print("=" * 100)
    for name, yrs in sorted(all_results.items()):
        avg_sharpe = float(np.mean([y["sharpe"] for y in yrs]))
        avg_hit = float(np.mean([y["hit_rate"] for y in yrs]))
        avg_dd = float(np.mean([y["max_drawdown"] for y in yrs]))
        avg_acc = float(np.mean([y["accuracy"] for y in yrs]))
        pos_windows = sum(1 for y in yrs if y["sharpe"] > 0)
        years_str = "  ".join(
            f"{y['year']}: S={y['sharpe']:.2f} H={y['hit_rate']:.2f} DD={y['max_drawdown']:.3f}" for y in yrs
        )
        print(
            f"\n  {name:10s}  avg(S)={avg_sharpe:.2f}  avg(H)={avg_hit:.2f}  "
            f"avg(DD)={avg_dd:.3f}  avg(acc)={avg_acc:.4f}  "
            f"pos_windows={pos_windows}/{len(yrs)}"
        )
        print(f"  {' ' * 10}  {years_str}")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sandbox model retraining and comparison")
    parser.add_argument("--force", action="store_true", help="Retrain even if cached model exists")
    parser.add_argument("--assets", nargs="+", help="Specific assets to retrain (default: all)")
    parser.add_argument("--historical", action="store_true", help="Run 5-year historical walk-forward evaluation")
    parser.add_argument("--augmented", action="store_true", help="Use augmented feature set on weak assets")
    parser.add_argument("--tb20", action="store_true", help="Switch CADJPY to tb20 labels (like NZDJPY)")
    args = parser.parse_args()
    if args.historical:
        run_historical(force=args.force, target_assets=args.assets, augmented=args.augmented, tb20_cadjpy=args.tb20)
    else:
        main(force=args.force, target_assets=args.assets)
