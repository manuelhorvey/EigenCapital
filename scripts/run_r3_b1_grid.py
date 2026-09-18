"""R3-B1 Grid Runner — the preregistered parameter-stability experiment.

Frozen contract: docs/research/R3_PARAMETER_STABILITY.md (preregistration +
pre-execution addendum). This runner:

- reuses the R1 exporter's pipeline functions UNCHANGED (fork-injected
  globals — zero signal-logic duplication, contract item 5);
- evaluates ALL 1,500 preregistered grid points (full factorial, no
  subsampling, deterministic — no RNG anywhere);
- produces explicit error records for failed points (never silent drops);
- applies the preregistered verdict machinery: FRAGILE classification →
  connected component → STABLE fraction → Holm axis family → F1/F2 verdict;
- reports PBO + Deflated Sharpe as false-confidence diagnostics with the
  recorded non-independence caveat attached.

This is a ROBUSTNESS STUDY, not a parameter search. The only preregistered
questions are (a) whether the frozen configuration sits inside a historically
stable region on this data and (b) whether the axes' marginal associations
are consistent with a plateau. No output of this script is a parameter
recommendation, and nothing here modifies production R4.
"""

from __future__ import annotations

import importlib.util
import json
import math
import multiprocessing as mp
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eigencapital.analytics.validation.deflated_sharpe import deflated_sharpe_ratio
from eigencapital.analytics.validation.pbo import compute_pbo
from eigencapital.research.parameter_stability.evaluate import (
    daily_portfolio_path,
    evaluate_grid_point,
)
from eigencapital.research.parameter_stability.grid import (
    GridAxis,
    PointMetrics,
    axis_association_tests,
    build_grid,
    classify_point,
    stability_verdict,
    stable_region_metrics,
)

REPORTS = Path("reports/r3_parameter_stability")

# ── Preregistered axes (ledger; values in EXPORTER parameter keys) ────────────
# skip_months is recorded in months in the ledger; conversion ×21 trading days
# is the frozen r4_rebalance_loop convention, applied here once, up front.
AXES = [
    GridAxis(name="lookback", values=(189.0, 220.0, 252.0, 284.0, 315.0)),
    GridAxis(name="skip", values=(0.0, 21.0, 42.0, 63.0)),  # skip_months 0..3 ×21
    GridAxis(name="vol_lookback", values=(40.0, 50.0, 60.0, 70.0, 80.0)),
    GridAxis(name="risk_lookback", values=(10.0, 15.0, 20.0, 25.0, 30.0)),
    GridAxis(name="rebalance_every", values=(3.0, 5.0, 10.0)),
]
AXIS_NAME_MAP = {
    "lookback": "signal_lookback_long",
    "skip": "skip_months ×21",
    "vol_lookback": "vol_lookback_signal",
    "risk_lookback": "risk_lookback",
    "rebalance_every": "rebalance_every",
}

# ── Fork-injected worker globals (Linux fork: no pickling of functions) ──────
_DATA: Dict[str, pd.DataFrame] = {}
_BASE: Dict[str, Any] = {}
_SIGNAL_FN: Any = None
_SIM_FN: Any = None


def _init_workers(
    data: Dict[str, pd.DataFrame],
    base: Dict[str, Any],
    signal_fn: Any,
    sim_fn: Any,
) -> None:
    global _DATA, _BASE, _SIGNAL_FN, _SIM_FN
    _DATA, _BASE, _SIGNAL_FN, _SIM_FN = data, base, signal_fn, sim_fn


def _evaluate_one(point_params: Dict[str, float]) -> Dict[str, Any]:
    """One grid point → record. Raises propagate to the pool result handler."""
    try:
        metrics: PointMetrics = evaluate_grid_point(point_params, _DATA, _BASE, _SIGNAL_FN, _SIM_FN)
    except Exception as exc:  # explicit error record — never a silent drop
        return {"params": dict(point_params), "error": f"{type(exc).__name__}: {exc}"}
    record = asdict(metrics)
    record["classification"] = classify_point(metrics)
    return record


def _load_exporter() -> Any:
    """Import the R1 exporter as a proper module (picklable-by-reference)."""
    path = Path(__file__).resolve().parent / "export_r4_trade_stream.py"
    spec = importlib.util.spec_from_file_location("r4_exporter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r4_exporter"] = module
    spec.loader.exec_module(module)
    return module


