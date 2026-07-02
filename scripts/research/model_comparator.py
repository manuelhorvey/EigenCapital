import logging
import os
from typing import Optional, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.model_comparator")


def classify_regime(close: pd.Series) -> pd.Series:
    returns = np.log(close / close.shift(1)).dropna()
    vol = returns.rolling(20).std() * np.sqrt(252)
    vol_pct = vol.rank(pct=True)
    vol_pct = vol_pct.reindex(close.index)
    regime = pd.Series("transition", index=close.index)
    regime[vol_pct < 0.33] = "low_vol"
    regime[vol_pct > 0.67] = "high_vol"
    return regime.ffill()


def _compute_signals(
    proba: np.ndarray,
    index: pd.Index,
    threshold: float = 0.45,
) -> pd.DataFrame:
    probs_long = proba[:, 2]
    probs_short = proba[:, 0]
    signals = pd.Series(0, index=index)
    signals[probs_long > threshold] = 2
    signals[probs_short > threshold] = 0
    return pd.DataFrame({
        "signal": signals,
        "prob_long": probs_long,
        "prob_short": probs_short,
        "prob_neutral": proba[:, 1],
    }, index=index)


def compare_models(
    old_model,
    new_model,
    X: pd.DataFrame,
    y: Optional[pd.Series] = None,
    predict_fn: Optional[Callable] = None,
) -> dict:
    try:
        if predict_fn is None:
            predict_fn = lambda m, x: m.predict_proba(x)

        old_proba = predict_fn(old_model, X)
        new_proba = predict_fn(new_model, X)

        result: dict = {"n_samples": len(X)}

        if y is not None:
            from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
            labels = sorted(y.unique())
            result["old"] = {
                "accuracy": round(float(accuracy_score(y, np.argmax(old_proba, axis=1))), 4),
                "logloss": round(float(log_loss(y, old_proba, labels=labels)), 4),
            }
            result["new"] = {
                "accuracy": round(float(accuracy_score(y, np.argmax(new_proba, axis=1))), 4),
                "logloss": round(float(log_loss(y, new_proba, labels=labels)), 4),
            }
            try:
                result["old"]["auc_macro"] = round(float(roc_auc_score(y, old_proba, multi_class="ovr", labels=labels)), 4)
                result["new"]["auc_macro"] = round(float(roc_auc_score(y, new_proba, multi_class="ovr", labels=labels)), 4)
            except Exception:
                pass

        old_class_dist = np.bincount(np.argmax(old_proba, axis=1), minlength=3) / len(old_proba)
        new_class_dist = np.bincount(np.argmax(new_proba, axis=1), minlength=3) / len(new_proba)
        result["class_distribution"] = {
            "old": {"short": round(float(old_class_dist[0]), 4), "neutral": round(float(old_class_dist[1]), 4), "long": round(float(old_class_dist[2]), 4)},
            "new": {"short": round(float(new_class_dist[0]), 4), "neutral": round(float(new_class_dist[1]), 4), "long": round(float(new_class_dist[2]), 4)},
        }

        return result
    except Exception as e:
        logger.error("compare_models failed: %s", e)
        return {"n_samples": 0, "error": str(e)}


def compare_signals(
    old_model,
    new_model,
    X: pd.DataFrame,
    close: pd.Series,
    threshold: float = 0.45,
    predict_fn: Optional[Callable] = None,
) -> dict:
    try:
        if predict_fn is None:
            predict_fn = lambda m, x: m.predict_proba(x)

        old_proba = predict_fn(old_model, X)
        new_proba = predict_fn(new_model, X)

        old_sig = _compute_signals(old_proba, X.index, threshold)
        new_sig = _compute_signals(new_proba, X.index, threshold)

        old_final = old_sig["signal"].iloc[-1]
        new_final = new_sig["signal"].iloc[-1]
        final_agreement = old_final == new_final
        final_type_old = "BUY" if old_final == 2 else ("SELL" if old_final == 0 else "FLAT")
        final_type_new = "BUY" if new_final == 2 else ("SELL" if new_final == 0 else "FLAT")

        agreement = (old_sig["signal"] == new_sig["signal"]).mean()
        flips = ((old_sig["signal"] != new_sig["signal"])).sum()

        old_conf = old_sig[["prob_long", "prob_short"]].max(axis=1)
        new_conf = new_sig[["prob_long", "prob_short"]].max(axis=1)
        mean_conf_shift = float((new_conf - old_conf).mean())

        regime = classify_regime(close).reindex(X.index).ffill()

        regime_agreement = {}
        for r in ["low_vol", "high_vol", "transition"]:
            mask = (regime == r).values
            if mask.sum() > 0:
                reg_agree = (old_sig["signal"].values[mask] == new_sig["signal"].values[mask]).mean()
                regime_agreement[r] = round(float(reg_agree), 4)

        return {
            "n_samples": len(X),
            "overall_agreement": round(float(agreement), 4),
            "total_flips": int(flips),
            "flip_rate": round(float(flips / len(X)), 4),
            "final_signal_old": final_type_old,
            "final_signal_new": final_type_new,
            "final_agreement": bool(final_agreement),
            "mean_confidence_shift": round(mean_conf_shift, 4),
            "regime_stratified_agreement": regime_agreement,
        }
    except Exception as e:
        logger.error("compare_signals failed: %s", e)
        return {"n_samples": 0, "error": str(e)}


