import pandas as pd

from diagnostics.model_validity_timeline import (
    assemble_manifold,
    classify_era,
    grouped_feature_psi,
    psi_gate,
    regime_distribution_drift,
    score_performance,
    score_regime_drift,
    score_validity,
    shap_importance,
    shap_instability,
)
from backtests.expectancy_audit import calculate_expectancy
from models.hybrid_ensemble import HybridRegimeEnsemble
from signals.signal_generator import RegimeAwareSignalGenerator


NO_PSI_GATES = {
    "structural_gate": 1.0,
    "behavioral_gate": 1.0,
    "interaction_gate": 1.0,
    "psi_gate": 1.0,
}


def run_base_measurements() -> pd.DataFrame:
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

        metrics = calculate_expectancy(scored[scored["signal"] != 0])
        expectancy = metrics.get("expectancy", 0)
        profit_factor = metrics.get("profit_factor", 0)
        perf_score = score_performance(expectancy, profit_factor)

        psi_components = grouped_feature_psi(X_train, X_oos)
        psi = psi_components["feature_psi"]
        regime_drift = regime_distribution_drift(r_train, r_oos)
        dominant_regime = r_oos.value_counts().idxmax()
        gates = psi_gate(
            psi_components["structural_psi"],
            psi_components["behavioral_psi"],
            psi_components["interaction_psi"],
            dominant_regime,
        )

        sample = X_oos.tail(min(250, len(X_oos)))
        current_shap = shap_importance(ensemble.global_model, sample)
        shap_drift = shap_instability(previous_shap, current_shap)
        previous_shap = current_shap

        expectancy_history = [row["expectancy"] for row in rows[-2:]] + [expectancy]
        consistency_penalty = min(float(pd.Series(expectancy_history).std(ddof=0)) / 0.0005, 1.0)
        stability_component = max(0.0, 1.0 - 0.5 * shap_drift - 0.5 * consistency_penalty)

        rows.append(
            {
                "window": current_year,
                "expectancy": expectancy,
                "profit_factor": profit_factor,
                "n_trades": metrics.get("n_trades", 0),
                "perf_score": perf_score,
                "psi": psi,
                "structural_psi": psi_components["structural_psi"],
                "behavioral_psi": psi_components["behavioral_psi"],
                "interaction_psi": psi_components["interaction_psi"],
                "dominant_regime": dominant_regime,
                "regime_drift": regime_drift,
                "regime_drift_score": score_regime_drift(regime_drift),
                "shap_instability": shap_drift,
                "consistency_penalty": consistency_penalty,
                "stability_component": stability_component,
                "structural_gate": gates["structural_gate"],
                "behavioral_gate": gates["behavioral_gate"],
                "interaction_gate": gates["interaction_gate"],
                "psi_gate": gates["psi_gate"],
            }
        )

    return pd.DataFrame(rows)


def add_variants(base: pd.DataFrame) -> pd.DataFrame:
    df = base.copy()
    variants = ["current", "no_psi", "no_regime_drift", "no_drift"]

    for variant in variants:
        scores = []
        eras = []
        for _, row in df.iterrows():
            gates = {
                "structural_gate": row["structural_gate"],
                "behavioral_gate": row["behavioral_gate"],
                "interaction_gate": row["interaction_gate"],
                "psi_gate": row["psi_gate"],
            }
            regime_drift = row["regime_drift"]
            if variant == "no_psi":
                gates = NO_PSI_GATES
            elif variant == "no_regime_drift":
                regime_drift = 0.0
            elif variant == "no_drift":
                gates = NO_PSI_GATES
                regime_drift = 0.0

            score, _ = score_validity(row["perf_score"], regime_drift, row["stability_component"], gates)
            scores.append(score)
            eras.append(classify_era(score))
        df[f"{variant}_validity"] = scores
        df[f"{variant}_era"] = eras

    df["performance_only_validity"] = df["perf_score"]
    df["performance_only_era"] = df["performance_only_validity"].apply(classify_era)

    era_cols = [
        "current_era",
        "no_psi_era",
        "no_regime_drift_era",
        "no_drift_era",
        "performance_only_era",
    ]
    df["classification_delta"] = df[era_cols].nunique(axis=1) > 1
    return df


def classification_consistency(df: pd.DataFrame) -> pd.DataFrame:
    variants = ["no_psi", "no_regime_drift", "no_drift", "performance_only"]
    rows = []
    for variant in variants:
        unchanged = (df["current_era"] == df[f"{variant}_era"]).mean()
        rows.append(
            {
                "variant": variant,
                "classification_consistency": unchanged,
                "changed_windows": int((df["current_era"] != df[f"{variant}_era"]).sum()),
            }
        )
    return pd.DataFrame(rows)


def main():
    base = run_base_measurements()
    sensitivity = add_variants(base)

    display_cols = [
        "window",
        "expectancy",
        "profit_factor",
        "structural_psi",
        "behavioral_psi",
        "interaction_psi",
        "psi_gate",
        "current_validity",
        "current_era",
        "no_psi_validity",
        "no_psi_era",
        "no_regime_drift_validity",
        "no_regime_drift_era",
        "no_drift_validity",
        "no_drift_era",
        "performance_only_validity",
        "performance_only_era",
        "classification_delta",
    ]

    print("\n" + "=" * 20 + " VALIDITY SENSITIVITY " + "=" * 20)
    print(sensitivity[display_cols].round(4).to_string(index=False))

    print("\nClassification consistency vs current")
    print(classification_consistency(sensitivity).round(4).to_string(index=False))

    print("\nEra counts by variant")
    era_count_rows = []
    for variant in ["current", "no_psi", "no_regime_drift", "no_drift", "performance_only"]:
        counts = sensitivity[f"{variant}_era"].value_counts().to_dict()
        era_count_rows.append(
            {
                "variant": variant,
                "GREEN": counts.get("GREEN", 0),
                "YELLOW": counts.get("YELLOW", 0),
                "RED": counts.get("RED", 0),
            }
        )
    print(pd.DataFrame(era_count_rows).to_string(index=False))


if __name__ == "__main__":
    main()