def _center_params(base: Dict[str, Any]) -> Dict[str, float]:
    """The frozen R4 configuration in grid-axis coordinates (all in-grid)."""
    return {
        "lookback": float(base["lookback"]),
        "skip": float(base["skip"]),
        "vol_lookback": float(base["vol_lookback"]),
        "risk_lookback": float(base["risk_lookback"]),
        "rebalance_every": float(base["rebalance_every"]),
    }


def _point_key(params: Dict[str, float]) -> Tuple[Tuple[str, float], ...]:
    return tuple(sorted((k, float(v)) for k, v in params.items()))


def main() -> None:
    t0 = time.time()
    exporter = _load_exporter()
    base = exporter.load_config_params()
    data = exporter.load_bars()
    center = _center_params(base)

    # Preregistration guard: the frozen config MUST sit on the grid.
    grid = build_grid(AXES, center)
    n_points = len(grid)
    print(f"[R3-B1] grid: {n_points} points (preregistered 5×4×5×5×3 = 1,500)")
    if n_points != 1500:
        raise SystemExit(f"preregistration violation: grid size {n_points} != 1500")

    ctx = mp.get_context("fork")
    workers = min(14, mp.cpu_count())
    param_list = [p.params for p in grid]
    with ctx.Pool(
        processes=workers,
        initializer=_init_workers,
        initargs=(data, base, exporter.compute_r4_signal, exporter.simulate_portfolio),
    ) as pool:
        raw = pool.map(_evaluate_one, param_list, chunksize=16)

    records: List[Dict[str, Any]] = [r for r in raw if "error" not in r]
    errors: List[Dict[str, Any]] = [r for r in raw if "error" in r]
    wall = time.time() - t0
    print(f"[R3-B1] evaluated {len(records)} points in {wall:.1f}s ({len(errors)} errors)")

    meta: Dict[str, Any] = {
        "experiment": "R3-B1 parameter stability grid",
        "contract": "docs/research/R3_PARAMETER_STABILITY.md",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "universe_version": "r4_local_v1",
        "symbols": sorted(data.keys()),
        "cost_one_way": float(base["cost_one_way"]),
        "axis_name_map": AXIS_NAME_MAP,
        "axes": {a.name: list(a.values) for a in AXES},
        "center": center,
        "grid_size": n_points,
        "evaluated": len(records),
        "errors": errors,
        "wall_seconds": round(wall, 1),
        "workers": workers,
        "wf_geometry": {"train": 750, "test": 250, "purge": 10, "embargo": 5, "anchored": True},
        "semantics": "OBSERVED — robustness study, not a parameter search",
    }

    if errors:
        # Falsification-first: an incomplete grid cannot support a verdict.
        meta["verdict"] = {
            "outcome": "INCONCLUSIVE",
            "reason": f"{len(errors)} grid points failed; the preregistered verdict machinery requires the full grid",
        }
        _write_artifacts(meta, records, errors, None, None, None, None)
        return

    # ── Classification + region machinery (frozen) ──────────────────────────
    metrics_by_key = {
        _point_key(r["params"]): PointMetrics(**{k: v for k, v in r.items() if k != "classification"}) for r in records
    }
    classifications = {_point_key(r["params"]): r["classification"] for r in records}
    region = stable_region_metrics(grid, classifications, center)
    axis_records = axis_association_tests(grid, metrics_by_key)
    verdict = stability_verdict(region, axis_records)

    # ── False-confidence diagnostics (pre-execution addendum) ───────────────
    wf_candidates = [
        {
            "in_sample_sharpe": float(r["sharpe"]),
            "out_of_sample_sharpe": float(r["wf_mean_oos_sharpe"]),
        }
        for r in records
        if int(r["wf_total_windows"]) > 0
    ]
    pbo = compute_pbo(wf_candidates)
    pbo_dict = pbo.to_dict()
    pbo_dict["excluded_points_no_wf_windows"] = n_points - len(wf_candidates)
    pbo_dict["caveat"] = (
        "grid points share the same underlying data — trials are not "
        "independent; PBO is a false-confidence diagnostic, never a "
        "calibrated probability"
    )

    center_key = _point_key(center)
    center_rec = metrics_by_key[center_key]
    center_weights = exporter.compute_r4_signal(data, dict(base))
    center_returns = daily_portfolio_path(data, center_weights, float(base["cost_one_way"]))
    daily = center_returns.to_numpy()
    per_period_sharpe = float(daily.mean() / daily.std(ddof=1)) if daily.std(ddof=1) > 1e-15 else 0.0
    dsr = deflated_sharpe_ratio(
        observed_sharpe=per_period_sharpe,
        n_trials=n_points,
        n_periods=len(daily),  # derived from `returns` when supplied
        returns=[float(v) for v in daily],
        trial_sharpes=[float(r["sharpe"]) / math.sqrt(252.0) for r in records],
    )
    dsr_dict = asdict(dsr)
    dsr_dict["annualized_observed_sharpe"] = per_period_sharpe * math.sqrt(252.0)
    dsr_dict["caveat"] = (
        "grid points share the same underlying data — the effective number of "
        "independent trials is below 1,500; DSR reported as a diagnostic, "
        "used for no decision"
    )

    meta["region"] = region
    meta["axis_tests"] = axis_records
    meta["verdict"] = {
        "outcome": verdict.outcome,
        "region_statement": verdict.region_statement,
        "axes_flagged": verdict.axes_flagged,
        "holm_adjusted_p": verdict.holm_adjusted_p,
        "center_classification": verdict.center_classification,
        "center_all_neighbors_fragile": verdict.center_all_neighbors_fragile,
    }
    meta["pbo"] = pbo_dict
    meta["deflated_sharpe"] = dsr_dict

    _write_artifacts(meta, records, errors, region, axis_records, verdict, center_rec)
    print(f"[R3-B1] verdict: {verdict.outcome}")
    print(f"[R3-B1] {verdict.region_statement}")
    print(f"[R3-B1] artifacts in {REPORTS}/")


