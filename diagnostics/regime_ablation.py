import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from backtests.expectancy_audit import calculate_expectancy
from models.hybrid_ensemble import HybridRegimeEnsemble


SIGNAL_THRESHOLD = 0.40
REGIME_COLUMNS = [
    "P_trend",
    "P_range",
    "P_volatile",
    "regime_confidence",
    "regime_contrast",
    "ema_contrast",
    "slope_contrast",
    "path_contrast",
    "regime_entropy",
    "transition_risk",
]


def assemble_data():
    base = pd.read_parquet("data/processed/EURUSD_features.parquet")
    regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
    struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
    interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
    labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
    raw = pd.read_parquet("data/raw/EURUSD_1d.parquet")

    common_idx = (
        base.index
        .intersection(regime_meta.index)
        .intersection(struct.index)
        .intersection(interact.index)
        .intersection(labeled.index)
        .intersection(raw.index)
    )

    X_regime = pd.concat(
        [
            base.loc[common_idx].drop("label", axis=1),
            regime_meta.loc[common_idx][["P_trend", "P_range", "P_volatile", "regime_confidence"]],
            struct.loc[common_idx],
            interact.loc[common_idx],
        ],
        axis=1,
    )
    X_no_regime = X_regime.drop(columns=[c for c in REGIME_COLUMNS if c in X_regime.columns])
    y = labeled.loc[common_idx, "label"] + 1
    labels = labeled.loc[common_idx, "label"]
    regimes = regime_meta.loc[common_idx, "regime"]
    returns = raw.loc[common_idx, "close"].pct_change()

    return X_regime, X_no_regime, y, labels, regimes, returns


def signal_from_probs(probs: np.ndarray, index: pd.Index) -> pd.DataFrame:
    signals = pd.DataFrame(index=index)
    signals["raw_prob_short"] = probs[:, 0]
    signals["raw_prob_neutral"] = probs[:, 1]
    signals["raw_prob_long"] = probs[:, 2]
    signals["signal"] = 0
    signals.loc[signals["raw_prob_long"] > SIGNAL_THRESHOLD, "signal"] = 1
    signals.loc[signals["raw_prob_short"] > SIGNAL_THRESHOLD, "signal"] = -1
    signals["risk_multiplier"] = 1.0
    return signals


def train_no_regime_model(X_train: pd.DataFrame, y_train: pd.Series):
    split = int(len(X_train) * 0.8)
    weights = np.linspace(0.5, 1.0, len(X_train))
    model = xgb.XGBClassifier(
        n_estimators=500,
        learning_rate=0.01,
        max_delta_step=1,
        tree_method="hist",
        min_child_weight=10,
        objective="multi:softprob",
        num_class=3,
        max_depth=2,
        random_state=42,
        early_stopping_rounds=30,
    )
    model.fit(
        X_train.iloc[:split],
        y_train.iloc[:split],
        sample_weight=weights[:split],
        eval_set=[(X_train.iloc[split:], y_train.iloc[split:])],
        verbose=False,
    )
    return model


def score_signals(signals: pd.DataFrame, returns: pd.Series) -> dict:
    df = signals.copy()
    df["returns"] = returns.shift(-1).loc[df.index]
    df["pnl"] = df["signal"] * df["risk_multiplier"] * df["returns"]
    return calculate_expectancy(df[df["signal"] != 0])


def shap_top_features(model, X_sample: pd.DataFrame, class_idx: int = 2, n: int = 8) -> pd.Series:
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)
    if isinstance(shap_values, list):
        values = shap_values[class_idx]
    elif len(shap_values.shape) == 3:
        if shap_values.shape[1] == len(X_sample.columns):
            values = shap_values[:, :, class_idx]
        else:
            values = shap_values[:, class_idx, :]
    else:
        values = shap_values
    return pd.Series(np.abs(values).mean(axis=0), index=X_sample.columns).sort_values(ascending=False).head(n)


