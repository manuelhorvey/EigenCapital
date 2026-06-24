"""Model comparison utilities for evaluating new vs old models."""

import numpy as np
import pandas as pd


def classify_regime(close):
    """Classify volatility regime from close prices."""
    returns = close.pct_change().dropna()
    vol = returns.rolling(20).std()
    if vol.empty or len(vol) < 2:
        return pd.Series("mid", index=close.index)

    vol_aligned = vol.reindex(close.index, method="ffill").fillna(vol.median() if len(vol) > 0 else 0.0)
    thresholds = vol_aligned.quantile([0.33, 0.66])
    low_thresh = thresholds.iloc[0]
    high_thresh = thresholds.iloc[1] if len(thresholds) > 1 else low_thresh

    regime = pd.Series("mid", index=close.index)
    regime[vol_aligned <= low_thresh] = "low_vol"
    regime[(vol_aligned > low_thresh) & (vol_aligned <= high_thresh)] = "mid"
    vol_change = vol_aligned.diff().abs()
    transition_thresh = vol_aligned.quantile(0.8)
    regime[vol_change > transition_thresh] = "transition"
    regime[vol_aligned > high_thresh] = "high_vol"
    return regime


def _compute_signals(proba, dates, threshold=0.45):
    """Convert probability array to signals DataFrame.

    proba is (n, 3) with columns [short, neutral, long].
    Returns DataFrame with 'signal' column (0=short, 1=neutral, 2=long).
    Default signal is 0 (short).
    """
    n = len(proba)
    signals = np.full(n, 0, dtype=int)  # default short
    signals[proba[:, 2] > threshold] = 2  # long
    return pd.DataFrame({"signal": signals}, index=dates)


def _simulate_portfolio(proba, close, initial_capital=100000.0, threshold=0.45):
    """Simple portfolio simulation from probabilities."""
    n = len(proba)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    signals_df = _compute_signals(proba, dates, threshold=threshold)
    signals = signals_df["signal"].values

    close_arr = close.values
    daily_rets = np.diff(close_arr) / close_arr[:-1]

    aligned_signals = signals[: len(daily_rets)]
    pnl = np.where(
        aligned_signals == 2,
        daily_rets,
        np.where(aligned_signals == 0, -daily_rets, 0.0),
    )

    equity = initial_capital * (1 + np.cumsum(pnl))
    trades = int((aligned_signals != 1).sum())

    total_return = float(np.sum(pnl))
    dd = 0.0
    if len(equity) > 0:
        peak = np.maximum.accumulate(equity)
        dd = float(np.max((peak - equity) / peak)) if peak[-1] > 0 else 0.0

    return {
        "total_return": total_return,
        "max_drawdown": dd,
        "total_trades": trades,
    }


def compare_models(old, new, x, y=None, predict_fn=None):
    """Compare two models' performance on data x.

    Computes AUC (macro), accuracy, and logloss for both models. Also
    reports class distribution (short/neutral/long).

    Args:
        old: Reference model with ``predict_proba``.
        new: Candidate model with ``predict_proba``.
        x: Feature DataFrame of shape (n_samples, n_features).
        y: Optional ground-truth labels for AUC/accuracy/logloss.
            If None, only class distribution is reported.
        predict_fn: Optional custom prediction function ``fn(model, x)``.

    Returns:
        dict with keys: n_samples, class_distribution, and optionally
        "old" and "new" containing accuracy, auc_macro, logloss,
        and predictions (list). Returns {"error": ...} on exception.
    """
    import sklearn.metrics

    try:
        if predict_fn is not None:
            old_proba = predict_fn(old, x)
            new_proba = predict_fn(new, x)
        else:
            old_proba = old.predict_proba(x)
            new_proba = new.predict_proba(x)
    except Exception as e:
        return {"error": str(e)}

    old_pred = np.argmax(old_proba, axis=1)
    new_pred = np.argmax(new_proba, axis=1)

    def _class_dist(pred):
        return {
            "short": int((pred == 0).sum()),
            "neutral": int((pred == 1).sum()),
            "long": int((pred == 2).sum()),
        }

    result = {
        "n_samples": len(x),
        "class_distribution": {
            "old": _class_dist(old_pred),
            "new": _class_dist(new_pred),
        },
    }

    if y is not None:
        try:
            old_auc = sklearn.metrics.roc_auc_score(y, old_proba, multi_class="ovr")
            new_auc = sklearn.metrics.roc_auc_score(y, new_proba, multi_class="ovr")
        except Exception:
            old_auc = None
            new_auc = None

        old_acc = sklearn.metrics.accuracy_score(y, old_pred)
        new_acc = sklearn.metrics.accuracy_score(y, new_pred)

        try:
            old_ll = sklearn.metrics.log_loss(y, old_proba)
            new_ll = sklearn.metrics.log_loss(y, new_proba)
        except Exception:
            old_ll = None
            new_ll = None

        old_dict = {"accuracy": old_acc, "predictions": old_pred.tolist()}
        new_dict = {"accuracy": new_acc, "predictions": new_pred.tolist()}

        if old_auc is not None:
            old_dict["auc_macro"] = old_auc
        if new_auc is not None:
            new_dict["auc_macro"] = new_auc
        if old_ll is not None:
            old_dict["logloss"] = old_ll
        if new_ll is not None:
            new_dict["logloss"] = new_ll

        result["old"] = old_dict
        result["new"] = new_dict
    else:
        # No y provided: only include class_distribution, not per-model accuracy
        pass

    return result


