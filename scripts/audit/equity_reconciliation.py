"""P0-1 equity reconciliation for the EC-AUDIT-009 closure gate.

Reads equity snapshots and a broker statement CSV, classifies every
consecutive equity step, and reconciles each step against statement
transactions. The tool fails closed when the statement is missing, malformed,
non-USD, or leaves any step unexplained.

Statement CSV schema (header required):
    timestamp,type,amount,reference,currency,balance_after,equity_after

- ``timestamp``: ISO 8601 with timezone.
- ``type``: deposit, withdrawal, credit, adjustment, realized_pnl,
  floating_pnl, fee, or swap.
- ``amount``: signed USD amount.
- ``reference``: non-empty broker reference.
- ``currency``: optional, must be USD when present.
- ``balance_after`` / ``equity_after``: optional anchors.

Exit codes: 0 = PASS, 1 = FAIL, 2 = input error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOTS = REPO / "reports" / "r4_loop" / "portfolio_analytics.jsonl"
DEFAULT_OUTPUT_DIR = REPO / "reports" / "audits"
TOLERANCE_USD = 0.01
ALLOWED_TYPES = {
    "deposit",
    "withdrawal",
    "credit",
    "adjustment",
    "realized_pnl",
    "floating_pnl",
    "fee",
    "swap",
}
REQUIRED_STATEMENT_COLUMNS = {"timestamp", "type", "amount", "reference"}


@dataclass(frozen=True)
class Snapshot:
    timestamp: datetime
    equity: float


@dataclass(frozen=True)
class StatementRow:
    timestamp: datetime
    type: str
    amount: float
    reference: str
    currency: str
    balance_after: float | None
    equity_after: float | None


@dataclass(frozen=True)
class Step:
    before: Snapshot
    after: Snapshot
    delta: float
    pct: float
    statement_delta: float
    residual: float
    classification: str
    explained_by: list[str]
    evidence_refs: list[str]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _window(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise ValueError("--end must be on or after --start")
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end, time.max, tzinfo=UTC),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = float(str(value))
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite number: {value!r}")
    return parsed


def load_snapshots(path: Path, start: datetime, end: datetime) -> list[Snapshot]:
    if not path.exists():
        raise FileNotFoundError(f"snapshot file not found: {path}")
    snapshots: list[Snapshot] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            timestamp = _parse_timestamp(str(record["timestamp"]))
            equity = float(record["equity"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid snapshot: {exc}") from exc
        if not math.isfinite(equity):
            raise ValueError(f"{path}:{line_number}: equity is not finite")
        if start <= timestamp <= end:
            snapshots.append(Snapshot(timestamp=timestamp, equity=equity))
    snapshots.sort(key=lambda item: item.timestamp)
    if len(snapshots) < 2:
        raise ValueError(f"{path}: need at least two snapshots in the window")
    return snapshots


def load_statement(path: Path, start: datetime, end: datetime) -> list[StatementRow]:
    if not path.exists():
        raise FileNotFoundError(f"broker statement not found: {path}")
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: statement has no header")
        missing = REQUIRED_STATEMENT_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{path}: missing columns: {sorted(missing)}")
        rows: list[StatementRow] = []
        for line_number, raw in enumerate(reader, start=2):
            try:
                timestamp = _parse_timestamp(str(raw["timestamp"]))
                row_type = str(raw["type"]).strip().lower()
                amount = float(raw["amount"])
                reference = str(raw["reference"]).strip()
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid row: {exc}") from exc
            if row_type not in ALLOWED_TYPES:
                raise ValueError(f"{path}:{line_number}: unknown type {row_type!r}")
            if not reference:
                raise ValueError(f"{path}:{line_number}: empty reference")
            if not math.isfinite(amount):
                raise ValueError(f"{path}:{line_number}: amount is not finite")
            currency = str(raw.get("currency") or "USD").strip().upper()
            if currency != "USD":
                raise ValueError(f"{path}:{line_number}: unsupported currency {currency!r}; USD required")
            if start <= timestamp <= end:
                rows.append(
                    StatementRow(
                        timestamp=timestamp,
                        type=row_type,
                        amount=amount,
                        reference=reference,
                        currency=currency,
                        balance_after=_optional_float(raw.get("balance_after")),
                        equity_after=_optional_float(raw.get("equity_after")),
                    )
                )
    rows.sort(key=lambda item: item.timestamp)
    return rows


def build_steps(snapshots: list[Snapshot]) -> list[Step]:
    steps: list[Step] = []
    for before, after in zip(snapshots, snapshots[1:]):
        if before.equity <= 0:
            raise ValueError(f"non-positive equity at {before.timestamp.isoformat()}")
        delta = after.equity - before.equity
        steps.append(
            Step(
                before=before,
                after=after,
                delta=delta,
                pct=delta / before.equity,
                statement_delta=0.0,
                residual=delta,
                classification="UNEXPLAINED",
                explained_by=[],
                evidence_refs=[],
            )
        )
    return steps


def reconcile_steps(steps: list[Step], rows: list[StatementRow]) -> list[Step]:
    reconciled: list[Step] = []
    for step in steps:
        window = [row for row in rows if step.before.timestamp < row.timestamp <= step.after.timestamp]
        statement_delta = sum(row.amount for row in window)
        residual = step.delta - statement_delta
        classification = "RECONCILED" if abs(residual) <= TOLERANCE_USD else "UNEXPLAINED"
        reconciled.append(
            replace(
                step,
                statement_delta=statement_delta,
                residual=residual,
                classification=classification,
                explained_by=sorted({row.type for row in window}),
                evidence_refs=[row.reference for row in window],
            )
        )
    return reconciled


def _step_to_dict(step: Step) -> dict[str, object]:
    return {
        "from_timestamp": step.before.timestamp.isoformat(),
        "to_timestamp": step.after.timestamp.isoformat(),
        "equity_before": step.before.equity,
        "equity_after": step.after.equity,
        "delta": step.delta,
        "pct": step.pct,
        "statement_delta": step.statement_delta,
        "residual": step.residual,
        "classification": step.classification,
        "explained_by": step.explained_by,
        "evidence_refs": step.evidence_refs,
    }


def build_report(
    snapshots: list[Snapshot],
    steps: list[Step],
    rows: list[StatementRow],
    *,
    statement_path: Path,
    snapshot_path: Path,
    threshold_pct: float,
) -> dict[str, Any]:
    opening = snapshots[0].equity
    closing = snapshots[-1].equity
    total_statement_delta = sum(row.amount for row in rows)
    reconstructed = opening + total_statement_delta
    delta = closing - reconstructed
    totals: dict[str, float] = {}
    for row in rows:
        totals[row.type] = totals.get(row.type, 0.0) + row.amount
    jumps = [step for step in steps if abs(step.pct) >= threshold_pct / 100.0]
    unexplained_steps = sum(1 for step in steps if step.classification != "RECONCILED")
    unexplained_jumps = sum(1 for step in jumps if step.classification != "RECONCILED")
    within_tolerance = abs(delta) <= TOLERANCE_USD
    verdict = "PASS" if unexplained_steps == 0 and within_tolerance else "FAIL"
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "start": snapshots[0].timestamp.isoformat(),
        "end": snapshots[-1].timestamp.isoformat(),
        "snapshot_path": str(snapshot_path),
        "snapshot_count": len(snapshots),
        "statement_path": str(statement_path),
        "statement_sha256": _sha256(statement_path),
        "statement_row_count": len(rows),
        "jump_threshold_pct": threshold_pct,
        "opening_equity": opening,
        "closing_equity": closing,
        "net_equity_change": closing - opening,
        "statement_totals": dict(sorted(totals.items())),
        "total_statement_delta": total_statement_delta,
        "reconstructed_equity": reconstructed,
        "delta": delta,
        "within_tolerance": within_tolerance,
        "steps": [_step_to_dict(step) for step in steps],
        "jumps": [_step_to_dict(step) for step in jumps],
        "unexplained_steps": unexplained_steps,
        "unexplained_jumps": unexplained_jumps,
        "verdict": verdict,
    }


def _print_summary(report: dict[str, Any]) -> None:
    print(f"Verdict: {report['verdict']}")
    print(
        f"Snapshots: {report['snapshot_count']} | "
        f"Steps: {len(report['steps'])} | "
        f"Jumps: {len(report['jumps'])} | "
        f"Unexplained steps: {report['unexplained_steps']} | "
        f"Unexplained jumps: {report['unexplained_jumps']}"
    )
    print(
        f"Opening: ${report['opening_equity']:,.2f} | "
        f"Closing: ${report['closing_equity']:,.2f} | "
        f"Statement delta: ${report['total_statement_delta']:,.2f} | "
        f"Residual: ${report['delta']:,.2f}"
    )
    for jump in report["jumps"]:
        print(
            f"  {jump['from_timestamp']} -> {jump['to_timestamp']}: "
            f"{jump['pct'] * 100:+.2f}% | {jump['classification']} | "
            f"residual ${jump['residual']:,.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile equity steps against a broker statement")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD, UTC)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD, UTC)")
    parser.add_argument("--statement", required=True, help="Broker statement CSV")
    parser.add_argument("--snapshots", default=str(DEFAULT_SNAPSHOTS), help="Equity snapshot JSONL")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / f"equity_reconciliation_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"),
        help="Output JSON path",
    )
    parser.add_argument("--jump-threshold-pct", type=float, default=10.0, help="Material jump threshold")
    args = parser.parse_args(argv)

    try:
        start, end = _window(_parse_date(args.start), _parse_date(args.end))
        snapshot_path = Path(args.snapshots)
        statement_path = Path(args.statement)
        snapshots = load_snapshots(snapshot_path, start, end)
        rows = load_statement(statement_path, start, end)
        steps = reconcile_steps(build_steps(snapshots), rows)
        report = build_report(
            snapshots,
            steps,
            rows,
            statement_path=statement_path,
            snapshot_path=snapshot_path,
            threshold_pct=args.jump_threshold_pct,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_summary(report)
    print(f"Report: {output}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