def compare_portfolio(
    old_model,
    new_model,
    X: pd.DataFrame,
    close: pd.Series,
    initial_capital: float = 100000.0,
    threshold: float = 0.45,
    position_size: float = 0.95,
    predict_fn: Optional[Callable] = None,
) -> dict:
    try:
        if predict_fn is None:
            predict_fn = lambda m, x: m.predict_proba(x)

        old_proba = predict_fn(old_model, X)
        new_proba = predict_fn(new_model, X)

        def simulate(proba: np.ndarray) -> dict:
            sig = _compute_signals(proba, X.index, threshold)
            capital = float(initial_capital)
            peak = float(initial_capital)
            trades = 0
            pos = 0
            entry_price = 0.0

            for i in range(1, len(sig)):
                prev_s = sig["signal"].iloc[i - 1]
                curr_s = sig["signal"].iloc[i]
                curr_close = float(close.iloc[i])
                prev_close = float(close.iloc[i - 1])

                if pos != 0 and curr_s != prev_s:
                    ret = (curr_close / entry_price - 1) if pos == 2 else (entry_price / curr_close - 1)
                    pnl = capital * ret * position_size
                    capital += pnl
                    trades += 1
                    pos = 0

                if pos == 0 and curr_s != 0:
                    pos = int(curr_s)
                    entry_price = float(curr_close)

            ret = (capital - initial_capital) / initial_capital
            dd = (capital - peak) / peak if peak > 0 else 0
            return {
                "final_capital": round(capital, 2),
                "total_return": round(float(ret), 4),
                "total_trades": trades,
                "max_drawdown": round(float(dd), 4),
            }

        old_result = simulate(old_proba)
        new_result = simulate(new_proba)

        return {
            "initial_capital": initial_capital,
            "old": old_result,
            "new": new_result,
            "delta": {
                "return_diff": round(new_result["total_return"] - old_result["total_return"], 4),
                "trade_diff": new_result["total_trades"] - old_result["total_trades"],
            },
        }
    except Exception as e:
        logger.error("compare_portfolio failed: %s", e)
        return {"error": str(e), "initial_capital": initial_capital}