def compare_signals(old, new, x, close):
    """Compare signal-level agreement between two models.

    Computes overall flip rate, final signal agreement, regime-stratified
    agreement, and mean confidence shift between old and new model
    predictions.

    Args:
        old: Reference model with ``predict_proba``.
        new: Candidate model with ``predict_proba``.
        x: Feature DataFrame.
        close: Close price Series (used for regime classification).

    Returns:
        dict with keys: overall_agreement, total_flips, flip_rate,
        final_signal_old, final_signal_new, final_agreement,
        mean_confidence_shift, regime_stratified_agreement.
        Returns {"error": ...} on exception.
    """
    try:
        old_proba = old.predict_proba(x)
        new_proba = new.predict_proba(x)
    except Exception as e:
        return {"error": str(e)}

    n = len(x)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")

    old_signals = _compute_signals(old_proba, dates)["signal"].values
    new_signals = _compute_signals(new_proba, dates)["signal"].values

    agreement = (old_signals == new_signals).mean()
    total_flips = int((old_signals != new_signals).sum())

    # Final signal: use old model's last signal
    final_old = int(old_signals[-1]) if len(old_signals) > 0 else 1
    final_new = int(new_signals[-1]) if len(new_signals) > 0 else 1

    # Regime-stratified agreement
    regime = classify_regime(close)
    regime_agreement = {}
    for r in regime.unique():
        mask = regime.values == r
        if mask.sum() > 0:
            regime_agreement[r] = float((old_signals[mask] == new_signals[mask]).mean())

    # Mean confidence shift
    old_conf = np.max(old_proba, axis=1)
    new_conf = np.max(new_proba, axis=1)
    conf_shift = float(np.mean(np.abs(old_conf - new_conf)))

    return {
        "overall_agreement": float(agreement),
        "total_flips": total_flips,
        "flip_rate": total_flips / n if n > 0 else 0.0,
        "final_signal_old": final_old,
        "final_signal_new": final_new,
        "final_agreement": final_old == final_new,
        "mean_confidence_shift": conf_shift,
        "regime_stratified_agreement": regime_agreement,
    }


def compare_portfolio(old, new, x, close, initial_capital=100000.0, threshold=0.45):
    """Compare portfolio-level performance between two models.

    Simulates a simple long/short portfolio for both models using
    signal-based PnL at the given threshold.

    Args:
        old: Reference model with ``predict_proba``.
        new: Candidate model with ``predict_proba``.
        x: Feature DataFrame.
        close: Close price Series.
        initial_capital: Starting capital (default 100,000).
        threshold: Signal threshold (default 0.45).

    Returns:
        dict with keys: initial_capital, old (portfolio result),
        new (portfolio result), delta (return_diff, trade_diff).
        Returns {"error": ...} on exception.
    """
    try:
        old_proba = old.predict_proba(x)
        new_proba = new.predict_proba(x)
    except Exception as e:
        return {"error": str(e)}

    old_result = _simulate_portfolio(old_proba, close, initial_capital, threshold)
    new_result = _simulate_portfolio(new_proba, close, initial_capital, threshold)

    return {
        "initial_capital": initial_capital,
        "old": old_result,
        "new": new_result,
        "delta": {
            "return_diff": round(new_result["total_return"] - old_result["total_return"], 6),
            "trade_diff": new_result["total_trades"] - old_result["total_trades"],
        },
    }


