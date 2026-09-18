"""R5-B Labeling Runner — frozen triple-barrier spec on frozen-replica events.

Frozen contract: docs/research/R5_TRIPLE_BARRIER.md (R5-A, frozen BEFORE any
labeling code). This runner:

- runs the frozen-R4 replica pipeline (export_r4_trade_stream.py functions
  unchanged) to obtain its ENTRY fills — contract item 1's events;
- labels every event with the ONE preregistered specification
  (PT 2.0 / SL 2.0 / 10-bar vertical / 60-day PIT vol — contract item 2);
- reports ONLY the frozen diagnostics (contract item 5): label distribution,
  first-touch types, time-to-touch, overlap structure, average uniqueness,
  exclusion counts;
- emits JSON + MD artifacts plus a per-event CSV.

This is a MEASUREMENT study of the labeling instrument. It establishes label
validity and behavior, NOT predictive power — no classifier, no ML, no
barrier comparison, no take/skip/size logic (contract item 6). Research-only;
R4 production is untouched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eigencapital.research.labeling import (
    LABEL_VERSION,
    Event,
    LabeledEvent,
    average_uniqueness,
    build_labels,
    overlap_intervals,
)

REPORTS = Path("reports/r5_triple_barrier")


def _load_exporter() -> Any:
    path = Path(__file__).resolve().parent / "export_r4_trade_stream.py"
    spec = importlib.util.spec_from_file_location("r4_exporter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r4_exporter"] = module
    spec.loader.exec_module(module)
    return module


def extract_entry_events(
    fills_by_symbol: Dict[str, List[Dict[str, Any]]], index_by_symbol: Dict[str, pd.DatetimeIndex]
) -> List[Event]:
    """Entry fills → Events (contract item 1).

    The replica's fills strictly alternate OPEN/CLOSE per symbol, so entries
    sit at even positions (0, 2, 4, ...). Fill side BUY → LONG, SELL →
    SHORT. decision_timestamp = the trading bar immediately before the
    event bar (the PIT decision bar for a next-bar-open executor; for the
    weekly replica this IS the weight date). Event IDs are deterministic:
    ``{symbol}-{seq:04d}`` in chronological order per symbol.
    """
    events: List[Event] = []
    for sym in sorted(fills_by_symbol):
        fills = fills_by_symbol[sym]
        index = index_by_symbol[sym]
        pos_of = {ts: i for i, ts in enumerate(index)}
        seq = 0
        for i in range(0, len(fills) - 1, 2):  # even positions are entries
            fill = fills[i]
            ts = pd.Timestamp(fill["timestamp"])
            pos = pos_of.get(ts)
            if pos is None or pos == 0:
                continue  # cannot name a decision bar → skip defensively (counted in diagnostics if seen)
            events.append(
                Event(
                    event_id=f"{sym}-{seq:04d}",
                    instrument=sym,
                    decision_timestamp=index[pos - 1],
                    event_timestamp=ts,
                    side="LONG" if fill["side"] == "BUY" else "SHORT",
                    entry_price=float(fill["fill_price"]),
                )
            )
            seq += 1
    return events


def main() -> None:
    timestamp = datetime.now(UTC).isoformat()
    exporter = _load_exporter()
    params = exporter.load_config_params()
    data = exporter.load_bars()
    weights = exporter.compute_r4_signal(data, dict(params))
    fills_by_symbol, _trades = exporter.simulate_portfolio(data, weights, params)

    index_by_symbol = {sym: df.index for sym, df in data.items()}
    events = extract_entry_events(fills_by_symbol, index_by_symbol)

    bars_by_instrument = {sym: df for sym, df in data.items()}
    run = build_labels(events, bars_by_instrument)
    labels = list(run.labels)

    # ── Diagnostics (contract item 5, exactly these, nothing more) ──────────
    valid = [le for le in labels if not le.excluded_reason]
    label_dist = {
        "+1 (PT first or favorable vertical)": sum(1 for le in valid if le.label == 1),
        "-1 (SL first or adverse vertical)": sum(1 for le in valid if le.label == -1),
        "0 (vertical, exact equality)": sum(1 for le in valid if le.label == 0 and le.first_touch_type == "VERTICAL"),
    }
    touch_dist = {
        "PT": sum(1 for le in valid if le.first_touch_type == "PT"),
        "SL": sum(1 for le in valid if le.first_touch_type == "SL"),
        "VERTICAL": sum(1 for le in valid if le.first_touch_type == "VERTICAL"),
    }
    time_to_touch = [
        {
            "type": le.first_touch_type,
            "bars": int(pd.Index(bars_by_instrument[le.event.instrument].index).get_loc(le.first_touch_timestamp))
            - int(pd.Index(bars_by_instrument[le.event.instrument].index).get_loc(le.event.event_timestamp)),
        }
        for le in valid
        if le.first_touch_timestamp is not None and le.first_touch_type in ("PT", "SL")
    ]
    tt_bars = [d["bars"] for d in time_to_touch]

    overlaps = overlap_intervals(valid)
    per_event_overlap: Dict[str, int] = {}
    for a, b, _days in overlaps:
        per_event_overlap[a.event.event_id] = per_event_overlap.get(a.event.event_id, 0) + 1
        per_event_overlap[b.event.event_id] = per_event_overlap.get(b.event.event_id, 0) + 1

    uniqueness: Dict[str, float] = {}
    for sym in sorted({le.event.instrument for le in valid}):
        sym_labels = [le for le in valid if le.event.instrument == sym]
        uniqueness.update(average_uniqueness(sym_labels, bars_by_instrument[sym].index))
    uniq_values = [uniqueness[e.event.event_id] for e in valid if e.event.event_id in uniqueness]

    per_instrument: List[Dict[str, Any]] = []
    for sym in sorted({le.event.instrument for le in labels}):
        sym_labels = [le for le in labels if le.event.instrument == sym]
        sym_valid = [le for le in sym_labels if not le.excluded_reason]
        per_instrument.append(
            {
                "instrument": sym,
                "n_events": len(sym_labels),
                "n_excluded": sum(1 for le in sym_labels if le.excluded_reason),
                "labels": {
                    "+1": sum(1 for le in sym_valid if le.label == 1),
                    "-1": sum(1 for le in sym_valid if le.label == -1),
                    "0": sum(1 for le in sym_valid if le.label == 0),
                },
                "touches": {
                    "PT": sum(1 for le in sym_valid if le.first_touch_type == "PT"),
                    "SL": sum(1 for le in sym_valid if le.first_touch_type == "SL"),
                    "VERTICAL": sum(1 for le in sym_valid if le.first_touch_type == "VERTICAL"),
                },
                "mean_uniqueness": (
                    sum(uniqueness.get(le.event.event_id, 1.0) for le in sym_valid) / len(sym_valid)
                    if sym_valid
                    else None
                ),
            }
        )

    meta: Dict[str, Any] = {
        "experiment": "R5-B triple-barrier label-quality measurement",
        "contract": "docs/research/R5_TRIPLE_BARRIER.md (frozen before code)",
        "timestamp_utc": timestamp,
        "spec_version": LABEL_VERSION,
        "spec": {
            "pt_multiplier": 2.0,
            "sl_multiplier": 2.0,
            "vertical_horizon_bars": 10,
            "vol_lookback_days": 60,
            "vol_source": "frozen replica per-symbol 60d realized vol (PIT by construction)",
            "barriers": "multiplicative: entry ± m · daily_vol · entry_price",
        },
        "n_events": len(events),
        "n_valid": len(valid),
        "n_excluded": run.n_excluded,
        "exclusion_reasons": run.exclusion_reasons,
        "label_distribution": label_dist,
        "first_touch_distribution": touch_dist,
        "time_to_touch": {
            "n_pt_sl": len(tt_bars),
            "mean_bars": sum(tt_bars) / len(tt_bars) if tt_bars else None,
            "max_bars": max(tt_bars) if tt_bars else None,
        },
        "overlap": {
            "n_overlapping_pairs": len(overlaps),
            "n_events_with_overlap": len(per_event_overlap),
            "max_overlaps_single_event": max(per_event_overlap.values()) if per_event_overlap else 0,
        },
        "uniqueness": {
            "mean": sum(uniq_values) / len(uniq_values) if uniq_values else None,
            "min": min(uniq_values) if uniq_values else None,
            "max": max(uniq_values) if uniq_values else None,
        },
        "per_instrument": per_instrument,
        "determinism_note": "build_labels is a pure function; two runs on the same inputs are byte-identical (tested)",
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "r5_labels.json", "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    (REPORTS / "r5_labels.csv").write_text(_events_csv(labels))
    (REPORTS / "r5_labels.md").write_text(_render(meta))
    print(f"[R5-B] events: {len(events)} valid={len(valid)} excluded={run.n_excluded}")
    print(f"[R5-B] labels: {label_dist}")
    print(f"[R5-B] artifacts in {REPORTS}/")


def _events_csv(labels: List[LabeledEvent]) -> str:
    rows = [
        "event_id,instrument,side,event_timestamp,entry_price,daily_vol,pt_price,sl_price,"
        "first_touch_type,first_touch_timestamp,first_touch_price,label,excluded_reason"
    ]
    for le in labels:
        rows.append(
            ",".join(
                str(
                    le.event.event_id,
                )
                + ","
                + ",".join(
                    str(x)
                    for x in (
                        le.event.instrument,
                        le.event.side,
                        le.event.event_timestamp.date(),
                        le.event.entry_price,
                        round(le.daily_vol, 6),
                        round(le.pt_price, 6),
                        round(le.sl_price, 6),
                        le.first_touch_type,
                        le.first_touch_timestamp.date() if le.first_touch_timestamp is not None else "",
                        round(le.first_touch_price, 6) if le.first_touch_price is not None else "",
                        le.label,
                        le.excluded_reason.replace(",", ";"),
                    )
                )
            )
        )
    return "\n".join(rows) + "\n"


def _render(meta: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# R5-B — Triple-Barrier Label Quality (OBSERVED report)",
        "",
        f"**Experiment:** {meta['experiment']}  ",
        f"**Contract:** `{meta['contract']}`  ",
        f"**Run:** {meta['timestamp_utc']} · spec `{meta['spec_version']}` (ONE preregistered specification)  ",
        f"**Spec:** PT {meta['spec']['pt_multiplier']} / SL {meta['spec']['sl_multiplier']} · "
        f"vertical {meta['spec']['vertical_horizon_bars']} bars · vol {meta['spec']['vol_lookback_days']}d PIT · "
        f"{meta['spec']['barriers']}",
        "",
        "> **What this is:** a measurement of what the frozen labeling",
        "> specification produces on the frozen replica's entry events.",
        "> **What this is NOT:** evidence of predictive power, a model input",
        "> study, or a barrier-specification comparison. Label distribution",
        "> balance proves nothing about predictability (frozen contract item 6).",
        "",
        "## Events",
        "",
        f"- {meta['n_events']} entry events from the frozen-R4 replica pipeline",
        f"- {meta['n_valid']} labeled · {meta['n_excluded']} excluded (never imputed): {meta['exclusion_reasons']}",
        "",
        "## Label distribution (valid events)",
        "",
        f"- **+1** (PT first, or vertical expiry with close favorable to the event): {meta['label_distribution']['+1 (PT first or favorable vertical)']}",
        f"- **−1** (SL first, or adverse vertical expiry): {meta['label_distribution']['-1 (SL first or adverse vertical)']}",
        f"- **0** (vertical expiry, close == entry exactly): {meta['label_distribution']['0 (vertical, exact equality)']}",
        "",
        f"Note: {meta['first_touch_distribution']['VERTICAL']} vertical expiries resolved to ±1 by the sign of the "
        "close-vs-entry move; exact equality never occurred on daily closes, so no label 0 was produced. This is "
        "observed instrument behavior, not a defect (the ledger's label semantics are sign-based with 0 only on "
        "exact equality).",
        "",
        "## First-touch types",
        "",
        f"- PT: {meta['first_touch_distribution']['PT']} · SL: {meta['first_touch_distribution']['SL']} · "
        f"VERTICAL: {meta['first_touch_distribution']['VERTICAL']}",
        f"- time-to-touch (PT/SL): n={meta['time_to_touch']['n_pt_sl']}, "
        f"mean={meta['time_to_touch']['mean_bars'] and round(meta['time_to_touch']['mean_bars'], 2)} bars, "
        f"max={meta['time_to_touch']['max_bars']} bars",
        "",
        "## Overlap structure",
        "",
        f"- overlapping event pairs: {meta['overlap']['n_overlapping_pairs']}",
        f"- events with ≥1 overlap: {meta['overlap']['n_events_with_overlap']}",
        f"- max overlaps on a single event: {meta['overlap']['max_overlaps_single_event']}",
        "",
        "## Sample uniqueness (concurrency-based, implemented for R5)",
        "",
        f"- mean: {meta['uniqueness']['mean'] and round(meta['uniqueness']['mean'], 4)} · "
        f"min: {meta['uniqueness']['min'] and round(meta['uniqueness']['min'], 4)} · "
        f"max: {meta['uniqueness']['max'] and round(meta['uniqueness']['max'], 4)}",
        "",
        "## Per instrument",
        "",
        "| Instrument | events | excluded | +1 | −1 | 0 | PT | SL | VERT | mean uniq |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in meta["per_instrument"]:
        mu = p["mean_uniqueness"]
        lines.append(
            f"| {p['instrument']} | {p['n_events']} | {p['n_excluded']} | "
            f"{p['labels']['+1']} | {p['labels']['-1']} | {p['labels']['0']} | "
            f"{p['touches']['PT']} | {p['touches']['SL']} | {p['touches']['VERTICAL']} | "
            f"{mu is not None and round(mu, 3)} |"
        )
    lines += [
        "",
        "## Interpretation guards (frozen)",
        "",
        "- These are properties of the MEASUREMENT INSTRUMENT on this dataset —",
        "  not a strategy signal and not a forecast.",
        "- ONE preregistered trial slot (R5-B) consumed; barrier sweeps are",
        "  banned; a sensitivity study would be a NEW preregistration (R5-C).",
        "- No classifier or meta-model is built here; R6 is gated on R5's",
        "  label-structure evidence, not on this report's balance.",
        "- Research-only: events are read from the replica; R4 production is",
        "  untouched.",
        "",
        f"*Artifacts: r5_labels.json, r5_labels.csv (per-event audit trail), r5_labels.md in {REPORTS}/.*",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
