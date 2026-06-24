import logging
from typing import Optional, Callable

import numpy as np
import pandas as pd
import xgboost as xgb

from features.registry import FEATURE_REGISTRY
from shared.model import XGBoostModel

logger = logging.getLogger("quantforge.forward_test")


def _classify_vol_regime(close: pd.Series) -> pd.Series:
    returns = np.log(close / close.shift(1)).dropna()
    vol = returns.rolling(10).std() * np.sqrt(252)
    vol_pct = vol.rank(pct=True)
    vol_pct = vol_pct.reindex(close.index).ffill().fillna(0.5)
    regime = pd.Series("transition", index=close.index)
    regime[vol_pct < 0.33] = "low_vol"
    regime[vol_pct > 0.67] = "high_vol"
    return regime


def _sharpe_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    excess = returns - rf / 252
    if excess.std() == 0:
        return 0.0
    return float(np.sqrt(252) * excess.mean() / excess.std())


def _hit_rate(signals: np.ndarray, forward_returns: np.ndarray) -> float:
    trades = signals != 1
    if trades.sum() == 0:
        return 0.0
    correct = ((signals == 2) & (forward_returns > 0)) | ((signals == 0) & (forward_returns < 0))
    return float(correct[trades].sum() / trades.sum())


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(abs(dd.min()))


def _forward_metrics(
    proba: np.ndarray,
    close: pd.Series,
    threshold: float = 0.45,
) -> dict:
    n = len(proba)
    signals = np.full(n, 1, dtype=int)
    signals[proba[:, 2] > threshold] = 2
    signals[proba[:, 0] > threshold] = 0

    close_arr = close.values.astype(np.float64)
    forward_ret = np.full(n, np.nan)
    for i in range(n - 1):
        forward_ret[i] = close_arr[i + 1] / close_arr[i] - 1
    forward_ret[-1] = 0.0

    daily_pnl = np.full(n, np.nan)
    pos = 0
    entry = 0.0
    for i in range(n):
        if pos != 0 and signals[i] != pos:
            ret = (close_arr[i] / entry - 1) if pos == 2 else (entry / close_arr[i] - 1)
            daily_pnl[i] = ret
            pos = 0
        elif pos == 0 and signals[i] != 1:
            pos = int(signals[i])
            daily_pnl[i] = 0.0
            entry = float(close_arr[i])
        elif pos == 0:
            daily_pnl[i] = 0.0

    trade_returns = daily_pnl[~np.isnan(daily_pnl)]
    if len(trade_returns) == 0:
        trade_returns = np.array([0.0])

    equity = 100000.0 * (1 + np.nan_to_num(daily_pnl)).cumprod()
    sharpe = _sharpe_ratio(trade_returns)
    hit = _hit_rate(signals, forward_ret)
    dd = _max_drawdown(equity)
    n_trades = int((signals[1:] != signals[:-1]).sum())
    pnl_std = float(trade_returns.std()) if len(trade_returns) > 1 else 0.0

    # ── Statistical metrics ──
    n_obs = len(trade_returns)
    skew_val, exkurt_val = (0.0, 0.0)
    if n_obs >= 3:
        from quantforge.domain.value_objects.statistical_metrics import _moments as _stats_moments
        skew_val, exkurt_val = _stats_moments(trade_returns)

    from quantforge.domain.value_objects.statistical_metrics import (
        probabilistic_sharpe_ratio,
        minimum_track_record_length,
        expected_calibration_error,
    )

    psr_gt_0 = probabilistic_sharpe_ratio(float(sharpe), n_obs, skew_val, exkurt_val, 0.0)
    min_trl = minimum_track_record_length(float(sharpe), skew_val, exkurt_val, 0.05)

    # CRS: per-prediction confidence vs correctness for directional signals only
    pred_confs: list[float] = []
    pred_correct: list[bool] = []
    for i in range(n):
        if signals[i] == 2:
            pred_confs.append(float(proba[i, 2]))
            pred_correct.append(forward_ret[i] > 0)
        elif signals[i] == 0:
            pred_confs.append(float(proba[i, 0]))
            pred_correct.append(forward_ret[i] < 0)
    crs = 1.0 - expected_calibration_error(
        np.array(pred_confs), np.array(pred_correct, dtype=int)
    ) if len(pred_confs) >= 10 else 0.0

    return {
        "sharpe": round(float(sharpe), 4),
        "hit_rate": round(float(hit), 4),
        "max_drawdown": round(float(dd), 4),
        "total_trades": n_trades,
        "pnl_std": round(pnl_std, 6),
        "stability": 1.0 - min(pnl_std / 0.05, 1.0) if pnl_std > 0 else 1.0,
        "psr_gt_0": round(float(psr_gt_0), 4),
        "min_trl": int(min_trl),
        "n_obs": n_obs,
        "crs": round(float(crs), 4),
    }


