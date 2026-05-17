import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from models.hybrid_ensemble import HybridRegimeEnsemble


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


def assemble_manifold(include_noise: bool = False):
    base = pd.read_parquet("data/processed/EURUSD_features.parquet")
    regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
    struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
    interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
    labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")

    common_idx = (
        base.index
        .intersection(regime_meta.index)
        .intersection(struct.index)
        .intersection(interact.index)
        .intersection(labeled.index)
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

    if include_noise:
        rng = np.random.default_rng(42)
        X["noise_baseline"] = rng.normal(size=len(X))

    y = labeled.loc[common_idx, "label"] + 1
    labels = labeled.loc[common_idx, "label"]
    regimes = regime_meta.loc[common_idx, "regime"]

    return X, y, labels, regimes


def shap_importance(model, X_sample: pd.DataFrame, class_idx: int = 2) -> pd.Series:
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

    return pd.Series(np.abs(values).mean(axis=0), index=X_sample.columns)


def signal_from_probs(probs: np.ndarray, threshold: float = 0.40) -> pd.Series:
    signals = np.zeros(len(probs), dtype=int)
    signals[probs[:, 2] > threshold] = 1
    signals[probs[:, 0] > threshold] = -1
    return pd.Series(signals)


def gate_feature_dominance(ensemble: HybridRegimeEnsemble, X: pd.DataFrame) -> GateResult:
    worst_model = None
    worst_feature = None
    worst_share = 0.0

    models = {"global": ensemble.global_model, **ensemble.expert_heads}
    for model_name, model in models.items():
        importance = pd.Series(model.feature_importances_, index=X.columns)
        total = importance.sum()
        if total == 0:
            continue
        share = importance / total
        feature = share.idxmax()
        if share.loc[feature] > worst_share:
            worst_model = model_name
            worst_feature = feature
            worst_share = share.loc[feature]

    return GateResult(
        "No single feature dominates >40%",
        worst_share <= 0.40,
        f"max={worst_share:.2%} ({worst_model}.{worst_feature})",
    )


def gate_path_efficiency_used(ensemble: HybridRegimeEnsemble, X: pd.DataFrame) -> GateResult:
    path_cols = ["path_efficiency_20", "path_efficiency_63"]
    models = {"global": ensemble.global_model, **ensemble.expert_heads}

    used = []
    for model_name, model in models.items():
        importance = pd.Series(model.feature_importances_, index=X.columns)
        for col in path_cols:
            if importance.get(col, 0) > 0:
                used.append(f"{model_name}.{col}")

    return GateResult(
        "Path efficiency used in at least one model",
        bool(used),
        ", ".join(used) if used else "no nonzero path-efficiency importance",
    )


def gate_curvature_beats_noise(X: pd.DataFrame, y: pd.Series, regimes: pd.Series) -> GateResult:
    X_noise = X.copy()
    rng = np.random.default_rng(42)
    X_noise["noise_baseline"] = rng.normal(size=len(X_noise))

    ensemble = HybridRegimeEnsemble()
    ensemble.train(X_noise, y, regimes)

    curvature_cols = ["curvature_20", "curvature_10"]
    models = {"global": ensemble.global_model, **ensemble.expert_heads}
    best_margin = -np.inf
    best_detail = "no eligible models"

    for model_name, model in models.items():
        sample = X_noise if model_name == "global" else X_noise.loc[regimes == model_name]
        if len(sample) < 50:
            continue
        sample = sample.tail(min(300, len(sample)))
        importance = shap_importance(model, sample)
        curvature_score = importance.reindex(curvature_cols).fillna(0).max()
        noise_score = importance.get("noise_baseline", 0.0)
        margin = curvature_score - noise_score
        if margin > best_margin:
            best_margin = margin
            best_detail = (
                f"best={model_name}, curvature={curvature_score:.6g}, "
                f"noise={noise_score:.6g}, margin={margin:.6g}"
            )

    return GateResult(
        "Curvature SHAP importance > noise baseline",
        best_margin > 0,
        best_detail,
    )


def gate_transition_risk_ablation(
    ensemble: HybridRegimeEnsemble,
    X: pd.DataFrame,
    labels: pd.Series,
    regimes: pd.Series,
) -> GateResult:
    if "transition_risk" not in X.columns:
        return GateResult("Transition risk reduces switch false positives", False, "missing transition_risk")

    switch_mask = X["transition_risk"] >= X["transition_risk"].quantile(0.75)
    if switch_mask.sum() == 0:
        return GateResult("Transition risk reduces switch false positives", False, "no switch-period samples")

    actual_probs = ensemble.predict_proba(X, regimes)
    ablated = X.copy()
    ablated["transition_risk"] = 0.0
    ablated_probs = ensemble.predict_proba(ablated, regimes)

    actual_signals = signal_from_probs(actual_probs).set_axis(X.index)
    ablated_signals = signal_from_probs(ablated_probs).set_axis(X.index)

    actual_fp = ((actual_signals != 0) & (actual_signals != labels) & switch_mask).sum()
    ablated_fp = ((ablated_signals != 0) & (ablated_signals != labels) & switch_mask).sum()

    return GateResult(
        "Transition risk reduces switch false positives",
        actual_fp < ablated_fp,
        f"actual_fp={actual_fp}, ablated_fp={ablated_fp}, switch_samples={int(switch_mask.sum())}",
    )


def gate_directional_consistency(ensemble: HybridRegimeEnsemble, X: pd.DataFrame, regimes: pd.Series) -> list[GateResult]:
    results = []
    delta = 0.05
    epsilon = 1e-6

    if "trend" in ensemble.expert_heads:
        sample = X.loc[regimes == "trend"].tail(300)
        perturbed = sample.copy()
        perturbed["P_trend"] = (perturbed["P_trend"] + delta).clip(upper=1.0)
        sample_regimes = pd.Series("trend", index=sample.index)
        base_long = ensemble.predict_proba(sample, sample_regimes)[:, 2].mean()
        perturbed_long = ensemble.predict_proba(perturbed, sample_regimes)[:, 2].mean()
        results.append(
            GateResult(
                "TREND: P_trend increase raises long probability",
                perturbed_long > base_long + epsilon,
                f"base={base_long:.6f}, perturbed={perturbed_long:.6f}",
            )
        )
    else:
        results.append(GateResult("TREND: P_trend increase raises long probability", False, "missing trend expert"))

    if "range" in ensemble.expert_heads:
        sample = X.loc[regimes == "range"].tail(300)
        perturbed = sample.copy()
        perturbed["P_range"] = (perturbed["P_range"] + delta).clip(upper=1.0)
        sample_regimes = pd.Series("range", index=sample.index)
        base_probs = ensemble.predict_proba(sample, sample_regimes)
        perturbed_probs = ensemble.predict_proba(perturbed, sample_regimes)
        base_strength = (base_probs[:, 0] + base_probs[:, 2]).mean()
        perturbed_strength = (perturbed_probs[:, 0] + perturbed_probs[:, 2]).mean()
        results.append(
            GateResult(
                "RANGE: P_range increase raises mean-reversion strength",
                perturbed_strength > base_strength + epsilon,
                f"base={base_strength:.6f}, perturbed={perturbed_strength:.6f}",
            )
        )
    else:
        results.append(GateResult("RANGE: P_range increase raises mean-reversion strength", False, "missing range expert"))

    if "volatile" in ensemble.expert_heads:
        sample = X.loc[regimes == "volatile"].tail(300)
        perturbed = sample.copy()
        perturbed["P_volatile"] = (perturbed["P_volatile"] + delta).clip(upper=1.0)
        sample_regimes = pd.Series("volatile", index=sample.index)
        base_probs = ensemble.predict_proba(sample, sample_regimes)
        perturbed_probs = ensemble.predict_proba(perturbed, sample_regimes)
        base_exposure = np.maximum(base_probs[:, 0], base_probs[:, 2]).mean()
        perturbed_exposure = np.maximum(perturbed_probs[:, 0], perturbed_probs[:, 2]).mean()
        passed = perturbed_exposure < base_exposure - epsilon
        detail = f"base={base_exposure:.6f}, perturbed={perturbed_exposure:.6f}"
    else:
        sample = X[X["P_volatile"] < 0.95].tail(300)
        perturbed = sample.copy()
        perturbed["P_volatile"] = (perturbed["P_volatile"] + delta).clip(upper=1.0)
        sample_regimes = pd.Series("volatile", index=sample.index)
        base_probs = ensemble.predict_proba(sample, sample_regimes)
        perturbed_probs = ensemble.predict_proba(perturbed, sample_regimes)
        base_exposure = np.maximum(base_probs[:, 0], base_probs[:, 2]).mean()
        perturbed_exposure = np.maximum(perturbed_probs[:, 0], perturbed_probs[:, 2]).mean()
        passed = perturbed_exposure < base_exposure - epsilon
        detail = (
            f"volatile expert unavailable; checked global fallback. "
            f"base={base_exposure:.6f}, perturbed={perturbed_exposure:.6f}"
        )

    results.append(
        GateResult(
            "VOLATILE: P_volatile increase lowers exposure",
            passed,
            detail,
        )
    )

    return results


def print_result(result: GateResult):
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.name}: {result.detail}")


def main() -> int:
    X, y, labels, regimes = assemble_manifold()

    ensemble = HybridRegimeEnsemble()
    ensemble.train(X, y, regimes)

    results = [
        gate_feature_dominance(ensemble, X),
        gate_path_efficiency_used(ensemble, X),
        gate_transition_risk_ablation(ensemble, X, labels, regimes),
        gate_curvature_beats_noise(X, y, regimes),
    ]
    results.extend(gate_directional_consistency(ensemble, X, regimes))

    print("\n" + "=" * 24 + " PHASE 3 VALIDATION " + "=" * 24)
    for result in results:
        print_result(result)

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"\nPHASE 3 STATUS: FAIL ({len(failed)} gate(s) failed)")
        return 1

    print("\nPHASE 3 STATUS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
