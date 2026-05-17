import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr

from backtests.expectancy_audit import calculate_expectancy
from models.hybrid_ensemble import HybridRegimeEnsemble
from signals.signal_generator import RegimeAwareSignalGenerator


STRUCTURAL_PSI_COLUMNS = [
    "ema_spread",
    "adx",
    "rsi",
    "bb_zscore",
    "slope_20",
    "curvature_10",
    "path_efficiency_63",
    "skew",
    "kurt",
    "tail_ratio",
]

BEHAVIORAL_PSI_COLUMNS = [
    "P_trend",
    "P_range",
    "P_volatile",
    "regime_confidence",
]

INTERACTION_PSI_COLUMNS = [
    "regime_contrast",
    "regime_entropy",
    "transition_risk",
    "ema_contrast",
    "slope_contrast",
    "path_contrast",
]


def sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-np.clip(x, -20, 20))))


def bounded_z(value: float, center: float, scale: float) -> float:
    return (value - center) / (scale + 1e-12)


def assemble_manifold():
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

    X = pd.concat(
        [
            base.loc[common_idx].drop("label", axis=1),
            regime_meta.loc[common_idx][["P_trend", "P_range", "P_volatile", "regime_confidence"]],
            struct.loc[common_idx],
            interact.loc[common_idx],
        ],
        axis=1,
    )

    y = labeled.loc[common_idx, "label"] + 1
    regimes = regime_meta.loc[common_idx, "regime"]
    returns = raw.loc[common_idx, "close"].pct_change()
    regime_features = regime_meta.loc[common_idx]

    return X, y, regimes, returns, regime_features


def calculate_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    expected = expected.replace([np.inf, -np.inf], np.nan).dropna()
    actual = actual.replace([np.inf, -np.inf], np.nan).dropna()
    if len(expected) < bins or len(actual) == 0:
        return 0.0

    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(expected.quantile(quantiles).to_numpy())
    if len(edges) < 3:
        return 0.0

    expected_counts = pd.cut(expected, bins=edges, include_lowest=True).value_counts(sort=False)
    actual_counts = pd.cut(actual, bins=edges, include_lowest=True).value_counts(sort=False)

    expected_pct = expected_counts / max(expected_counts.sum(), 1)
    actual_pct = actual_counts / max(actual_counts.sum(), 1)

    expected_pct = expected_pct.replace(0, 1e-6)
    actual_pct = actual_pct.replace(0, 1e-6)
    return float(((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)).sum())


def column_group_psi(train: pd.DataFrame, oos: pd.DataFrame, columns: list[str]) -> float:
    cols = [col for col in columns if col in train.columns and col in oos.columns]
    if not cols:
        return 0.0
    return float(np.mean([calculate_psi(train[col], oos[col]) for col in cols]))


def grouped_feature_psi(train: pd.DataFrame, oos: pd.DataFrame) -> dict:
    structural = column_group_psi(train, oos, STRUCTURAL_PSI_COLUMNS)
    behavioral = column_group_psi(train, oos, BEHAVIORAL_PSI_COLUMNS)
    interaction = column_group_psi(train, oos, INTERACTION_PSI_COLUMNS)
    weighted = 0.2 * structural + 0.5 * behavioral + 0.3 * interaction
    return {
        "feature_psi": weighted,
        "structural_psi": structural,
        "behavioral_psi": behavioral,
        "interaction_psi": interaction,
    }


def feature_psi(train: pd.DataFrame, oos: pd.DataFrame) -> float:
    return grouped_feature_psi(train, oos)["feature_psi"]


def regime_distribution_drift(train_regimes: pd.Series, oos_regimes: pd.Series) -> float:
    labels = sorted(set(train_regimes.dropna().unique()) | set(oos_regimes.dropna().unique()))
    train_dist = train_regimes.value_counts(normalize=True).reindex(labels).fillna(1e-6)
    oos_dist = oos_regimes.value_counts(normalize=True).reindex(labels).fillna(1e-6)
    train_dist = train_dist / train_dist.sum()
    oos_dist = oos_dist / oos_dist.sum()
    return float(0.5 * np.abs(train_dist - oos_dist).sum())