def _regime_trade_returns(signals: np.ndarray, close_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(signals)
    daily_pnl = np.full(n, np.nan)
    pos = 0
    entry = 0.0
    for i in range(n):
        if pos != 0 and signals[i] != pos:
            ret = (close_arr[i] / entry - 1) if pos == 2 else (entry / close_arr[i] - 1)
            daily_pnl[i] = ret
            pos = 0
        elif pos == 0 and signals[i] != 1:
            pos = int(signals[i])
            daily_pnl[i] = 0.0
            entry = float(close_arr[i])
        elif pos == 0:
            daily_pnl[i] = 0.0
    equity = 100000.0 * (1 + np.nan_to_num(daily_pnl)).cumprod()
    return daily_pnl, equity


def _regime_metrics(proba: np.ndarray, close: pd.Series, regime: pd.Series, threshold: float = 0.45) -> dict:
    n = len(proba)
    signals = np.full(n, 1, dtype=int)
    signals[proba[:, 2] > threshold] = 2
    signals[proba[:, 0] > threshold] = 0
    close_arr = close.values.astype(np.float64)
    trade_pnl, equity = _regime_trade_returns(signals, close_arr)
    regime_results = {}
    for r in ["low_vol", "high_vol", "transition"]:
        mask = (regime.values == r)
        if mask.sum() < 3:
            regime_results[r] = {"sharpe": 0.0, "max_drawdown": 0.0}
            continue
        r_trades = trade_pnl[mask]
        r_trades = r_trades[~np.isnan(r_trades)]
        r_sharpe = _sharpe_ratio(r_trades) if len(r_trades) > 1 else 0.0
        r_equity = equity[mask]
        r_dd = _max_drawdown(r_equity)
        regime_results[r] = {
            "sharpe": round(float(r_sharpe), 4),
            "max_drawdown": round(float(r_dd), 4),
        }
    return regime_results


def run_forward_test(
    ticker: str,
    X: pd.DataFrame,
    y: pd.Series,
    close: pd.Series,
    production_model,
    forward_months: int = 6,
    threshold: float = 0.45,
    predict_fn: Optional[Callable] = None,
) -> dict:
    try:
        if predict_fn is None:
            predict_fn = lambda m, x: XGBoostModel().predict(m, x)

        cutoff = X.index[-1] - pd.DateOffset(months=forward_months)
        train_mask = X.index < cutoff
        fwd_mask = X.index >= cutoff

        if fwd_mask.sum() < 20:
            logger.warning("  %s: forward window too small (%d rows), falling back to 3mo", ticker, int(fwd_mask.sum()))
            cutoff = X.index[-1] - pd.DateOffset(months=3)
            train_mask = X.index < cutoff
            fwd_mask = X.index >= cutoff

        X_train_fw = X[train_mask]
        y_train_fw = y[train_mask]
        X_fwd = X[fwd_mask]
        close_fwd = close[fwd_mask]

        logger.info("  %s forward: train=%d rows, forward=%d rows (%.1f months cutoff)",
                     ticker, len(X_train_fw), len(X_fwd), forward_months)

        n_est = 300
        depth = 2
        lr = 0.02
        fw_split = int(len(X_train_fw) * 0.8) if len(X_train_fw) >= 200 else int(len(X_train_fw) * 0.5)

        fw_model = xgb.XGBClassifier(
            n_estimators=n_est, max_depth=depth, learning_rate=lr,
            objective="multi:softprob", num_class=3,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
        )
        fw_model.fit(
            X_train_fw.iloc[:fw_split], y_train_fw.iloc[:fw_split],
            eval_set=[(X_train_fw.iloc[fw_split:], y_train_fw.iloc[fw_split:])],
            verbose=False,
        )

        baseline_proba = predict_fn(production_model, X_fwd)
        fw_proba = predict_fn(fw_model, X_fwd)

        baseline_metrics = _forward_metrics(baseline_proba, close_fwd, threshold)
        fw_metrics = _forward_metrics(fw_proba, close_fwd, threshold)

        fwd_regime = _classify_vol_regime(close_fwd)
        baseline_regime = _regime_metrics(baseline_proba, close_fwd, fwd_regime, threshold)
        fw_regime_metrics = _regime_metrics(fw_proba, close_fwd, fwd_regime, threshold)

        return {
            "ticker": ticker,
            "forward_window": {"start": str(X_fwd.index[0]), "end": str(X_fwd.index[-1]), "n_rows": len(X_fwd)},
            "baseline": baseline_metrics,
            "new": fw_metrics,
            "baseline_regime": baseline_regime,
            "new_regime": fw_regime_metrics,
            "delta": {
                "sharpe_diff": round(fw_metrics["sharpe"] - baseline_metrics["sharpe"], 4),
                "hit_rate_diff": round(fw_metrics["hit_rate"] - baseline_metrics["hit_rate"], 4),
                "stability_diff": round(fw_metrics["stability"] - baseline_metrics["stability"], 4),
            },
        }
    except Exception as e:
        logger.error("run_forward_test failed for %s: %s", ticker, e)
        import traceback; traceback.print_exc()
        return {"ticker": ticker, "error": str(e)}
