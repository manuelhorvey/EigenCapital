import pandas as pd

from diagnostics.model_validity_timeline import run_timeline


def safe_corr(df: pd.DataFrame, left: str, right: str) -> float:
    if df[left].nunique() < 2 or df[right].nunique() < 2:
        return 0.0
    return float(df[left].corr(df[right], method="spearman"))


def bucket_response(df: pd.DataFrame, column: str, buckets: int = 3) -> pd.DataFrame:
    labels = [f"q{i + 1}" for i in range(buckets)]
    bucket_col = f"{column}_bucket"
    out = df.copy()
    out[bucket_col] = pd.qcut(out[column], q=buckets, labels=labels, duplicates="drop")
    return (
        out.groupby(bucket_col, observed=True)
        .agg(
            windows=("window", "count"),
            avg_psi=(column, "mean"),
            avg_validity=("validity", "mean"),
            avg_expectancy=("expectancy", "mean"),
            avg_pf=("profit_factor", "mean"),
            green_rate=("era", lambda x: (x == "GREEN").mean()),
            red_rate=("era", lambda x: (x == "RED").mean()),
        )
        .reset_index()
    )


def main():
    timeline = run_timeline()

    cols = [
        "window",
        "expectancy",
        "profit_factor",
        "structural_psi",
        "behavioral_psi",
        "interaction_psi",
        "structural_gate",
        "behavioral_gate",
        "interaction_gate",
        "psi_gate",
        "pre_gate_validity",
        "validity",
        "era",
    ]

    print("\n" + "=" * 20 + " PSI RESPONSE CURVES " + "=" * 20)
    print(timeline[cols].round(4).to_string(index=False))

    print("\nSpearman correlations")
    rows = []
    for psi_col in ["structural_psi", "behavioral_psi", "interaction_psi", "psi_gate"]:
        rows.append(
            {
                "component": psi_col,
                "corr_validity": safe_corr(timeline, psi_col, "validity"),
                "corr_expectancy": safe_corr(timeline, psi_col, "expectancy"),
                "corr_profit_factor": safe_corr(timeline, psi_col, "profit_factor"),
            }
        )
    print(pd.DataFrame(rows).round(4).to_string(index=False))

    for psi_col in ["structural_psi", "behavioral_psi", "interaction_psi"]:
        print(f"\nBucket response: {psi_col}")
        print(bucket_response(timeline, psi_col).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
