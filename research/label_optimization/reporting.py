"""Reporting and comparison utilities for label optimization experiments."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


def results_dataframe(experiments: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for exp in experiments:
        row = {
            "experiment_id": exp.get("experiment_id", ""),
            "asset": exp.get("asset", ""),
            "label_method": exp.get("label_method", ""),
            "label_strategy_version": exp.get("label_strategy_version", ""),
            "pt": exp.get("pt", 0),
            "sl": exp.get("sl", 0),
            "vb": exp.get("vb", 0),
            "status": exp.get("status", ""),
        }
        keys = [
            "buy_pct", "sell_pct", "entropy", "imbalance_ratio",
            "auc_mean", "auc_std",
            "ece_mean", "ece_std", "ece_ci95",
            "brier_mean", "brier_std",
            "sharpe_mean", "sharpe_std", "sharpe_ci95",
            "profit_factor_mean", "profit_factor_std",
            "total_return_pct", "max_drawdown_mean",
            "cal_inversion_rate_mean", "cal_inversion_rate_std",
            "edge_retention", "composite_score",
        ]
        for k in keys:
            row[k] = exp.get(k, None)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col not in ["experiment_id", "asset", "label_method", "label_strategy_version", "status"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def print_comparison_table(df: pd.DataFrame, asset: str | None = None) -> None:
    if asset:
        df = df[df["asset"] == asset].copy()
    if df.empty:
        print("No results to display.")
        return
    group_cols = ["asset", "pt", "sl"]
    display_cols = [
        "sell_pct", "imbalance_ratio",
        "sharpe_mean", "sharpe_ci95", "ece_mean", "ece_ci95",
        "cal_inversion_rate_mean", "edge_retention", "composite_score",
    ]
    available = [c for c in display_cols if c in df.columns and df[c].notna().any()]

    def fmt(val, ci=None):
        if pd.isna(val):
            return "  N/A  "
        if ci is not None and not pd.isna(ci):
            return f"{val:.3f} ±{ci:.3f}"
        return f"{val:.3f}"

    # Build table rows manually for CI formatting
    print(f"\n{'='*90}")
    print(f"Label Optimization Results{' for ' + asset if asset else ''}")
    print(f"{'='*90}")
    header = f"{'PT':>5} {'SL':>5}  "
    for c in available:
        if c in ["sharpe_mean", "ece_mean"]:
            header += f"{c:>18}"
        else:
            header += f"{c:>12}"
    print(header)
    print("-" * 90)
    for _, r in df.sort_values(["pt", "sl"]).iterrows():
        line = f"{int(r['pt']):>5} {int(r['sl']):>5}  "
        for c in available:
            val = r.get(c)
            ci_key = None
            if c.endswith("_mean"):
                base = c[:-5]
                ci_key = f"{base}_ci95"
            ci_val = r.get(ci_key) if ci_key else None
            if c in ["sharpe_mean", "ece_mean"] and ci_val is not None:
                line += f"{val:>8.3f} ±{ci_val:>6.3f} " if pd.notna(val) and pd.notna(ci_val) else f"{'N/A':>18} "
            elif c == "edge_retention":
                line += f"{val:>11.3f} " if pd.notna(val) else f"{'N/A':>11} "
            elif c == "composite_score":
                line += f"{val:>10.3f} " if pd.notna(val) else f"{'N/A':>10} "
            else:
                line += f"{val:>11.3f} " if pd.notna(val) else f"{'N/A':>11} "
        print(line)
    print(f"{'='*90}\n")


def print_pareto_summary(ranked: list[dict[str, Any]]) -> None:
    grouped = defaultdict(list)
    for exp in ranked:
        grouped[exp["asset"]].append(exp)

    for asset, experiments in sorted(grouped.items()):
        front = [e for e in experiments if e.get("pareto_front")]
        if not front:
            continue
        print(f"\n{'─'*65}")
        print(f"  {asset} — Pareto-optimal configurations")
        print(f"{'─'*65}")
        for e in sorted(front, key=lambda x: x.get("composite_score", 0), reverse=True):
            pt = e.get("pt", "?")
            sl = e.get("sl", "?")
            sharpe = e.get("sharpe_mean") or e.get("sharpe", 0)
            ece = e.get("ece_mean") or e.get("ece", 0)
            er = e.get("edge_retention", 0)
            cs = e.get("composite_score", 0)
            print(f"    PT={pt:.1f} SL={sl:.1f}  "
                  f"Sharpe={sharpe:.3f}  ECE={ece:.4f}  "
                  f"EdgeRet={er:.3f}  Score={cs:.3f}")


def save_report(experiments: list[dict[str, Any]], path: str = "data/processed/label_opt_report.csv") -> None:
    df = results_dataframe(experiments)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Report saved to {path}")
