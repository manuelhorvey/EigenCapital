#!/usr/bin/env python3
"""Provenance CLI — inspect decisions captured by the Decision Provenance Layer.

Usage:
    PYTHONPATH=. python scripts/provenance_cli.py [command] [options]

Commands:
    recent [asset]       Show the most recent N decisions (default 10)
    get <decision_id>    Show a single decision by its UUID
    stats                Summary statistics across all records
    validate [N]         Run M2 validation on the most recent N records (default 100)
    watch [asset]        Tail recent decisions (poll every 5s)
    cf <id> <type> ...   Run a counterfactual on a decision

Counterfactual types:
    cf <id> gate <gate_name> <pass|block>
        Override a gate. Gate names: spread_gate_blocked, session_gate_blocked,
        confidence_gate_blocked, conviction_gate_blocked, hysteresis_blocked,
        vix_gate_blocked, adx_gate_blocked, sell_only_filtered, etc.
    cf <id> prob <long> <short> <neutral>
        Override model probabilities (0.0-1.0 each, should sum to ~1.0).
    cf <id> signal <BUY|SELL|HOLD>
        Force the final signal.
    cf <id> sltp <sl_price> <tp_price>
        Override stop-loss and take-profit prices.

Examples:
    python scripts/provenance_cli.py recent GBPJPY
    python scripts/provenance_cli.py get 18c6754d-af73-4a11-b23a-2c3f19d35d64
    python scripts/provenance_cli.py stats
    python scripts/provenance_cli.py validate 50
    python scripts/provenance_cli.py watch
    python scripts/provenance_cli.py cf <id> gate spread_gate_blocked pass
    python scripts/provenance_cli.py cf <id> prob 0.8 0.1 0.1
    python scripts/provenance_cli.py cf <id> signal BUY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from eigencapital.domain.provenance import (
    DecisionProvenance,
    PROVENANCE_SCHEMA_VERSION,
)
from eigencapital.domain.provenance.provenance_store import SqliteProvenanceStore
from eigencapital.domain.provenance.counterfactual import CounterfactualEngine
from eigencapital.domain.provenance.validator import ProvenanceValidator

# Default store path — same as what PaperTradingEngine uses
DEFAULT_DB = os.environ.get(
    "EIGENCAPITAL_PROVENANCE_DB",
    str(Path.home() / ".eigencapital" / "data" / "provenance.db"),
)


def _get_store(path: str | None = None) -> SqliteProvenanceStore:
    db = path or DEFAULT_DB
    if not os.path.isfile(db):
        print(f"Provenance database not found at: {db}")
        print("Hint: set EIGENCAPITAL_PROVENANCE_DB or run the engine first to capture decisions.")
        sys.exit(1)
    store = SqliteProvenanceStore(db)
    store.initialize()
    return store


def _fmt_timestamp(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts or "—"


def _fmt_dollar(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%"


def _signal_emoji(s: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪", "FLAT": "⚫"}.get(s.upper(), "❓")


def cmd_recent(args):
    store = _get_store(args.db)
    asset_filter = args.asset
    records = store.query(asset=asset_filter, limit=args.limit)
    if not records:
        print(f"No provenance records found{' for ' + asset_filter if asset_filter else ''}.")
        return

    print(f"{'Cycle':>5}  {'Asset':<8}  {'Signal':<8}  {'Timestamp':<20}  {'Equity':<12}  {'DD':<8}  {'Config':<10}")
    print("-" * 80)
    for r in records:
        sig = r.decision.final_signal if r.decision else "—"
        eq = _fmt_dollar(r.runtime.total_equity if r.runtime else None)
        dd = _fmt_pct(r.runtime.drawdown_pct if r.runtime else None)
        cfg_hash = r.config_hash[:10] if r.config_hash else "—"
        print(
            f"{r.cycle_id:>5}  {r.asset:<8}  {_signal_emoji(sig)} {sig:<6}  "
            f"{_fmt_timestamp(r.decision_timestamp):<20}  {eq:<12}  {dd:<8}  {cfg_hash:<10}"
        )
    print(f"\n{len(records)} record(s)")


def cmd_get(args):
    store = _get_store(args.db)
    record = store.get_by_decision_id(args.decision_id)
    if record is None:
        print(f"Decision not found: {args.decision_id}")
        sys.exit(1)

    d = record.to_dict()
    print(json.dumps(d, indent=2, default=str))


def cmd_stats(args):
    store = _get_store(args.db)
    total = store.count()
    if total == 0:
        print("No provenance records found.")
        return

    latest = store.query(limit=1)
    asset_counts: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    for r in store.query(limit=min(total, 5000)):
        asset_counts[r.asset] = asset_counts.get(r.asset, 0) + 1
        sig = r.decision.final_signal if r.decision else "—"
        signal_counts[sig] = signal_counts.get(sig, 0) + 1

    print(f"Total records:      {total}")
    print(f"Schema version:     {PROVENANCE_SCHEMA_VERSION}")
    if latest:
        print(f"Latest timestamp:   {_fmt_timestamp(latest[0].decision_timestamp)}")
        print(f"Latest cycle_id:    {latest[0].cycle_id}")
    print(f"Unique assets:      {len(asset_counts)}")
    print(f"\nSignals:")
    for sig, count in sorted(signal_counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  {_signal_emoji(sig)} {sig:<8}  {count:>5}  ({pct:5.1f}%)")
    print(f"\nTop assets:")
    for asset, count in sorted(asset_counts.items(), key=lambda x: -x[1])[:10]:
        pct = count / total * 100
        print(f"  {asset:<8}  {count:>5}  ({pct:5.1f}%)")


def cmd_validate(args):
    store = _get_store(args.db)
    total = store.count()
    if total == 0:
        print("No records to validate.")
        return

    n = min(args.n, total)
    records = store.query(limit=n)
    validator = ProvenanceValidator(strict=args.strict)
    result = validator.validate_batch(records)

    print(f"Validated {len(records)} records (strict={args.strict})")
    print(f"  Errors:   {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Valid:    {result.is_valid}")

    if result.errors:
        print("\nErrors:")
        for issue in result.errors[:20]:
            print(f"  ✗ {issue}")
        if len(result.errors) > 20:
            print(f"  ... and {len(result.errors) - 20} more")

    if result.warnings:
        print("\nWarnings:")
        for issue in result.warnings[:20]:
            print(f"  ⚠ {issue}")
        if len(result.warnings) > 20:
            print(f"  ... and {len(result.warnings) - 20} more")


def cmd_watch(args):
    store = _get_store(args.db)
    last_count = store.count()
    asset_filter = args.asset
    print(f"Watching provenance stream{' for ' + asset_filter if asset_filter else ''}...")
    print("(Ctrl+C to stop)")

    try:
        while True:
            time.sleep(5)
            current = store.count()
            if current > last_count:
                new_records = store.query(limit=current - last_count, asset=asset_filter)
                for r in reversed(new_records):
                    sig = r.decision.final_signal if r.decision else "—"
                    eq = _fmt_dollar(r.runtime.total_equity if r.runtime else None)
                    print(
                        f"[{_fmt_timestamp(r.decision_timestamp)}] "
                        f"{r.asset:<8} {_signal_emoji(sig)} {sig:<6} "
                        f"cycle={r.cycle_id} equity={eq}"
                    )
                last_count = current
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_counterfactual(args):
    store = _get_store(args.db)
    original = store.get_by_decision_id(args.decision_id)
    if original is None:
        print(f"Decision not found: {args.decision_id}")
        sys.exit(1)

    engine = CounterfactualEngine()
    cf_type = args.cf_type

    if cf_type == "gate":
        gate_name = args.gate_name
        passed_str = args.pass_or_block
        passed = passed_str == "pass"
        cf, delta = engine.gate_override(original, gate_name, passed)
    elif cf_type == "prob":
        p_long = float(args.long)
        p_short = float(args.short)
        p_neutral = float(args.neutral)
        cf, delta = engine.probability_override(original, p_long, p_short, p_neutral)
    elif cf_type == "signal":
        cf, delta = engine.signal_override(original, args.new_signal.upper())
    elif cf_type == "sltp":
        sl = float(args.sl) if args.sl != "None" else None
        tp = float(args.tp) if args.tp != "None" else None
        cf, delta = engine.sltp_override(original, stop_loss=sl, take_profit=tp)
    else:
        print(f"Unknown counterfactual type: {cf_type}")
        sys.exit(1)

    store.store(cf)
    print(f"Counterfactual stored: {cf.decision_id.decision_id}")
    print(f"  Type:     {delta.modification_type}")
    print(f"  Field:    {delta.field}")
    print(f"  Original: {delta.original_value}")
    print(f"  New:      {delta.new_value}")
    print(f"  Desc:     {delta.description}")
    print()
    print(f"  Original signal: {original.decision.final_signal if original.decision else '—'}")
    print(f"  Counterfactual signal: {cf.decision.final_signal if cf.decision else '—'}")
    if args.diff:
        print()
        print("Full counterfactual record:")
        print(json.dumps(cf.to_dict(), indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="Decision Provenance Layer CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", help=f"Provenance DB path (default: {DEFAULT_DB})")
    parser.add_argument("--limit", type=int, default=10, help="Max records (default: 10)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_recent = sub.add_parser("recent", help="Show recent decisions")
    p_recent.add_argument("asset", nargs="?", default=None, help="Filter by asset")
    p_recent.set_defaults(func=cmd_recent)

    p_get = sub.add_parser("get", help="Show a single decision by ID")
    p_get.add_argument("decision_id", help="Decision UUID")
    p_get.set_defaults(func=cmd_get)

    p_stats = sub.add_parser("stats", help="Summary statistics")
    p_stats.set_defaults(func=cmd_stats)

    p_validate = sub.add_parser("validate", help="Run M2 validation")
    p_validate.add_argument("n", nargs="?", type=int, default=100, help="Number of records to validate")
    p_validate.add_argument("--strict", action="store_true", help="Require all 6 contexts")
    p_validate.set_defaults(func=cmd_validate)

    p_watch = sub.add_parser("watch", help="Tail recent decisions")
    p_watch.add_argument("asset", nargs="?", default=None, help="Filter by asset")
    p_watch.set_defaults(func=cmd_watch)

    p_cf = sub.add_parser("cf", help="Run a counterfactual on a decision")
    p_cf.add_argument("decision_id", help="Original decision UUID")
    p_cf.add_argument("cf_type", choices=["gate", "prob", "signal", "sltp"], help="Counterfactual type")
    p_cf.add_argument("args", nargs="*", help="Type-specific arguments")
    p_cf.add_argument("--diff", action="store_true", help="Print full counterfactual record")
    p_cf.set_defaults(func=_cf_dispatch)

    args = parser.parse_args()
    args.func(args)


def _cf_dispatch(args):
    import sys

    argv = args.args
    if args.cf_type == "gate":
        if len(argv) < 2:
            print("Usage: cf <id> gate <gate_name> <pass|block>")
            sys.exit(1)
        args.gate_name = argv[0]
        args.pass_or_block = argv[1]
    elif args.cf_type == "prob":
        if len(argv) < 3:
            print("Usage: cf <id> prob <long> <short> <neutral>")
            sys.exit(1)
        args.long = argv[0]
        args.short = argv[1]
        args.neutral = argv[2]
    elif args.cf_type == "signal":
        if len(argv) < 1:
            print("Usage: cf <id> signal <BUY|SELL|HOLD>")
            sys.exit(1)
        args.new_signal = argv[0]
    elif args.cf_type == "sltp":
        if len(argv) < 2:
            print("Usage: cf <id> sltp <sl_price> <tp_price> (use 'None' to keep existing)")
            sys.exit(1)
        args.sl = argv[0]
        args.tp = argv[1]
    cmd_counterfactual(args)


if __name__ == "__main__":
    main()
