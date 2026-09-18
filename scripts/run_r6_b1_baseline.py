"""R6-B1 Runner — preregistered vol-cap filter on the R5 event population.

Frozen contract: docs/research/R6_META_LABELING.md (R6-A contract + B1
preregistration §5, frozen BEFORE any conditional label rate was computed).

Pre-execution checks (run and reported BEFORE the B1 statistic):
  1. feature availability: every decision-time feature is read at or before
     the event's decision bar and is finite;
  2. weights identity: independently re-derived final weights equal the
     replica's weights EXACTLY for every event (proves the feature
     re-derivation is the frozen pipeline, not a fork);
  3. event↔round-trip correspondence: per symbol, entry fills map 1:1 in
     order onto the replica's round-trips (population = 1,311 = R5/R1);
  4. WF fit: event count vs frozen R3 geometry (train 504 + purge 21 +
     test 5).

Then the ONE preregistered evaluation: take iff vol_scale < 1.0; favorable
rate(taken) − rate(skipped) with the preregistered block-bootstrap CI
(block 20, seed 42). Filter-quality result only — not a strategy verdict,
not a forecast (contract items 6/8).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eigencapital.research.labeling import build_labels
from eigencapital.research.meta_labeling import evaluate_b1, summarize
from eigencapital.research.parameter_stability.grid import (
    WF_EMBARGO_BARS,
    WF_PURGE_BARS,
    WF_TEST_BARS,
    WF_TRAIN_BARS,
)

REPORTS = Path("reports/r6_meta_labeling")
VOL_SCALE_REFERENCE = 0.50
WEIGHT_CLIP = 0.20


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    timestamp = datetime.now(UTC).isoformat()
    exporter = _load_module("r4_exporter", Path(__file__).resolve().parent / "export_r4_trade_stream.py")
    r5_runner = _load_module("r5_runner", Path(__file__).resolve().parent / "run_r5_b1_labels.py")

    params = exporter.load_config_params()
    data = exporter.load_bars()
    weights = exporter.compute_r4_signal(data, dict(params))
    fills_by_symbol, trades_by_symbol = exporter.simulate_portfolio(data, weights, params)

    # ── Events (R5 extraction, reused unchanged) ────────────────────────────
    index_by_symbol = {sym: df.index for sym, df in data.items()}
    events = r5_runner.extract_entry_events(fills_by_symbol, index_by_symbol)

    # ── Feature re-derivation (observability copy of the replica internals) ─
    returns_df = (
        pd.DataFrame({sym: df["close"].pct_change() for sym, df in data.items()}).dropna(how="all").ffill().fillna(0)
    )
    mom_12m = (1 + returns_df).rolling(params["lookback"]).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(params["skip"]).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom_12m - mom_1m).dropna(how="all")
    rk = sig.rank(axis=1, pct=True)
    w_centered = rk - 0.5
    avg_vol = returns_df.rolling(params["risk_lookback"]).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)
    vol60 = returns_df.rolling(params["vol_lookback"]).std() * np.sqrt(252)
    vol_scale = np.minimum(vol60 / VOL_SCALE_REFERENCE, 1.0)
    w_final = (w_centered.multiply(regime, axis=0) * vol_scale).clip(-WEIGHT_CLIP, WEIGHT_CLIP)

    # ── Per-event decision-time features (contract item 2) ──────────────────
    checks: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    weight_identity_fail = 0
    availability_fail = 0
    for ev in events:
        dt = ev.decision_timestamp
        try:
            w_exp = float(w_final.at[dt, ev.instrument])
            vs = float(vol_scale.at[dt, ev.instrument])
            sg = float(sig.at[dt, ev.instrument])
            rkk = float(rk.at[dt, ev.instrument])
            reg = float(regime.at[dt])
            v60 = float(vol60.at[dt, ev.instrument])
            av = float(avg_vol.at[dt])
        except KeyError:
            availability_fail += 1
            continue
        vals = [w_exp, vs, sg, rkk, reg, v60, av]
        if not all(np.isfinite(x) for x in vals):
            availability_fail += 1
            continue
        w_rep = float(weights.at[dt, ev.instrument])
        if w_exp != w_rep:  # exact identity required (same arithmetic path)
            weight_identity_fail += 1
        rows.append(
            {
                "event_id": ev.event_id,
                "instrument": ev.instrument,
                "side": ev.side,
                "decision_ts": dt,
                "event_ts": ev.event_timestamp,
                "w_final": w_exp,
                "abs_w_final": abs(w_exp),
                "vol_scale": vs,
                "sig": sg,
                "rk": rkk,
                "regime": reg,
                "vol60": v60,
                "avg_vol": av,
                "taken": vs < 1.0,
            }
        )

    # ── Labels (R5 frozen spec, deterministic re-run) ────────────────────────
    run = build_labels(events, {sym: df for sym, df in data.items()})
    label_of = {le.event.event_id: le.label for le in run.labels if not le.excluded_reason}

    # ── Event↔round-trip correspondence (order, per symbol) ──────────────────
    n_round_trips = sum(len(v) for v in trades_by_symbol.values())
    n_entry_fills = sum(sum(1 for i in range(0, len(f) - 1, 2)) for f in fills_by_symbol.values())
    correspondence_ok = n_round_trips == n_entry_fills == len(events)

    # ── B1 evaluation over the date-ordered event sequence ──────────────────
    rows.sort(key=lambda r: (r["event_ts"], r["event_id"]))
    vol_scales = [r["vol_scale"] for r in rows if r["event_id"] in label_of]
    labels_seq = [label_of[r["event_id"]] for r in rows if r["event_id"] in label_of]
    dates_seq = [r["event_ts"] for r in rows if r["event_id"] in label_of]

    n_events = len(dates_seq)
    geometry = WF_TRAIN_BARS + WF_PURGE_BARS + WF_TEST_BARS
    result = evaluate_b1(
        vol_scales,
        labels_seq,
        dates_seq,
        train_bars=WF_TRAIN_BARS,
        purge_bars=WF_PURGE_BARS,
        embargo_bars=WF_EMBARGO_BARS,
        test_bars=WF_TEST_BARS,
    )

    checks = {
        "feature_availability_failures": availability_fail,
        "weights_identity_failures": weight_identity_fail,
        "event_round_trip_correspondence": {
            "n_events": len(events),
            "n_entry_fills": n_entry_fills,
            "n_round_trips": n_round_trips,
            "ok": correspondence_ok,
        },
        "labels": {"n_labeled": n_events, "n_excluded": run.n_excluded},
        "wf_fit": {
            "n_events": n_events,
            "train_purge_test": geometry,
            "ok": n_events >= geometry,
        },
    }

    meta: Dict[str, Any] = {
        "experiment": "R6-B1 preregistered vol-cap deterministic filter (meta-labeling baseline 1)",
        "contract": "docs/research/R6_META_LABELING.md (R6-A contract + B1 preregistration §5)",
        "timestamp_utc": timestamp,
        "filter": "take iff vol_scale < 1.0 (vol60 < VOL_SCALE_REFERENCE = 0.50); skip iff vol_scale == 1.0",
        "pre_execution_checks": checks,
        "b1": summarize(result),
        "guards": {
            "filter_quality_only": True,
            "not_a_strategy_verdict": True,
            "not_a_forecast": True,
            "label_balance_is_not_accuracy": "the R5 681/630 split is an instrument property; never quoted as baseline accuracy",
        },
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "r6_b1_report.json", "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    (REPORTS / "r6_b1_report.md").write_text(_render(meta, result))
    print(
        f"[R6-B1] checks: availability_fail={availability_fail} identity_fail={weight_identity_fail} correspondence={correspondence_ok} wf_fit={n_events >= geometry}"
    )
    print(f"[R6-B1] taken={result.split.n_taken} skipped={result.split.n_skipped} diff={result.rate_difference}")
    print(f"[R6-B1] CI90=[{result.ci_low}, {result.ci_high}] verdict={result.verdict}")
    print(f"[R6-B1] artifacts in {REPORTS}/")


def _render(meta: Dict[str, Any], result: Any) -> str:
    b1 = meta["b1"]
    checks = meta["pre_execution_checks"]
    lines: List[str] = [
        "# R6-B1 — Preregistered Vol-Cap Filter (OBSERVED report)",
        "",
        f"**Experiment:** {meta['experiment']}  ",
        f"**Contract:** `{meta['contract']}` — preregistered before any conditional label rate  ",
        f"**Run:** {meta['timestamp_utc']} · CI via moving-block bootstrap (block 20, seed 42, n=1000)  ",
        f"**Filter:** `{meta['filter']}`",
        "",
        "> **What this is:** a filter-quality measurement of a deterministic,",
        "> parameter-free meta-labeling baseline against its preregistered",
        "> success criterion.",
        "> **What this is NOT:** a strategy verdict, a take/skip production",
        "> decision, or a forecast. The R5 681/630 label split is an instrument",
        "> property and is never quoted as baseline accuracy.",
        "",
        "## Pre-execution checks",
        "",
        f"- feature availability failures: {checks['feature_availability_failures']}",
        f"- weights-identity failures (re-derived vs replica, exact): {checks['weights_identity_failures']}",
        f"- event↔round-trip correspondence: {checks['event_round_trip_correspondence']['n_events']} events / "
        f"{checks['event_round_trip_correspondence']['n_entry_fills']} entry fills / "
        f"{checks['event_round_trip_correspondence']['n_round_trips']} round-trips → "
        f"{'OK' if checks['event_round_trip_correspondence']['ok'] else 'FAILED'}",
        f"- labels: {checks['labels']['n_labeled']} labeled, {checks['labels']['n_excluded']} excluded",
        f"- WF fit: {checks['wf_fit']['n_events']} events vs {checks['wf_fit']['train_purge_test']} geometry → "
        f"{'OK' if checks['wf_fit']['ok'] else 'FAILED'}",
        "",
        "## Result",
        "",
        f"- taken (uncapped): **{b1['n_taken']}** events, favorable rate {b1['rate_taken'] and round(b1['rate_taken'], 4)}",
        f"- skipped (vol-capped): **{b1['n_skipped']}** events, favorable rate {b1['rate_skipped'] and round(b1['rate_skipped'], 4)}",
        f"- rate difference: **{b1['rate_difference'] and round(b1['rate_difference'], 4)}**",
        f"- 90% block-bootstrap CI: [{b1['ci_90'][0] and round(b1['ci_90'][0], 4)}, {b1['ci_90'][1] and round(b1['ci_90'][1], 4)}]",
        "",
        f"## Verdict: **{b1['verdict']}**",
        "",
        f"> {b1['verdict_statement']}.",
        "",
        "## WF OOS slices (descriptive only)",
        "",
        "| window | OOS events | taken | skipped | rate diff |",
        "|---|---|---|---|---|",
    ]
    for s in result.oos_slices:
        rd = "n/a" if s.rate_diff is None else f"{s.rate_diff:+.3f}"
        lines.append(f"| {s.window} | {s.oos_end - s.oos_start} | {s.n_taken} | {s.n_skipped} | {rd} |")
    lines += [
        "",
        "## Interpretation guards (frozen)",
        "",
        "- One preregistered trial slot (R6-B1) consumed; B2 (logistic",
        "  regression) is a separate slot gated on this design, and B3+ (more",
        "  complex ML) stays banned absent demonstrated B2 incremental value.",
        "- Success here does NOT promote anything: the branch bar is",
        "  incremental OOS utility over take-every-event R4 after costs",
        "  (contract item 6, evaluated at B2).",
        "- Failure or INCONCLUSIVE feeds the branch-rejection criteria",
        "  (contract item 7) — no filter tuning, no feature additions.",
        "- Research-only: R4 production untouched.",
        "",
        f"*Artifacts: r6_b1_report.json in {REPORTS}/.*",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
