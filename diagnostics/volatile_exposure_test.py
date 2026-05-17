import numpy as np
import pandas as pd

from backtests.expectancy_audit import calculate_expectancy
from models.hybrid_ensemble import HybridRegimeEnsemble


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

    return X, y, regimes, returns


def freeze_walk_forward_predictions(X: pd.DataFrame, y: pd.Series, regimes: pd.Series) -> pd.DataFrame:
    years = X.index.year.unique()
    rows = []

    for current_year in range(years[0] + 3, years[-1] + 1):
        train_mask = X.index.year <= current_year - 1
        test_mask = X.index.year == current_year
        if test_mask.sum() == 0:
            continue

        X_train, y_train, r_train = X[train_mask], y[train_mask], regimes[train_mask]
        X_test, r_test = X[test_mask], regimes[test_mask]

        ensemble = HybridRegimeEnsemble()
        ensemble.train(X_train, y_train, r_train)
        probs = ensemble.predict_proba(X_test, r_test)

        window = pd.DataFrame(index=X_test.index)
        window["window"] = current_year
        window["regime"] = r_test
        window["raw_prob_short"] = probs[:, 0]
        window["raw_prob_neutral"] = probs[:, 1]
        window["raw_prob_long"] = probs[:, 2]
        window["P_volatile"] = X_test["P_volatile"]
        window["vol_zscore_proxy"] = X_test["P_volatile"].clip(0, 1)
        rows.append(window)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows).sort_index()


def direction_from_probs(df: pd.DataFrame) -> pd.Series:
    direction = pd.Series(0, index=df.index)
    direction[df["raw_prob_long"] >= df["raw_prob_short"]] = 1
    direction[df["raw_prob_short"] > df["raw_prob_long"]] = -1
    return direction


def apply_treatment(
    frozen: pd.DataFrame,
    treatment: str,
    base_threshold: float = 0.40,
    volatile_threshold: float = 0.40,
    forced_size: float = 0.10,
) -> pd.DataFrame:
    df = frozen.copy()
    df["signal"] = 0
    df["risk_multiplier"] = 1.0

    vol_mask = df["regime"] == "volatile"
    non_vol_mask = ~vol_mask

    df.loc[non_vol_mask & (df["raw_prob_long"] > base_threshold), "signal"] = 1
    df.loc[non_vol_mask & (df["raw_prob_short"] > base_threshold), "signal"] = -1

    if treatment == "current":
        df.loc[vol_mask & (df["raw_prob_long"] > base_threshold), "signal"] = 1
        df.loc[vol_mask & (df["raw_prob_short"] > base_threshold), "signal"] = -1
    elif treatment == "forced":
        df.loc[vol_mask, "signal"] = direction_from_probs(df.loc[vol_mask])
        df.loc[vol_mask, "risk_multiplier"] = forced_size
    elif treatment == "threshold":
        df.loc[vol_mask & (df["raw_prob_long"] > volatile_threshold), "signal"] = 1
        df.loc[vol_mask & (df["raw_prob_short"] > volatile_threshold), "signal"] = -1
    elif treatment == "vol_sized":
        df.loc[vol_mask, "signal"] = direction_from_probs(df.loc[vol_mask])
        vol_size = 0.05 + 0.20 * df.loc[vol_mask, "vol_zscore_proxy"]
        df.loc[vol_mask, "risk_multiplier"] = vol_size.clip(0.05, 0.25)
    else:
        raise ValueError(f"Unknown treatment: {treatment}")

    return df


def score_treatment(name: str, signals: pd.DataFrame, returns: pd.Series) -> dict:
    df = signals.copy()
    df["returns"] = returns.shift(-1).loc[df.index]
    df["pnl"] = df["signal"] * df["risk_multiplier"] * df["returns"]

    trades = df[df["signal"] != 0]
    volatile_trades = trades[trades["regime"] == "volatile"]
    metrics = calculate_expectancy(trades)
    volatile_metrics = calculate_expectancy(volatile_trades)

    total_pnl = trades["pnl"].sum()
    volatile_pnl = volatile_trades["pnl"].sum()
    contribution = volatile_pnl / (total_pnl + 1e-12)

    return {
        "treatment": name,
        "total_expectancy": metrics.get("expectancy", 0),
        "total_pf": metrics.get("profit_factor", 0),
        "total_recovery": metrics.get("recovery_factor", 0),
        "total_trades": metrics.get("n_trades", 0),
        "volatile_expectancy": volatile_metrics.get("expectancy", 0),
        "volatile_pf": volatile_metrics.get("profit_factor", 0),
        "volatile_recovery": volatile_metrics.get("recovery_factor", 0),
        "volatile_trades": volatile_metrics.get("n_trades", 0),
        "volatile_pnl": round(volatile_pnl, 6),
        "total_pnl": round(total_pnl, 6),
        "volatile_contribution": round(contribution, 4),
    }


def main():
    X, y, regimes, returns = assemble_manifold()
    frozen = freeze_walk_forward_predictions(X, y, regimes)

    print("=" * 20 + " VOLATILE EXPOSURE TEST " + "=" * 20)
    print(f"Frozen OOS rows: {len(frozen)}")
    print(f"VOLATILE OOS rows: {(frozen['regime'] == 'volatile').sum()}")

    treatments = [
        ("current", apply_treatment(frozen, "current")),
        ("forced_size_0.10", apply_treatment(frozen, "forced", forced_size=0.10)),
        ("forced_size_0.25", apply_treatment(frozen, "forced", forced_size=0.25)),
        ("vol_sized_0.05_0.25", apply_treatment(frozen, "vol_sized")),
    ]

    for threshold in [0.34, 0.36, 0.38, 0.40]:
        treatments.append(
            (
                f"vol_threshold_{threshold:.2f}",
                apply_treatment(frozen, "threshold", volatile_threshold=threshold),
            )
        )

    results = pd.DataFrame(
        [score_treatment(name, signals, returns) for name, signals in treatments]
    )

    print("\nTreatment results")
    print(results.to_string(index=False))

    print("\nInterpretation guide")
    print("A: forced exposure improves expectancy and recovery stays stable -> threshold suppression.")
    print("B: forced exposure improves expectancy but recovery/drawdown worsens -> sizing problem.")
    print("C: forced exposure worsens everything -> VOLATILE is risk-only or needs new features/objective.")


if __name__ == "__main__":
    main()