def run_holdout_ablation(X_regime, X_no_regime, y, regimes, returns):
    split = int(len(X_regime) * 0.8)

    Xr_train, Xr_test = X_regime.iloc[:split], X_regime.iloc[split:]
    Xn_train, Xn_test = X_no_regime.iloc[:split], X_no_regime.iloc[split:]
    y_train = y.iloc[:split]
    regimes_train, regimes_test = regimes.iloc[:split], regimes.iloc[split:]

    ensemble = HybridRegimeEnsemble()
    ensemble.train(Xr_train, y_train, regimes_train)
    regime_probs = ensemble.predict_proba(Xr_test, regimes_test)
    regime_signals = signal_from_probs(regime_probs, Xr_test.index)
    regime_metrics = score_signals(regime_signals, returns)

    no_regime_model = train_no_regime_model(Xn_train, y_train)
    no_regime_probs = no_regime_model.predict_proba(Xn_test)
    no_regime_signals = signal_from_probs(no_regime_probs, Xn_test.index)
    no_regime_metrics = score_signals(no_regime_signals, returns)

    return {
        "regime_metrics": regime_metrics,
        "no_regime_metrics": no_regime_metrics,
        "regime_signals": regime_signals,
        "no_regime_signals": no_regime_signals,
        "regime_shap": shap_top_features(ensemble.global_model, Xr_test.tail(500)),
        "no_regime_shap": shap_top_features(no_regime_model, Xn_test.tail(500)),
    }


def run_walk_forward_ablation(X_regime, X_no_regime, y, regimes, returns):
    years = X_regime.index.year.unique()
    rows = []

    for current_year in range(years[0] + 3, years[-1] + 1):
        train_mask = X_regime.index.year <= current_year - 1
        test_mask = X_regime.index.year == current_year
        if test_mask.sum() == 0:
            continue

        Xr_train, Xr_test = X_regime[train_mask], X_regime[test_mask]
        Xn_train, Xn_test = X_no_regime[train_mask], X_no_regime[test_mask]
        y_train = y[train_mask]
        regimes_train, regimes_test = regimes[train_mask], regimes[test_mask]

        ensemble = HybridRegimeEnsemble()
        ensemble.train(Xr_train, y_train, regimes_train)
        regime_probs = ensemble.predict_proba(Xr_test, regimes_test)
        regime_metrics = score_signals(signal_from_probs(regime_probs, Xr_test.index), returns)

        no_regime_model = train_no_regime_model(Xn_train, y_train)
        no_regime_probs = no_regime_model.predict_proba(Xn_test)
        no_regime_metrics = score_signals(signal_from_probs(no_regime_probs, Xn_test.index), returns)

        rows.append(
            {
                "window": current_year,
                "regime_expectancy": regime_metrics.get("expectancy", 0),
                "regime_trades": regime_metrics.get("n_trades", 0),
                "regime_pf": regime_metrics.get("profit_factor", 0),
                "no_regime_expectancy": no_regime_metrics.get("expectancy", 0),
                "no_regime_trades": no_regime_metrics.get("n_trades", 0),
                "no_regime_pf": no_regime_metrics.get("profit_factor", 0),
            }
        )

    return pd.DataFrame(rows)


def print_metrics(title: str, metrics: dict):
    print(f"\n{title}")
    print(f"  Expectancy:    {metrics.get('expectancy', 0)}")
    print(f"  Win Rate:      {metrics.get('win_rate', 0):.2%}")
    print(f"  Profit Factor: {metrics.get('profit_factor', 0)}")
    print(f"  Recovery:      {metrics.get('recovery_factor', 0)}")
    print(f"  Trades:        {metrics.get('n_trades', 0)}")


def main():
    X_regime, X_no_regime, y, labels, regimes, returns = assemble_data()

    print("=" * 24 + " REGIME ABLATION " + "=" * 24)
    print(f"Regime-aware features: {X_regime.shape[1]}")
    print(f"No-regime features:    {X_no_regime.shape[1]}")

    holdout = run_holdout_ablation(X_regime, X_no_regime, y, regimes, returns)
    print_metrics("Holdout: regime-aware", holdout["regime_metrics"])
    print_metrics("Holdout: no-regime", holdout["no_regime_metrics"])

    print("\nTop SHAP features: regime-aware global model")
    print(holdout["regime_shap"].to_string())
    print("\nTop SHAP features: no-regime model")
    print(holdout["no_regime_shap"].to_string())

    wf = run_walk_forward_ablation(X_regime, X_no_regime, y, regimes, returns)
    print("\nWalk-forward comparison")
    print(wf.to_string(index=False))

    print("\nWalk-forward averages")
    print(
        wf[
            [
                "regime_expectancy",
                "regime_trades",
                "regime_pf",
                "no_regime_expectancy",
                "no_regime_trades",
                "no_regime_pf",
            ]
        ]
        .mean()
        .round(6)
        .to_string()
    )


if __name__ == "__main__":
    main()