def shap_importance(model, X_sample: pd.DataFrame, class_idx: int = 2) -> pd.Series:
    if len(X_sample) == 0:
        return pd.Series(dtype=float)

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

    return pd.Series(np.abs(values).mean(axis=0), index=X_sample.columns).sort_values(ascending=False)


def shap_instability(previous: pd.Series | None, current: pd.Series) -> float:
    if previous is None or previous.empty or current.empty:
        return 0.5

    cols = previous.index.intersection(current.index)
    if len(cols) < 3:
        return 0.5

    prev_rank = previous.loc[cols].rank(ascending=False)
    curr_rank = current.loc[cols].rank(ascending=False)
    corr = spearmanr(prev_rank, curr_rank).correlation
    if np.isnan(corr):
        return 0.5

    return float((1.0 - corr) / 2.0)


def score_drift(psi: float, regime_drift: float) -> float:
    psi_score = min(psi / 0.25, 1.0)
    regime_score = min(regime_drift / 0.50, 1.0)
    return 0.5 * psi_score + 0.5 * regime_score


def score_regime_drift(regime_drift: float) -> float:
    return min(regime_drift / 0.50, 1.0)


def structural_psi_gate(structural_psi: float) -> float:
    """
    Structural features are expected to drift, but large shifts should reduce
    capital trust. Bands are calibrated to the observed EURUSD daily PSI scale.
    """
    if structural_psi <= 0.65:
        return 1.00
    if structural_psi <= 0.80:
        return 0.85
    if structural_psi <= 1.20:
        return 0.72
    return 0.80


def behavioral_psi_gate(behavioral_psi: float) -> float:
    """
    Behavioral PSI is usually low in this system, so use a small saturating
    penalty rather than a hard cutoff.
    """
    return 1.0 - 0.08 * sigmoid((behavioral_psi - 0.20) / 0.08)


def interaction_psi_gate(interaction_psi: float, dominant_regime: str) -> float:
    """
    Interaction drift is most important when trend coupling dominates, less so
    in range-heavy environments where context features are expected to vary.
    """
    weights = {
        "trend": 0.12,
        "range": 0.05,
        "volatile": 0.08,
        "neutral": 0.08,
    }
    weight = weights.get(dominant_regime, 0.08)
    penalty = weight * min(interaction_psi / 0.50, 1.0)
    return max(0.85, 1.0 - penalty)


def psi_gate(structural_psi: float, behavioral_psi: float, interaction_psi: float, dominant_regime: str) -> dict:
    structural_gate = structural_psi_gate(structural_psi)
    behavioral_gate = behavioral_psi_gate(behavioral_psi)
    interaction_gate = interaction_psi_gate(interaction_psi, dominant_regime)
    combined_gate = structural_gate * behavioral_gate * interaction_gate
    return {
        "structural_gate": structural_gate,
        "behavioral_gate": behavioral_gate,
        "interaction_gate": interaction_gate,
        "psi_gate": combined_gate,
    }


def score_performance(expectancy: float, profit_factor: float) -> float:
    expectancy_z = bounded_z(expectancy, center=0.0, scale=0.0005)
    pf_z = bounded_z(profit_factor, center=1.0, scale=0.25)
    return 0.5 * sigmoid(expectancy_z) + 0.5 * sigmoid(pf_z)


def score_validity(perf_score: float, regime_drift: float, stability_component: float, gates: dict) -> tuple[float, float]:
    regime_score = score_regime_drift(regime_drift)
    pre_gate = (
        0.4 * perf_score
        + 0.3 * (1.0 - regime_score)
        + 0.3 * stability_component
    )
    return pre_gate * gates["psi_gate"], pre_gate


def classify_era(validity: float) -> str:
    if validity > 0.70:
        return "GREEN"
    if validity > 0.45:
        return "YELLOW"
    return "RED"