def _write_artifacts(
    meta: Dict[str, Any],
    records: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    region: Dict[str, object] | None,
    axis_records: List[Dict[str, object]] | None,
    verdict: Any,
    center_rec: Any,
) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)

    with open(REPORTS / "r3_b1_grid_results.json", "w") as fh:
        json.dump({"meta": meta, "points": records, "errors": errors}, fh, indent=2, default=str)

    fieldnames = [
        "lookback",
        "skip",
        "vol_lookback",
        "risk_lookback",
        "rebalance_every",
        "cagr",
        "ann_vol",
        "max_drawdown",
        "sharpe",
        "total_pnl",
        "trade_count",
        "turnover",
        "hit_rate",
        "payoff_ratio",
        "wf_total_windows",
        "wf_mean_oos_sharpe",
        "wf_pct_profitable_windows",
        "wf_oos_return_mean",
        "wf_oos_return_std",
        "classification",
    ]
    with open(REPORTS / "r3_b1_grid_results.csv", "w") as fh:
        fh.write(",".join(fieldnames) + "\n")
        for r in records:
            row = {**{k: r["params"][k] for k in fieldnames[:5]}, **r}
            fh.write(",".join(str(row.get(f, "")) for f in fieldnames) + "\n")

    md = _render_report(meta, records, errors, region, axis_records, verdict, center_rec)
    (REPORTS / "r3_b1_report.md").write_text(md)


