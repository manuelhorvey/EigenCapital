"""Reporting and comparison utilities for label optimization experiments."""

from __future__ import annotations

from typing import Any

import pandas as pd


def results_dataframe(experiments: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert experiment results to a flat DataFrame for analysis."""
    rows = []
    for exp in experiments:
        row = {
            "experiment_id": exp.get("experiment_id", ""),
            "asset": exp.get("asset", ""),
            "label_method": exp.get("label_method", ""),
            "pt": exp.get("pt", 0),
            "sl": exp.get("sl", 0),
            "vb": exp.get("vb", 0),
            "status": exp.get("status", ""),
        }
        for prefix in ["buy_pct", "sell_pct", "timeout_pct", "entropy", "imbalance_ratio",
                       "auc", "ece", "brier", "calibration_slope",
                       "sharpe", "sortino", "profit_factor", "cagr_pct",
                       "total_return_pct", "max_drawdown_pct", "win_rate_pct",
                       "avg_r", "total_r", "trade_count", "calmar_ratio",
                       "cal_inversion_rate", "avg_pred_buy_pct", "pred_entropy",
                       "composite_score"]:
            row[prefix] = exp.get(prefix, None)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col not in ["experiment_id", "asset", "label_method", "status"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def print_comparison_table(df: pd.DataFrame, asset: str | None = None) -> None:
    """Print a human-readable comparison table grouped by asset."""
    if asset:
        df = df[df["asset"] == asset].copy()
    if df.empty:
        print("No results to display.")
        return
    group_cols = ["asset", "pt", "sl", "vb"]
    display_cols = [
        "sell_pct", "imbalance_ratio",
        "sharpe", "profit_factor",
        "ece", "brier",
        "cal_inversion_rate", "composite_score",
    ]
    available = [c for c in display_cols if c in df.columns]
    table = df.groupby(group_cols)[available].first().round(4)
    print(f"\n{'='*80}")
    print(f"Label Optimization Results{' for ' + asset if asset else ''}")
    print(f"{'='*80}")
    print(table.to_string())
    print(f"{'='*80}\n")


def print_pareto_summary(ranked: list[dict[str, Any]]) -> None:
    """Print Pareto-optimal experiments per asset."""
    from collections import defaultdict

    grouped = defaultdict(list)
    for exp in ranked:
        grouped[exp["asset"]].append(exp)

    for asset, experiments in sorted(grouped.items()):
        front = [e for e in experiments if e.get("pareto_front")]
        if not front:
            continue
        print(f"\n{'─'*60}")
        print(f"  {asset} — Pareto-optimal configurations")
        print(f"{'─'*60}")
        for e in sorted(front, key=lambda x: x.get("composite_score", 0), reverse=True):
            pt = e.get("pt", "?")
            sl = e.get("sl", "?")
            sharpe = e.get("sharpe", 0)
            pf = e.get("profit_factor", 0)
            total_r = e.get("total_r", 0)
            composite = e.get("composite_score", 0)
            print(f"    PT={pt:.1f} SL={sl:.1f}  "
                  f"Sharpe={sharpe:.3f}  PF={pf:.3f}  "
                  f"TotalR={total_r:.1f}  Score={composite:.3f}")


def save_report(experiments: list[dict[str, Any]], path: str = "data/processed/label_opt_report.csv") -> None:
    """Save all experiment results to CSV."""
    df = results_dataframe(experiments)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Report saved to {path}")