def compare_shadow_intel(old, new, x, close, asset=None):
    """Compare shadow intelligence between two models.

    Computes class distribution shift, entropy difference, signal
    agreement, mean confidence per class, and regime-stratified
    stability.

    Args:
        old: Reference model with ``predict_proba``.
        new: Candidate model with ``predict_proba``.
        x: Feature DataFrame.
        close: Close price Series (used for regime classification).
        asset: Optional asset name to include in the result.

    Returns:
        dict with keys: class_distribution_shift, entropy_shift,
        signal_agreement, mean_confidence_old, mean_confidence_new,
        regime_stability, and optionally asset.
        Returns {"error": ...} on exception.
    """
    try:
        old_proba = old.predict_proba(x)
        new_proba = new.predict_proba(x)
    except Exception as e:
        return {"error": str(e)}

    n = len(x)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")

    old_signals = _compute_signals(old_proba, dates)["signal"].values
    new_signals = _compute_signals(new_proba, dates)["signal"].values

    def _class_dist(signals):
        return {
            "short": int((signals == 0).sum()),
            "neutral": int((signals == 1).sum()),
            "long": int((signals == 2).sum()),
        }

    # Class distribution shift
    old_dist = _class_dist(old_signals)
    new_dist = _class_dist(new_signals)

    def _entropy(dist):
        import math

        total = sum(dist.values())
        if total == 0:
            return 0.0
        h = 0.0
        for v in dist.values():
            if v > 0:
                p = v / total
                h -= p * math.log(p + 1e-12)
        return h

    # Signal agreement
    signal_agreement = float((old_signals == new_signals).mean())

    old_entropy = _entropy(old_dist)
    new_entropy = _entropy(new_dist)
    entropy_shift = abs(new_entropy - old_entropy)

    # Mean confidence per class
    def _mean_conf(proba, signals):
        conf = {"short": 0.0, "long": 0.0}
        for cls, label in [("short", 0), ("long", 2)]:
            mask = signals == label
            if mask.any():
                conf[cls] = float(np.mean(proba[mask, label]))
        return conf

    old_conf = _mean_conf(old_proba, old_signals)
    new_conf = _mean_conf(new_proba, new_signals)

    # Regime stability
    regime = classify_regime(close)
    regime_stability = {}
    for r in regime.unique():
        mask = regime.values == r
        if mask.sum() > 0:
            regime_stability[r] = float((old_signals[mask] == new_signals[mask]).mean())

    result = {
        "class_distribution_shift": {"old": old_dist, "new": new_dist},
        "entropy_shift": entropy_shift,
        "signal_agreement": signal_agreement,
        "mean_confidence_old": old_conf,
        "mean_confidence_new": new_conf,
        "regime_stability": regime_stability,
    }
    if asset is not None:
        result["asset"] = asset
    return result


def build_summary(model_result, signal_result, portfolio_result, shadow_result, thresholds=None):
    """Build a summary verdict from all comparison results.

    Checks accuracy drop, signal agreement, flip rate, return drop,
    and entropy shift against configurable thresholds. Produces a
    PASS (<= 25% failures), WARN (<= 50%), or FAIL verdict.

    Args:
        model_result: Result from ``compare_models``.
        signal_result: Result from ``compare_signals``.
        portfolio_result: Result from ``compare_portfolio``.
        shadow_result: Result from ``compare_shadow_intel``.
        thresholds: Optional dict of check-specific thresholds.

    Returns:
        dict with keys: verdict, checks (list of str),
        total_checks, failures.
    """
    if thresholds is None:
        thresholds = {
            "accuracy_drop": 0.05,
            "logloss_increase": 0.1,
            "agreement_min": 0.8,
            "flip_rate_max": 0.15,
            "return_drop": 0.05,
            "entropy_shift_max": 0.2,
        }

    checks = []
    total_checks = 0
    failures = 0

    # Model check
    if "error" not in model_result:
        total_checks += 1
        old = model_result.get("old", {})
        new = model_result.get("new", {})
        old_acc = old.get("accuracy", 0)
        new_acc = new.get("accuracy", 0)
        if new_acc < old_acc - thresholds["accuracy_drop"]:
            failures += 1
            checks.append("model: accuracy dropped")
        else:
            checks.append("model: OK")

    # Signal check
    if "error" not in signal_result:
        total_checks += 1
        if signal_result.get("overall_agreement", 0) < thresholds["agreement_min"]:
            failures += 1
            checks.append("signal: agreement too low")
        else:
            checks.append("signal: OK")
        if signal_result.get("flip_rate", 0) > thresholds["flip_rate_max"]:
            failures += 1
            checks.append("signal: flip rate too high")
        else:
            checks.append("signal: flip rate OK")

    # Portfolio check
    if "error" not in portfolio_result:
        total_checks += 1
        old_ret = portfolio_result.get("old", {}).get("total_return", 0)
        new_ret = portfolio_result.get("new", {}).get("total_return", 0)
        if new_ret < old_ret - thresholds["return_drop"]:
            failures += 1
            checks.append("portfolio: return dropped")
        else:
            checks.append("portfolio: OK")

    # Shadow check
    if "error" not in shadow_result:
        total_checks += 1
        if shadow_result.get("entropy_shift", 0) > thresholds["entropy_shift_max"]:
            failures += 1
            checks.append("shadow: entropy shift too high")
        else:
            checks.append("shadow: OK")

    # Verdict
    if total_checks == 0 or failures / total_checks <= 0.25:
        verdict = "PASS"
    elif failures / total_checks <= 0.5:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "checks": checks,
        "total_checks": total_checks,
        "failures": failures,
    }