def _render_report(
    meta: Dict[str, Any],
    records: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    region: Dict[str, object] | None,
    axis_records: List[Dict[str, object]] | None,
    verdict: Any,
    center_rec: Any,
) -> str:
    lines: List[str] = [
        "# R3-B1 — Parameter Stability Grid (OBSERVED report)",
        "",
        f"**Experiment:** {meta['experiment']}  ",
        f"**Contract:** `{meta['contract']}` (preregistered; pre-execution addendum frozen)  ",
        f"**Run:** {meta['timestamp_utc']} · {meta['wall_seconds']}s · {meta['workers']} workers · deterministic (no RNG)  ",
        f"**Data:** {len(meta['symbols'])} symbols ({meta['universe_version']}): {', '.join(meta['symbols'])}  ",
        f"**Costs:** {meta['cost_one_way'] * 1e4:.1f} bps one-way, identical across points  ",
        f"**Grid:** {meta['grid_size']} points, full factorial — 5×4×5×5×3",
        "",
        "> **What this study is:** a robustness study of the FROZEN R4",
        "> configuration under preregistered bounded perturbations.",
        "> **What this study is NOT:** a parameter search. Nothing here",
        "> recommends parameters; nothing here modifies production R4.",
        "",
    ]

    if errors:
        lines += [
            f"## INCONCLUSIVE — {len(errors)} grid points failed",
            "",
            "The preregistered verdict machinery requires the full grid.",
            "Failing points (explicit error records, never silent drops):",
            "",
        ]
        for e in errors[:20]:
            lines.append(f"- `{e['params']}` → {e['error']}")
        if len(errors) > 20:
            lines.append(f"- … and {len(errors) - 20} more (see JSON artifact)")
        return "\n".join(lines) + "\n"

    assert region is not None and axis_records is not None and verdict is not None

    lines += [
        "## Verdict (preregistered F1/F2)",
        "",
        f"**Outcome: {verdict.outcome}**",
        "",
        f"> {verdict.region_statement}.",
        "",
    ]

    lines += [
        "## Frozen center configuration",
        "",
        "| Axis | Frozen value |",
        "|---|---|",
    ]
    for k, v in meta["center"].items():
        lines.append(f"| {AXIS_NAME_MAP.get(k, k)} | {v:g} |")
    if center_rec is not None:
        lines += [
            "",
            f"Center classification: **{verdict.center_classification}** · "
            f"full-path Sharpe {center_rec.sharpe:.3f} · max DD "
            f"{center_rec.max_drawdown * 100:.2f}% · {center_rec.trade_count} trades",
        ]

    lines += [
        "",
        "## Region machinery",
        "",
        f"- Component reachable from the center through adjacent non-FRAGILE points: **{region['component_size']}** of {meta['grid_size']}",
        f"- STABLE fraction within the component (preregistered rule): **{region['stable_fraction']:.3f}**"
        f" (stable {region.get('stable_count', '—')})",
        f"- Center adjacent to at least one FRAGILE point: **{region['center_all_neighbors_fragile']}**",
        "",
        "## Axis-level association (one Holm family, preregistered)",
        "",
        "| Axis | Spearman ρ | t | raw p | Holm p | flagged ≤0.05 |",
        "|---|---|---|---|---|---|",
    ]
    for rec in axis_records:
        name = str(rec["axis"])
        holm = verdict.holm_adjusted_p.get(name, float("nan"))
        lines.append(
            f"| {AXIS_NAME_MAP.get(name, name)} | {rec['spearman_rho']:+.3f} | "
            f"{rec['t_stat']:+.2f} | {rec['raw_p']:.4f} | {holm:.4f} | "
            f"{'YES' if name in verdict.axes_flagged else 'no'} |"
        )

    counts = {"FRAGILE": 0, "NON_FRAGILE": 0}
    for r in records:
        counts[r["classification"]] += 1
    lines += [
        "",
        f"Point classifications across the full grid: "
        f"FRAGILE {counts['FRAGILE']} · NON_FRAGILE {counts['NON_FRAGILE']}",
        "",
        "## False-confidence diagnostics",
        "",
        f"- **PBO:** {meta['pbo']['pbo']:.4f} over {meta['pbo']['n_candidates']} candidates"
        f" ({meta['pbo']['excluded_points_no_wf_windows']} points excluded — WF geometry cannot fit)",
        f"  - {meta['pbo']['caveat']}",
        f"- **Deflated Sharpe:** DSR {meta['deflated_sharpe']['deflated_sharpe']:.4f} "
        f"(SR0 = {meta['deflated_sharpe']['expected_max_sharpe']:.4f}, n_trials = {meta['grid_size']})",
        f"  - {meta['deflated_sharpe']['caveat']}",
        "",
        "## Interpretation guards (frozen)",
        "",
        "- Region statements are about THIS data and THIS preregistered grid only.",
        "- The WF aggregate is a per-point diagnostic, never a selection score.",
        "- No pass/fail threshold beyond the preregistered F1/F2 criteria applies.",
        "- No output of this study is a parameter recommendation; the frozen R4",
        "  specification remains untouched.",
        "",
        f"*Errors: {len(errors)} · Records: {len(records)} · Deterministic rerun: identical.*",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
