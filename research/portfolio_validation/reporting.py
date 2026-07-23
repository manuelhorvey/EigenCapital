"""Reporting — generates the portfolio A/B comparison report."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def print_comparison(
    results: dict[str, dict[str, Any]],
    comparison: dict[str, Any] | None = None,
) -> None:
    """Print the portfolio comparison report.

    Args:
        results: Dict of scenario name -> scenario results.
        comparison: Optional comparison dict from compare_portfolios().
    """
    print()
    print("=" * 70)
    print("  Portfolio A/B Simulation — Comparison Report")
    print("=" * 70)

    _print_scenario_summary(results)

    if comparison:
        _print_statistical_comparison(comparison)

    _print_asset_details(results)


def _print_scenario_summary(results: dict[str, dict[str, Any]]) -> None:
    """Print portfolio-level metrics for each scenario."""
    scenarios_order = ["A", "B", "C"]

    metrics_order = [
        ("portfolio_sharpe", "Sharpe"),
        ("portfolio_ece", "ECE"),
        ("portfolio_cal_inversion", "Cal Inversion"),
        ("portfolio_brier", "Brier"),
        ("portfolio_imbalance", "Avg Imbalance"),
        ("calibration_flips", "Calibration Flips"),
        ("n_assets_loaded", "Assets Loaded"),
    ]

    print()
    print("  Portfolio Metrics")
    print(f"  {'Metric':25s}", end="")
    for s in scenarios_order:
        if s in results:
            print(f"  {s:>12s}", end="")
    print()

    print("  " + "-" * (25 + 15 * len(scenarios_order)))

    for key, label in metrics_order:
        print(f"  {label:25s}", end="")
        for s in scenarios_order:
            if s in results:
                pm = results[s].get("portfolio_metrics", {})
                val = pm.get(key)
                if val is None:
                    print(f"  {'—':>12s}", end="")
                elif isinstance(val, float):
                    print(f"  {val:>12.4f}", end="")
                else:
                    print(f"  {str(val):>12s}", end="")
        print()

    print()
    print(f"  {'Scenario Description':25s}", end="")
    for s in scenarios_order:
        if s in results:
            desc = results[s].get("scenario_description", "")
            print(f"  {desc}")

    n_b = len(results.get("B", {}).get("asset_results", []))
    n_a = len(results.get("A", {}).get("asset_results", []))
    print(f"\n  Assets compared: {min(n_a, n_b)} common across scenarios")


def _print_statistical_comparison(comparison: dict[str, Any]) -> None:
    """Print per-metric statistical comparison with verdicts."""
    print()
    print("  " + "=" * 65)
    print("  Statistical Comparison — Scenario A vs B (paired t-test)")
    print("  " + "=" * 65)

    metric_labels = {
        "sharpe": "Sharpe",
        "ece": "ECE",
        "cal_inversion_rate": "Cal Inversion",
        "brier": "Brier",
    }

    header = f"  {'Metric':15s}  {'A Mean':>8s}  {'B Mean':>8s}  {'Delta':>8s}  {'p-value':>8s}  {'Verdict'}"
    print(header)
    print("  " + "-" * len(header))

    for metric, label in metric_labels.items():
        mc = comparison.get(metric)
        if mc is None:
            continue
        p_str = f"{mc['paired_t_p']:.4f}" if mc["paired_t_p"] is not None else "N/A"
        print(
            f"  {label:15s}  {mc['mean_a']:>8.4f}  "
            f"{mc['mean_b']:>8.4f}  {mc['delta']:>+8.4f}  "
            f"{p_str:>8s}  {mc['verdict']}"
        )

    beh = comparison.get("behavioral", {})
    if beh:
        print()
        print("  Behavioral Changes:")
        print(f"    Calibration flips (>0.5):  {beh.get('calibration_flips_a')} → {beh.get('calibration_flips_b')}")
        print(f"    Avg sell percentage:       {beh.get('avg_sell_pct_a'):.1%} → {beh.get('avg_sell_pct_b'):.1%}")

    sc = comparison.get("scenario_c")
    if sc:
        print()
        print("  Scenario C (Hybrid Diagnostic):")
        print(f"    Portfolio Sharpe: {sc.get('portfolio_sharpe')}")
        print(f"    Portfolio ECE:    {sc.get('portfolio_ece')}")


def _print_asset_details(results: dict[str, dict[str, Any]]) -> None:
    """Print per-asset comparison between scenarios."""
    assets_a = {r["asset"]: r for r in results.get("A", {}).get("asset_results", [])}
    assets_b = {r["asset"]: r for r in results.get("B", {}).get("asset_results", [])}
    common = sorted(set(assets_a.keys()) & set(assets_b.keys()))

    if not common:
        return

    print()
    print("  " + "=" * 100)
    print("  Per-Asset Detail")
    print("  " + "=" * 100)

    header = (
        f"  {'Asset':8s}  {'A Strat':>7s}  {'B Strat':>7s}  "
        f"{'A Sharpe':>8s}  {'B Sharpe':>8s}  "
        f"{'A ECE':>6s}  {'B ECE':>6s}  "
        f"{'A CalInv':>8s}  {'B CalInv':>8s}"
    )
    print(header)
    print("  " + "-" * len(header))

    for a in common:
        ra = assets_a[a]
        rb = assets_b[a]
        a_strat = ra.get("strategy", "?")
        b_strat = rb.get("strategy", "?")
        a_sharpe = f"{ra.get('sharpe', 0):.4f}"
        b_sharpe = f"{rb.get('sharpe', 0):.4f}"
        a_ece = f"{ra.get('ece', 0):.4f}"
        b_ece = f"{rb.get('ece', 0):.4f}"
        a_cal = f"{ra.get('cal_inversion_rate', 0):.4f}"
        b_cal = f"{rb.get('cal_inversion_rate', 0):.4f}"
        print(
            f"  {a:8s}  {a_strat:>7s}  {b_strat:>7s}  "
            f"{a_sharpe:>8s}  {b_sharpe:>8s}  "
            f"{a_ece:>6s}  {b_ece:>6s}  "
            f"{a_cal:>8s}  {b_cal:>8s}"
        )
    print()


def save_comparison_report(
    results: dict[str, dict[str, Any]],
    comparison: dict[str, Any] | None = None,
    path: str = "portfolio_comparison_report.txt",
) -> None:
    """Save the comparison report to a text file."""
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = StringIO()
    print_comparison(results, comparison)
    report = sys.stdout.getvalue()
    sys.stdout = old_stdout

    Path(path).write_text(report)
    print(f"Report saved to {path}")
