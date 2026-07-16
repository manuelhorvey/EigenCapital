#!/usr/bin/env python3
"""
EigenCapital — Robustness Surface: Systematic ±10% Perturbation Grid
====================================================================

Phase 7 from the Institutional Audit: determines whether the system's
performance lies on a **broad plateau** (small parameter changes →
small performance changes) or a **fragile optimum** (small changes →
large degradation).

Methodology
-----------
1. Load all historical trades from trade lifecycle data.
2. For each of 5 parameters, apply perturbations: -10%, -5%, 0%, +5%, +10%.
3. For each perturbation, re-run the full capital growth simulation
   (compounding, drawdown taper, min-lot constraints, spread costs).
4. Classify each parameter's robustness via elasticity:
       elasticity = (%Δ metric) / (%Δ parameter)
   - |elasticity| < 1.0 → robust (plateau)
   - |elasticity| ≥ 1.0 → sensitive (fragile)
5. Run combined scenarios (worst 2 parameters together) for stress.
6. Generate a robustness surface chart and JSON report.

Parameters perturbed
--------------------
1. confidence_threshold — BUY (0.45) and SELL (0.55) thresholds relative ±10%
2. max_risk_per_trade_pct  — production 1.0%, ±10%
3. tp_mult — scale winning R-multiples ±10% (TP multiplier proxy)
4. sl_mult — scale losing R-multiples ±10% (SL multiplier proxy)
5. max_position_pct_of_equity — production 15%, ±10%

Usage
-----
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_surface.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_surface.py --start-capital 5000
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_surface.py --fast
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from scripts.backtest.capital_growth_simulation import (
    ASSET_CLASS_MAP,
    ASSET_CLASS_PARAMS,
    SizingParams,
    compute_performance_metrics,
    load_sizing_params,
    load_trades,
    run_simulation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.robustness_surface")

# ── Paths ─────────────────────────────────────────────────────────────────────
TRADE_PATH = ROOT / "data" / "processed" / "audits" / "trade_lifecycle_results.json"
OUTPUT_JSON = ROOT / "data" / "processed" / "audits" / "robustness_surface.json"
CHART_PATH = ROOT / "data" / "processed" / "charts" / "robustness_surface.png"
REPORT_PATH = ROOT / "data" / "processed" / "reports" / "ROBUSTNESS_SURFACE_REPORT.md"

# ── Production baseline parameters (fallback if config load fails) ────────────
PROD_BUY_THRESHOLD = 0.45
PROD_SELL_THRESHOLD = 0.55
PROD_RISK_PCT = 1.0
PROD_MAX_POSITION_PCT = 0.15

# ── Perturbation grid ────────────────────────────────────────────────────────
# deltas are RELATIVE multipliers applied to the production value.
# e.g., delta=-0.10 means production_value * (1 - 0.10) = 90% of production.
PERTURBATIONS: list[dict[str, Any]] = [
    {
        "key": "confidence_threshold",
        "label": "Confidence Threshold",
        "deltas": [-0.10, -0.05, 0.0, 0.05, 0.10],
    },
    {
        "key": "max_risk_per_trade_pct",
        "label": "Risk per Trade",
        "deltas": [-0.10, -0.05, 0.0, 0.05, 0.10],
    },
    {
        "key": "tp_mult",
        "label": "TP Multiplier (wins)",
        "deltas": [-0.10, -0.05, 0.0, 0.05, 0.10],
    },
    {
        "key": "sl_mult",
        "label": "SL Multiplier (losses)",
        "deltas": [-0.10, -0.05, 0.0, 0.05, 0.10],
    },
    {
        "key": "max_position_pct_of_equity",
        "label": "Max Position %% of Equity",
        "deltas": [-0.10, -0.05, 0.0, 0.05, 0.10],
    },
]

COMBINED_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "worst_2_risk_params",
        "label": "Worst: Higher Risk + Smaller Position",
        "perturbations": {
            "max_risk_per_trade_pct": 0.10,
            "max_position_pct_of_equity": -0.10,
        },
    },
    {
        "name": "worst_2_trade_params",
        "label": "Worst: Smaller TP + Wider SL",
        "perturbations": {
            "tp_mult": -0.10,
            "sl_mult": 0.10,
        },
    },
    {
        "name": "best_2_risk_params",
        "label": "Best: Lower Risk + Bigger Position",
        "perturbations": {
            "max_risk_per_trade_pct": -0.10,
            "max_position_pct_of_equity": 0.10,
        },
    },
    {
        "name": "best_2_trade_params",
        "label": "Best: Bigger TP + Tighter SL",
        "perturbations": {
            "tp_mult": 0.10,
            "sl_mult": -0.10,
        },
    },
    {
        "name": "worst_4_all",
        "label": "ALL 4 Adverse (worst config)",
        "perturbations": {
            "confidence_threshold": 0.10,
            "max_risk_per_trade_pct": 0.10,
            "tp_mult": -0.10,
            "sl_mult": 0.10,
            "max_position_pct_of_equity": -0.10,
        },
    },
]


# ── Data loading with p_long ──────────────────────────────────────────────────


def load_raw_trade_dicts(path: Path) -> list[dict]:
    """Load raw trade dicts from the trade lifecycle JSON (preserves p_long)."""
    with open(path) as f:
        data = json.load(f)
    raw_trades = data.get("_trades", {})
    all_trades = []
    for asset_name, trades in raw_trades.items():
        for t in trades:
            t["_asset"] = asset_name
            all_trades.append(t)
    logger.info("Loaded %d raw trade dicts across %d assets", len(all_trades), len(raw_trades))
    return all_trades


def filter_by_confidence(
    raw_trades: list[dict],
    buy_threshold: float,
    sell_threshold: float,
) -> list[dict]:
    """Filter trades by modified confidence thresholds using raw p_long values.

    Keeps trades where the signal confidence meets the direction-specific
    threshold. Lower thresholds keep all existing trades (cannot add trades
    that weren't taken). Higher thresholds remove marginal trades.

    Returns (filtered_trades, n_skipped).
    """
    filtered = []
    skipped = 0
    for t in raw_trades:
        p_long = float(t.get("p_long", 0.5) or 0.5)
        side = t.get("side", "BUY")
        if side == "BUY":
            if p_long >= buy_threshold:
                filtered.append(t)
            else:
                skipped += 1
        else:  # SELL
            if (1.0 - p_long) >= sell_threshold:
                filtered.append(t)
            else:
                skipped += 1
    return filtered, skipped


# ── Timestamp normalization ───────────────────────────────────────────────────


def _norm_ts(ts: str) -> str:
    """Normalize a timestamp string for cross-referencing.

    Strips trailing ``Z`` and any ``+HH:MM`` timezone suffix so that
    raw-JSON timestamps (which may have ``Z``) match
    ``datetime.isoformat()`` output (which is naive after ``parse_dt``).
    """
    return ts.replace("Z", "").split("+")[0]


# ── Perturbation runner ──────────────────────────────────────────────────────


def _perturb_trades(trades: list, param_key: str, delta: float) -> list:
    """Apply a perturbation to a trade list, returning a new list.

    For TP/SL, creates copies with modified r_multiple.
    For other params, returns the list unchanged (params handled separately).
    """
    if param_key not in ("tp_mult", "sl_mult"):
        return list(trades)

    result = []
    for t in trades:
        r = float(t.r_multiple)
        if param_key == "tp_mult" and r > 0:
            new_t = replace(t, r_multiple=r * (1.0 + delta))
            result.append(new_t)
        elif param_key == "sl_mult" and r < 0:
            new_t = replace(t, r_multiple=r * (1.0 + delta))
            result.append(new_t)
        else:
            result.append(t)
    return result


def _perturb_params(params: SizingParams, param_key: str, delta: float) -> SizingParams:
    """Return a copy of SizingParams with the perturbed field.

    Perturbations are applied RELATIVE to the passed-in ``params`` values,
    not the hardcoded PROD_* constants.  This ensures that if the config
    file has different baseline values, the +/-10%% grid is anchored
    correctly.
    """
    import copy

    p = copy.deepcopy(params)
    if param_key == "max_risk_per_trade_pct":
        new_val = p.max_risk_per_trade_pct * (1.0 + delta)
        p.max_risk_per_trade_pct = max(0.25, min(5.0, new_val))
    elif param_key == "max_position_pct_of_equity":
        new_val = p.max_position_pct * (1.0 + delta)
        p.max_position_pct = max(0.02, min(0.50, new_val))
    return p


def _run_and_measure(
    trades: list,
    start_capital: float,
    params: SizingParams,
    label: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run capital simulation and return metrics dict."""
    t0 = time.time()
    state = run_simulation(trades, start_capital, params, adaptive_exit=True)
    metrics = compute_performance_metrics(state, start_capital)
    elapsed = time.time() - t0

    result = {
        "label": label,
        "final_capital": round(metrics["final_capital"], 2),
        "net_profit": round(metrics["net_profit"], 2),
        "total_return_pct": round(metrics["total_return_pct"], 2),
        "cagr_pct": round(metrics["cagr_pct"], 2),
        "sharpe_ratio": round(metrics["sharpe_ratio"], 4),
        "sortino_ratio": round(metrics["sortino_ratio"], 4),
        "calmar_ratio": round(metrics["calmar_ratio"], 4),
        "max_drawdown_pct": round(metrics["max_drawdown_pct"], 2),
        "profit_factor": round(metrics["profit_factor"], 2),
        "day_win_rate_pct": round(metrics["day_win_rate_pct"], 1),
        "trade_win_rate_pct": round(metrics["trade_win_rate_pct"], 1),
        "expectancy": round(metrics["expectancy"], 2),
        "recovery_factor": round(metrics["recovery_factor"], 2),
        "annualized_volatility_pct": round(metrics["annualized_volatility_pct"], 2),
        "total_trades": len(trades),
        "final_equity": round(state.equity, 2),
        "peak_equity": round(state.peak_equity, 2),
        "elapsed_seconds": round(elapsed, 2),
    }
    if extra:
        result.update(extra)
    return result


# ── Elasticity ────────────────────────────────────────────────────────────────


def compute_elasticity(baseline: float, perturbed: float, delta: float) -> float:
    """elasticity = (%%Δ metric) / (%%Δ parameter).

    |el| < 1.0 → robust; |el| >= 1.0 → sensitive.
    """
    if delta == 0.0 or baseline == 0:
        return 0.0
    metric_change = (perturbed - baseline) / abs(baseline)
    return metric_change / delta


def classify_robustness(elasticity: float) -> str:
    ae = abs(elasticity)
    if ae < 0.3:
        return "VERY_ROBUST"
    elif ae < 0.7:
        return "ROBUST"
    elif ae < 1.0:
        return "MODERATE"
    elif ae < 2.0:
        return "SENSITIVE"
    else:
        return "FRAGILE"


# ── Grid runner ──────────────────────────────────────────────────────────────


def run_perturbation_grid(
    trades: list,
    raw_trades: list[dict],
    start_capital: float = 500.0,
    fast: bool = False,
) -> dict[str, Any]:
    """Run the full +/-10% perturbation grid.

    Parameters
    ----------
    trades : list[SimTrade]
        All trades from load_trades() — used for simulation.
    raw_trades : list[dict]
        Raw trade dicts with p_long — used for confidence filtering.
    start_capital : float
        Initial account equity.
    fast : bool
        If True, only run baseline + +/-10% extremes.

    Returns
    -------
    dict with baseline, perturbations, combined_scenarios, robustness_summary.
    """
    # ── Baseline ──
    logger.info("=" * 60)
    logger.info("ROBUSTNESS SURFACE — Systematic +/–10%% Perturbation Grid")
    logger.info("  Start Capital: $%.2f", start_capital)
    logger.info("  Trades: %d", len(trades))
    logger.info("=" * 60)
    logger.info("")
    logger.info("Running baseline simulation...")

    try:
        params = load_sizing_params()
    except Exception:
        logger.warning("Could not load sizing config, using hardcoded defaults")
        params = SizingParams(
            max_position_pct=PROD_MAX_POSITION_PCT,
            max_risk_per_trade_pct=PROD_RISK_PCT,
        )
    logger.info("Baseline params: risk=%.2f%%  pos=%.1f%%",
                params.max_risk_per_trade_pct, params.max_position_pct * 100)

    baseline = _run_and_measure(trades, start_capital, params, "baseline")
    logger.info("  Baseline: final=$%.2f  Sharpe=%.4f  DD=%.1f%%  CAGR=%.1f%%",
                baseline["final_capital"], baseline["sharpe_ratio"],
                baseline["max_drawdown_pct"], baseline["cagr_pct"])
    logger.info("")

    all_results: dict[str, Any] = {
        "baseline": baseline,
        "perturbations": {},
        "combined_scenarios": [],
        "robustness_summary": {},
        "metadata": {
            "start_capital": start_capital,
            "n_trades": len(trades),
            "simulation_timestamp": datetime.now().isoformat(),
            "n_parameters": len(PERTURBATIONS),
            "baseline_params": {
                "max_risk_per_trade_pct": params.max_risk_per_trade_pct,
                "max_position_pct_of_equity": params.max_position_pct,
            },
        },
    }

    METRICS = ("final_capital", "sharpe_ratio", "max_drawdown_pct", "cagr_pct", "profit_factor")

    for param_def in PERTURBATIONS:
        key = param_def["key"]
        deltas = param_def["deltas"]
        if fast:
            deltas = [d for d in deltas if abs(d) >= 0.09 or d == 0.0]

        logger.info("Parameter: %s", param_def["label"])
        param_results = []
        elasticities: dict[str, list[float]] = {m: [] for m in METRICS}

        for delta in deltas:
            logger.info("  Running delta=%+.2f...", delta)

            # Apply perturbation
            if key == "confidence_threshold":
                buy_th = max(0.20, min(0.80, PROD_BUY_THRESHOLD * (1.0 + delta)))
                sell_th = max(0.20, min(0.80, PROD_SELL_THRESHOLD * (1.0 + delta)))
                filtered_raw, n_skip = filter_by_confidence(raw_trades, buy_th, sell_th)

                # Build set of kept keys from filtered raw trades.
                kept = {(t["_asset"], _norm_ts(t.get("entry_date", "")), _norm_ts(t.get("exit_date", "")))
                        for t in filtered_raw}
                filtered_sim = [t for t in trades
                                if (t.asset,
                                    t.entry_date.isoformat() if hasattr(t.entry_date, "isoformat") else str(t.entry_date),
                                    t.exit_date.isoformat() if hasattr(t.exit_date, "isoformat") else str(t.exit_date)) in kept]

                logger.info("    Confidence filter: %d of %d trades kept (buy_th=%.2f, sell_th=%.2f)",
                            len(filtered_sim), len(trades), buy_th, sell_th)

                result = _run_and_measure(
                    filtered_sim, start_capital, params,
                    f"conf_{delta:+.2f}",
                    {"buy_threshold": round(buy_th, 3), "sell_threshold": round(sell_th, 3),
                     "n_trades_filtered": len(filtered_sim), "n_skipped": n_skip},
                )
            else:
                # Risk params: modify SizingParams
                if key in ("max_risk_per_trade_pct", "max_position_pct_of_equity"):
                    perturbed_params = _perturb_params(params, key, delta)
                    result = _run_and_measure(trades, start_capital, perturbed_params,
                                              f"{key}_{delta:+.2f}")
                # TP/SL: modify R-multiples
                elif key in ("tp_mult", "sl_mult"):
                    perturbed_trades = _perturb_trades(trades, key, delta)
                    n_adj = sum(1 for i, t in enumerate(trades)
                                if float(t.r_multiple) != float(perturbed_trades[i].r_multiple))
                    logger.debug("    Adjusted %d trades' R-multiples", n_adj)
                    result = _run_and_measure(perturbed_trades, start_capital, params,
                                              f"{key}_{delta:+.2f}")
                else:
                    raise ValueError(f"Unknown param_key: {key}")

            result["delta"] = delta
            result["param_key"] = key
            result["param_label"] = param_def["label"]

            # Elasticities
            for m in METRICS:
                el = compute_elasticity(baseline.get(m, 0.0), result.get(m, 0.0), delta)
                result[f"elasticity_{m}"] = round(el, 4)

            param_results.append(result)
            if delta != 0.0:
                for m in METRICS:
                    el = result.get(f"elasticity_{m}", 0.0)
                    if abs(el) < 100:
                        elasticities[m].append(el)

            # Summary line
            r = result
            logger.info("    -> final=%.2f  Sharpe=%.4f  DD=%.1f%%  PF=%.2f  CAGR=%.1f%%  el(final)=%+.3f",
                        r["final_capital"], r["sharpe_ratio"], r["max_drawdown_pct"],
                        r["profit_factor"], r["cagr_pct"], r.get("elasticity_final_capital", 0))

        # Average elasticity
        avg_el = {m: round(float(np.mean(vals)), 4) if vals else 0.0
                  for m, vals in elasticities.items()}
        max_abs = max(abs(v) for v in avg_el.values()) if avg_el else 0.0
        rclass = classify_robustness(max_abs)

        all_results["perturbations"][key] = {
            "label": param_def["label"],
            "results": param_results,
            "average_elasticity": avg_el,
            "max_abs_elasticity": round(max_abs, 4),
            "robustness_class": rclass,
        }
        logger.info("  -> Avg elasticities: final=%.3f  sharpe=%.3f  CAGR=%.3f  DD=%.3f  class=%s",
                    avg_el.get("final_capital", 0), avg_el.get("sharpe_ratio", 0),
                    avg_el.get("cagr_pct", 0), avg_el.get("max_drawdown_pct", 0), rclass)
        logger.info("")

    # Combined scenarios
    logger.info("Running combined scenarios...")
    for scenario in COMBINED_SCENARIOS:
        logger.info("  %s...", scenario["label"])
        import copy

        p = copy.deepcopy(params)
        perturbed_trades = list(trades)

        for pk, delta in scenario["perturbations"].items():
            if pk == "confidence_threshold":
                buy_th = max(0.20, min(0.80, PROD_BUY_THRESHOLD * (1.0 + delta)))
                sell_th = max(0.20, min(0.80, PROD_SELL_THRESHOLD * (1.0 + delta)))
                filtered_raw, n_skip = filter_by_confidence(raw_trades, buy_th, sell_th)
                kept = {(t["_asset"], _norm_ts(t.get("entry_date", "")), _norm_ts(t.get("exit_date", "")))
                        for t in filtered_raw}
                perturbed_trades = [
                    t for t in trades
                    if (t.asset,
                        t.entry_date.isoformat() if hasattr(t.entry_date, "isoformat") else str(t.entry_date),
                        t.exit_date.isoformat() if hasattr(t.exit_date, "isoformat") else str(t.exit_date)) in kept
                ]
                logger.info("    Confidence filter: %d/%d trades kept", len(perturbed_trades), len(trades))
            elif pk == "max_risk_per_trade_pct":
                p = _perturb_params(p, pk, delta)
            elif pk == "max_position_pct_of_equity":
                p = _perturb_params(p, pk, delta)
            elif pk in ("tp_mult", "sl_mult"):
                perturbed_trades = _perturb_trades(perturbed_trades, pk, delta)

        result = _run_and_measure(perturbed_trades, start_capital, p, scenario["name"],
                                  {"scenario_label": scenario["label"]})
        result["scenario_name"] = scenario["name"]
        result["scenario_label"] = scenario["label"]
        all_results["combined_scenarios"].append(result)

        delta_final = result["final_capital"] - baseline["final_capital"]
        logger.info("    -> final=$%.2f  Sharpe=%.4f  DD=%.1f%%  CAGR=%.1f%%  delta=$%+.2f",
                    result["final_capital"], result["sharpe_ratio"], result["max_drawdown_pct"],
                    result["cagr_pct"], delta_final)

    # Robustness summary
    summary = {}
    for key, data in all_results["perturbations"].items():
        avg_els = data["average_elasticity"]
        max_abs = max(abs(v) for v in avg_els.values()) if avg_els else 0.0
        summary[key] = {
            "label": data["label"],
            "average_elasticity": data["average_elasticity"],
            "max_abs_elasticity": data["max_abs_elasticity"],
            "robustness_class": data["robustness_class"],
            "overall_elasticity": round(max_abs, 4),
            "overall_classification": classify_robustness(max_abs),
        }
    all_results["robustness_summary"] = summary

    # Surface classification
    classes = [s["overall_classification"] for s in summary.values()]
    fragile = [k for k, s in summary.items()
               if s["overall_classification"] in ("FRAGILE", "SENSITIVE")]
    if not fragile:
        all_results["surface_classification"] = "BROAD_PLATEAU"
        all_results["surface_verdict"] = ("All parameters robust. Performance sits on a broad plateau. "
                                          "Minor parameter drift will not materially affect results.")
    elif len(fragile) <= 2:
        all_results["surface_classification"] = "MIXED"
        all_results["surface_verdict"] = (
            f"Mixed robustness. {len(fragile)} parameter(s) show elevated sensitivity: "
            f"{', '.join(fragile)}. Acceptable for production with these parameters monitored.")
    else:
        all_results["surface_classification"] = "FRAGILE_OPTIMUM"
        all_results["surface_verdict"] = (
            f"Fragile optimum. {len(fragile)} parameters show high sensitivity: "
            f"{', '.join(fragile)}. Small changes cause disproportionate effects.")

    return all_results


# ── Chart ─────────────────────────────────────────────────────────────────────


def generate_chart(results: dict[str, Any], output_path: Path) -> None:
    if not HAS_MPL:
        logger.warning("matplotlib not available, skipping chart")
        return

    perturbations = results["perturbations"]
    baseline = results["baseline"]
    metric_keys = ["sharpe_ratio", "cagr_pct", "max_drawdown_pct", "profit_factor", "final_capital"]
    metric_labels = ["Sharpe", "CAGR %", "Max DD %", "Profit Factor", "Final Capital"]
    param_keys = list(perturbations.keys())
    param_labels = [perturbations[k]["label"] for k in param_keys]
    n_params = len(param_keys)
    n_deltas = 5

    fig, axes = plt.subplots(len(metric_keys), 1, figsize=(12, 3 * len(metric_keys)), sharex=True)
    if len(metric_keys) == 1:
        axes = [axes]

    for idx, (m_key, m_label) in enumerate(zip(metric_keys, metric_labels)):
        ax = axes[idx]
        bv = baseline.get(m_key, 0.0)
        data_matrix = np.zeros((n_params, n_deltas))
        for pi, pk in enumerate(param_keys):
            for di, res in enumerate(perturbations[pk]["results"]):
                val = res.get(m_key, 0.0)
                dev = val - bv
                if m_key in ("cagr_pct", "final_capital", "max_drawdown_pct") and abs(bv) > 1e-6:
                    dev = (val - bv) / abs(bv) * 100
                data_matrix[pi, di] = dev

        im = ax.imshow(data_matrix, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)
        ax.set_yticks(range(n_params))
        ax.set_yticklabels(param_labels, fontsize=9)
        ax.set_xticks(range(n_deltas))
        ax.set_xticklabels(["-10%", "-5%", "0%", "+5%", "+10%"], fontsize=8)
        ax.set_title(m_label, fontsize=10, fontweight="bold")
        for pi in range(n_params):
            for di in range(n_deltas):
                val = data_matrix[pi, di]
                if abs(val) < 0.5 and m_key == "sharpe_ratio":
                    continue
                color = "black" if abs(val) < 8 else "white"
                ax.text(di, pi, f"{val:.1f}", ha="center", va="center",
                        fontsize=7, color=color)
        plt.colorbar(im, ax=ax, fraction=0.02, pad=0.04)

    ax.set_xlabel("Parameter Change (+/-%)", fontsize=9)
    fig.suptitle("Robustness Surface — +/-10% Perturbation Grid",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("Chart saved to %s", output_path)


# ── Report ────────────────────────────────────────────────────────────────────


def generate_report(results: dict[str, Any], output_path: Path) -> str:
    baseline = results["baseline"]
    summary = results["robustness_summary"]

    lines = [
        "# EigenCapital — Robustness Surface Analysis Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Start Capital:** ${results['metadata']['start_capital']:,.2f}",
        f"**Total Trades:** {results['metadata']['n_trades']:,.0f}",
        f"**Parameters Tested:** {results['metadata']['n_parameters']}\n",
        "---\n",
        "## Executive Summary\n",
        f"**Surface Classification:** {results['surface_classification']}\n",
        f"{results['surface_verdict']}\n",
        "### Baseline Performance\n",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Final Capital** | ${baseline['final_capital']:,.2f} |",
        f"| **Net Profit** | ${baseline['net_profit']:+,.2f} |",
        f"| **Total Return** | {baseline['total_return_pct']:+.2f}% |",
        f"| **CAGR** | {baseline['cagr_pct']:+.2f}% |",
        f"| **Sharpe** | {baseline['sharpe_ratio']:.4f} |",
        f"| **Sortino** | {baseline['sortino_ratio']:.4f} |",
        f"| **Max DD** | {baseline['max_drawdown_pct']:.2f}% |",
        f"| **Profit Factor** | {baseline['profit_factor']:.2f} |",
        f"| **Day Win Rate** | {baseline['day_win_rate_pct']:.1f}% |\n",
        "---\n",
        "## Per-Parameter Robustness\n",
        "",
        "| Parameter | Classification | |el| final | |el| Sharpe | |el| CAGR | |el| DD |",
        "|-----------|---------------|----------|-----------|---------|--------|",
    ]

    order = ["confidence_threshold", "max_risk_per_trade_pct", "tp_mult", "sl_mult", "max_position_pct_of_equity"]
    for pk in order:
        if pk not in summary:
            continue
        s = summary[pk]
        el = s["average_elasticity"]
        lines.append(
            f"| {s['label']} | {s['overall_classification']} "
            f"| {abs(el.get('final_capital', 0)):.4f} "
            f"| {abs(el.get('sharpe_ratio', 0)):.4f} "
            f"| {abs(el.get('cagr_pct', 0)):.4f} "
            f"| {abs(el.get('max_drawdown_pct', 0)):.4f} |"
        )

    lines += [
        "",
        "**Interpretation:**",
        "- **VERY_ROBUST** (|el| < 0.3): Changes are heavily dampened",
        "- **ROBUST** (|el| < 0.7): Moderate dampening — minor impact from +/-10% changes",
        "- **MODERATE** (|el| < 1.0): Impact roughly proportional",
        "- **SENSITIVE** (|el| < 2.0): Changes amplified 1.2x–2.0x",
        "- **FRAGILE** (|el| >= 2.0): Changes amplified 2x+ — parameter drift degrades performance\n",
        "---\n",
        "## Detailed Results by Parameter\n",
    ]

    for pk in order:
        if pk not in results["perturbations"]:
            continue
        data = results["perturbations"][pk]
        lines.append(f"### {data['label']}\n")
        lines.append("| Delta% | Final Capital | Sharpe | CAGR | Max DD | PF | Elasticity (final) |")
        lines.append("|--------|-------------|--------|------|--------|----|--------------------|")
        for res in data["results"]:
            d_pct = f"{res['delta'] * 100:+.0f}%"
            lines.append(
                f"| {d_pct} | ${res['final_capital']:>8,.2f} "
                f"| {res['sharpe_ratio']:.4f} "
                f"| {res['cagr_pct']:.2f}% "
                f"| {res['max_drawdown_pct']:.1f}% "
                f"| {res['profit_factor']:.2f} "
                f"| {res.get('elasticity_final_capital', 0):+.4f} |"
            )
        lines.append("")
        lines.append(f"**Robustness:** {data['robustness_class']} (max |el| = {data['max_abs_elasticity']:.4f})\n")

    lines += [
        "---\n",
        "## Combined Scenarios\n",
        "",
        "| Scenario | Final Capital | Sharpe | CAGR | Max DD | PF | Delta from Baseline |",
        "|----------|-------------|--------|------|--------|----|---------------------|",
    ]
    for sc in results["combined_scenarios"]:
        d = sc["final_capital"] - baseline["final_capital"]
        lines.append(
            f"| {sc.get('scenario_label', sc['scenario_name'])} "
            f"| ${sc['final_capital']:>8,.2f} "
            f"| {sc['sharpe_ratio']:.4f} "
            f"| {sc['cagr_pct']:.2f}% "
            f"| {sc['max_drawdown_pct']:.1f}% "
            f"| {sc['profit_factor']:.2f} "
            f"| ${d:+,.2f} |"
        )

    lines += [
        "",
        "---\n",
        "## Production Confidence Assessment\n",
        "",
    ]

    fragile_count = sum(1 for s in summary.values()
                        if s["overall_classification"] in ("FRAGILE", "SENSITIVE"))
    if fragile_count == 0:
        lines.append("**HIGH CONFIDENCE:** No fragile parameters detected. "
                     "The system is safe from small parameter drifts.\n")
    elif fragile_count <= 2:
        lines.append("**MODERATE CONFIDENCE:** Some sensitive parameters detected. "
                     "Monitor them in production but overall risk is manageable.\n")
    else:
        lines.append("**LOWER CONFIDENCE:** Multiple sensitive parameters. "
                     "Production risk controls should cover these specifically.\n")

    if "confidence_threshold" in summary and summary["confidence_threshold"]["overall_classification"] in ("SENSITIVE", "FRAGILE"):
        lines.append("> **Confidence threshold is sensitive.** Lock thresholds in config and only change with retraining.\n")
    if "tp_mult" in summary and summary["tp_mult"]["overall_classification"] in ("SENSITIVE", "FRAGILE"):
        lines.append("> **TP multiplier sensitivity** mitigated by adaptive exit engine. Monitor.\n")

    lines += [
        f"**Report saved to:** {output_path}",
        f"**Data saved to:** {OUTPUT_JSON}",
    ]

    report_text = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text)
    logger.info("Report saved to %s", output_path)
    return report_text


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Robustness Surface — Systematic +/-10% Perturbation Grid"
    )
    parser.add_argument("--start-capital", type=float, default=500.0,
                        help="Initial capital (default: 500)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--fast", action="store_true",
                        help="Only run baseline +/- 10pct extremes (skip +/- 5pct)")
    parser.add_argument("--no-chart", action="store_true",
                        help="Skip chart generation")
    parser.add_argument("--trade-path", type=str, default=None,
                        help="Path to trade lifecycle JSON")
    args = parser.parse_args()

    trade_path = Path(args.trade_path) if args.trade_path else TRADE_PATH
    logger.info("Loading trades from %s...", trade_path)

    # Load raw dicts first (needed for confidence filtering)
    raw_trades = load_raw_trade_dicts(trade_path)
    # Load SimTrade list (needed for simulation)
    trades = load_trades(trade_path=trade_path)
    logger.info("Loaded %d SimTrades, %d raw trade dicts", len(trades), len(raw_trades))

    results = run_perturbation_grid(trades, raw_trades, args.start_capital, fast=args.fast)

    if not args.no_chart and HAS_MPL:
        generate_chart(results, CHART_PATH)
        results["chart_path"] = str(CHART_PATH)

    output_path = Path(args.output) if args.output else OUTPUT_JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results saved to %s", output_path)

    generate_report(results, REPORT_PATH)

    baseline = results["baseline"]
    print("")
    print("=" * 60)
    print("  ROBUSTNESS SURFACE — EXECUTIVE SUMMARY")
    print(f"  Classification: {results['surface_classification']}")
    print("=" * 60)
    print(f"  Baseline:  Final=${baseline['final_capital']:>8,.2f}  "
          f"Sharpe={baseline['sharpe_ratio']:.4f}  "
          f"CAGR={baseline['cagr_pct']:.1f}%  "
          f"DD={baseline['max_drawdown_pct']:.1f}%")
    print()
    print(f"  {'Parameter':<35} {'Class':<15} {'|el| final':<12} {'|el| sharpe':<12}")
    print(f"  {'-'*35} {'-'*15} {'-'*12} {'-'*12}")
    for pk, s in results["robustness_summary"].items():
        el = s["average_elasticity"]
        print(f"  {s['label']:<35} {s['overall_classification']:<15} "
              f"{abs(el.get('final_capital', 0)):<12.4f} "
              f"{abs(el.get('sharpe_ratio', 0)):<12.4f}")
    print()
    print("  COMBINED SCENARIOS:")
    for sc in results["combined_scenarios"]:
        d = sc["final_capital"] - baseline["final_capital"]
        print(f"    {sc.get('scenario_label', sc['scenario_name']):<45} "
              f"final=${sc['final_capital']:>8,.2f}  "
              f"delta=${d:+,.2f}")
    print()
    print(f"  Report: {REPORT_PATH}")
    print(f"  JSON:   {output_path}")
    print(f"  Chart:  {CHART_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