def run_timeline():
    X, y, regimes, returns, regime_features = assemble_manifold()
    years = X.index.year.unique()
    rows = []
    previous_shap = None

    for current_year in range(years[0] + 3, years[-1] + 1):
        train_mask = X.index.year <= current_year - 1
        oos_mask = X.index.year == current_year
        if oos_mask.sum() == 0:
            continue

        X_train, y_train, r_train = X[train_mask], y[train_mask], regimes[train_mask]
        X_oos, r_oos = X[oos_mask], regimes[oos_mask]

        ensemble = HybridRegimeEnsemble()
        ensemble.train(X_train, y_train, r_train)

        generator = RegimeAwareSignalGenerator(ensemble)
        signals = generator.generate_signals(X_oos, regime_features.loc[X_oos.index])
        scored = signals.copy()
        scored["returns"] = returns.shift(-1).loc[X_oos.index]
        scored["pnl"] = scored["signal"] * scored["risk_multiplier"] * scored["returns"]
        trades = scored[scored["signal"] != 0]
        metrics = calculate_expectancy(trades)

        expectancy = metrics.get("expectancy", 0)
        profit_factor = metrics.get("profit_factor", 0)
        recovery = metrics.get("recovery_factor", 0)
        perf_score = score_performance(expectancy, profit_factor)

        psi_components = grouped_feature_psi(X_train, X_oos)
        psi = psi_components["feature_psi"]
        regime_drift = regime_distribution_drift(r_train, r_oos)
        dominant_regime = r_oos.value_counts().idxmax()

        sample = X_oos.tail(min(250, len(X_oos)))
        current_shap = shap_importance(ensemble.global_model, sample)
        shap_drift = shap_instability(previous_shap, current_shap)
        previous_shap = current_shap

        expectancy_history = [row["expectancy"] for row in rows[-2:]] + [expectancy]
        consistency_penalty = min(float(np.std(expectancy_history)) / 0.0005, 1.0)

        stability_component = max(0.0, 1.0 - 0.5 * shap_drift - 0.5 * consistency_penalty)
        gates = psi_gate(
            psi_components["structural_psi"],
            psi_components["behavioral_psi"],
            psi_components["interaction_psi"],
            dominant_regime,
        )
        validity, pre_gate_validity = score_validity(perf_score, regime_drift, stability_component, gates)

        rows.append(
            {
                "window": current_year,
                "expectancy": expectancy,
                "profit_factor": profit_factor,
                "recovery": recovery,
                "n_trades": metrics.get("n_trades", 0),
                "perf_score": perf_score,
                "feature_psi": psi,
                "structural_psi": psi_components["structural_psi"],
                "behavioral_psi": psi_components["behavioral_psi"],
                "interaction_psi": psi_components["interaction_psi"],
                "dominant_regime": dominant_regime,
                "regime_drift": regime_drift,
                "regime_drift_score": score_regime_drift(regime_drift),
                "shap_instability": shap_drift,
                "consistency_penalty": consistency_penalty,
                "pre_gate_validity": pre_gate_validity,
                "structural_gate": gates["structural_gate"],
                "behavioral_gate": gates["behavioral_gate"],
                "interaction_gate": gates["interaction_gate"],
                "psi_gate": gates["psi_gate"],
                "validity": validity,
                "era": classify_era(validity),
            }
        )

    return pd.DataFrame(rows)


def main():
    timeline = run_timeline()
    print("\n" + "=" * 20 + " MODEL VALIDITY TIMELINE " + "=" * 20)
    display_cols = [
        "window",
        "expectancy",
        "profit_factor",
        "n_trades",
        "feature_psi",
        "structural_psi",
        "behavioral_psi",
        "interaction_psi",
        "dominant_regime",
        "regime_drift",
        "shap_instability",
        "consistency_penalty",
        "psi_gate",
        "validity",
        "era",
    ]
    print(timeline[display_cols].round(4).to_string(index=False))

    print("\nEra counts")
    print(timeline["era"].value_counts().to_string())

    print("\nMean validity by era")
    print(timeline.groupby("era")["validity"].mean().round(4).to_string())


if __name__ == "__main__":
    main()