def compare_shadow_intel(
    old_model,
    new_model,
    X: pd.DataFrame,
    close: pd.Series,
    asset: str = "unknown",
    threshold: float = 0.45,
    predict_fn: Optional[Callable] = None,
) -> dict:
    try:
        if predict_fn is None:
            predict_fn = lambda m, x: m.predict_proba(x)

        old_proba = predict_fn(old_model, X)
        new_proba = predict_fn(new_model, X)

        old_sig = _compute_signals(old_proba, X.index, threshold)
        new_sig = _compute_signals(new_proba, X.index, threshold)

        old_dist = np.bincount(np.argmax(old_proba, axis=1), minlength=3) / len(old_proba)
        new_dist = np.bincount(np.argmax(new_proba, axis=1), minlength=3) / len(new_proba)

        old_short_conf = old_sig[old_sig["signal"] == 0]["prob_short"].mean() if (old_sig["signal"] == 0).any() else 0.0
        old_long_conf = old_sig[old_sig["signal"] == 2]["prob_long"].mean() if (old_sig["signal"] == 2).any() else 0.0
        new_short_conf = new_sig[new_sig["signal"] == 0]["prob_short"].mean() if (new_sig["signal"] == 0).any() else 0.0
        new_long_conf = new_sig[new_sig["signal"] == 2]["prob_long"].mean() if (new_sig["signal"] == 2).any() else 0.0

        old_entropy = -np.sum(old_dist * np.log(old_dist + 1e-12))
        new_entropy = -np.sum(new_dist * np.log(new_dist + 1e-12))
        entropy_shift = new_entropy - old_entropy

        signal_agreement = (old_sig["signal"] == new_sig["signal"]).mean()

        regime = classify_regime(close).reindex(X.index).ffill()
        regime_stability = {}
        for r in ["low_vol", "high_vol", "transition"]:
            mask = (regime == r).values
            if mask.sum() > 0:
                old_r_dist = np.bincount(np.argmax(old_proba[mask], axis=1), minlength=3) / mask.sum()
                new_r_dist = np.bincount(np.argmax(new_proba[mask], axis=1), minlength=3) / mask.sum()
                regime_stability[r] = round(float(1.0 - np.mean(np.abs(old_r_dist - new_r_dist))), 4)

        return {
            "asset": asset,
            "class_distribution_shift": {
                "old": {"short": round(float(old_dist[0]), 4), "neutral": round(float(old_dist[1]), 4), "long": round(float(old_dist[2]), 4)},
                "new": {"short": round(float(new_dist[0]), 4), "neutral": round(float(new_dist[1]), 4), "long": round(float(new_dist[2]), 4)},
            },
            "entropy_shift": round(float(entropy_shift), 4),
            "signal_agreement": round(float(signal_agreement), 4),
            "mean_confidence_old": {"short": round(float(old_short_conf), 4), "long": round(float(old_long_conf), 4)},
            "mean_confidence_new": {"short": round(float(new_short_conf), 4), "long": round(float(new_long_conf), 4)},
            "regime_stability": regime_stability,
        }
    except Exception as e:
        logger.error("compare_shadow_intel failed: %s", e)
        return {"asset": asset, "error": str(e)}


def build_summary(
    model_result: dict,
    signal_result: dict,
    portfolio_result: dict,
    shadow_result: dict,
    thresholds: Optional[dict] = None,
) -> dict:
    if thresholds is None:
        thresholds = {
            "accuracy_drop": 0.02,
            "logloss_increase": 0.05,
            "agreement_min": 0.80,
            "flip_rate_max": 0.15,
            "return_drop": 0.02,
            "entropy_shift_max": 0.1,
        }

    checks = []

    if "error" not in model_result:
        old_acc = model_result.get("old", {}).get("accuracy", 0)
        new_acc = model_result.get("new", {}).get("accuracy", 0)
        acc_drop = old_acc - new_acc
        checks.append({
            "check": "accuracy_drop",
            "value": round(acc_drop, 4),
            "pass": acc_drop <= thresholds["accuracy_drop"],
        })

    if "error" not in signal_result:
        agreement = signal_result.get("overall_agreement", 1.0)
        flip_rate = signal_result.get("flip_rate", 0.0)
        checks.append({"check": "signal_agreement", "value": agreement, "pass": agreement >= thresholds["agreement_min"]})
        checks.append({"check": "flip_rate", "value": flip_rate, "pass": flip_rate <= thresholds["flip_rate_max"]})

    if "error" not in portfolio_result:
        old_ret = portfolio_result.get("old", {}).get("total_return", 0)
        new_ret = portfolio_result.get("new", {}).get("total_return", 0)
        ret_diff = new_ret - old_ret
        checks.append({
            "check": "return_delta",
            "value": round(ret_diff, 4),
            "pass": ret_diff >= -thresholds["return_drop"],
        })

    if "error" not in shadow_result:
        entropy = abs(shadow_result.get("entropy_shift", 0))
        checks.append({
            "check": "entropy_stability",
            "value": entropy,
            "pass": entropy <= thresholds["entropy_shift_max"],
        })

    all_pass = all(c["pass"] for c in checks)
    return {
        "verdict": "PASS" if all_pass else "WARN" if sum(1 for c in checks if not c["pass"]) <= 2 else "FAIL",
        "checks": checks,
        "pass_count": sum(1 for c in checks if c["pass"]),
        "total_checks": len(checks),
    }
