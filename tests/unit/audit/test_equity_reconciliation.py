from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "audit" / "equity_reconciliation.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("equity_reconciliation", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _snapshot(timestamp: str, equity: float) -> dict[str, object]:
    return {"timestamp": timestamp, "equity": equity}


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _write_statement(path: Path, rows: list[dict[str, object]]) -> None:
    lines = ["timestamp,type,amount,reference,currency\n"]
    for row in rows:
        lines.append(
            f"{row['timestamp']},{row['type']},{row['amount']},{row['reference']},{row.get('currency', 'USD')}\n"
        )
    path.write_text("".join(lines))


def _run(
    module,
    tmp_path: Path,
    statement_rows: list[dict[str, object]],
    *,
    snapshots: list[dict[str, object]] | None = None,
    extra: list[str] | None = None,
) -> tuple[int, dict[str, object] | None]:
    snapshot_path = tmp_path / "snapshots.jsonl"
    statement_path = tmp_path / "statement.csv"
    output_path = tmp_path / "report.json"
    if snapshots is None:
        snapshots = [
            _snapshot("2026-01-01T00:00:00Z", 1000.0),
            _snapshot("2026-01-02T00:00:00Z", 1200.0),
            _snapshot("2026-01-03T00:00:00Z", 1200.0),
        ]
    _write_jsonl(snapshot_path, snapshots)
    _write_statement(statement_path, statement_rows)
    argv = [
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-03",
        "--statement",
        str(statement_path),
        "--snapshots",
        str(snapshot_path),
        "--output",
        str(output_path),
    ]
    if extra:
        argv.extend(extra)
    code = module.main(argv)
    report = json.loads(output_path.read_text()) if output_path.exists() else None
    return code, report


def test_deposit_reconciles_material_jump(module, tmp_path: Path) -> None:
    code, report = _run(
        module,
        tmp_path,
        [{"timestamp": "2026-01-01T12:00:00Z", "type": "deposit", "amount": 200, "reference": "DEP-1"}],
    )

    assert code == 0
    assert report is not None
    assert report["verdict"] == "PASS"
    assert report["unexplained_steps"] == 0
    assert report["unexplained_jumps"] == 0
    assert len(report["steps"]) == 2
    assert len(report["jumps"]) == 1
    assert report["jumps"][0]["classification"] == "RECONCILED"
    assert report["jumps"][0]["explained_by"] == ["deposit"]
    assert report["jumps"][0]["evidence_refs"] == ["DEP-1"]


def test_unexplained_jump_fails(module, tmp_path: Path) -> None:
    code, report = _run(module, tmp_path, [])

    assert code == 1
    assert report is not None
    assert report["verdict"] == "FAIL"
    assert report["unexplained_steps"] == 1
    assert report["unexplained_jumps"] == 1
    assert report["jumps"][0]["classification"] == "UNEXPLAINED"
    assert report["jumps"][0]["residual"] == pytest.approx(200.0)


def test_realized_pnl_explains_jump(module, tmp_path: Path) -> None:
    code, report = _run(
        module,
        tmp_path,
        [{"timestamp": "2026-01-01T12:00:00Z", "type": "realized_pnl", "amount": 200, "reference": "DEAL-1"}],
    )

    assert code == 0
    assert report is not None
    assert report["verdict"] == "PASS"
    assert report["jumps"][0]["explained_by"] == ["realized_pnl"]


def test_missing_statement_exits_2(module, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshots.jsonl"
    _write_jsonl(
        snapshot_path,
        [
            _snapshot("2026-01-01T00:00:00Z", 1000.0),
            _snapshot("2026-01-02T00:00:00Z", 1200.0),
        ],
    )
    output_path = tmp_path / "report.json"

    code = module.main(
        [
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
            "--statement",
            str(tmp_path / "missing.csv"),
            "--snapshots",
            str(snapshot_path),
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    assert not output_path.exists()


def test_unknown_statement_type_exits_2(module, tmp_path: Path) -> None:
    code, report = _run(
        module,
        tmp_path,
        [{"timestamp": "2026-01-01T12:00:00Z", "type": "bonus", "amount": 200, "reference": "BONUS-1"}],
    )

    assert code == 2
    assert report is None


def test_non_usd_statement_exits_2(module, tmp_path: Path) -> None:
    code, report = _run(
        module,
        tmp_path,
        [
            {
                "timestamp": "2026-01-01T12:00:00Z",
                "type": "deposit",
                "amount": 200,
                "reference": "DEP-1",
                "currency": "EUR",
            }
        ],
    )

    assert code == 2
    assert report is None


def test_threshold_controls_material_jumps(module, tmp_path: Path) -> None:
    snapshots = [
        _snapshot("2026-01-01T00:00:00Z", 1000.0),
        _snapshot("2026-01-02T00:00:00Z", 1120.0),
        _snapshot("2026-01-03T00:00:00Z", 1120.0),
    ]
    rows = [{"timestamp": "2026-01-01T12:00:00Z", "type": "deposit", "amount": 120, "reference": "DEP-1"}]

    code, report = _run(module, tmp_path, rows, snapshots=snapshots)
    assert code == 0
    assert report is not None
    assert len(report["jumps"]) == 1

    code, report = _run(
        module,
        tmp_path,
        rows,
        snapshots=snapshots,
        extra=["--jump-threshold-pct", "15"],
    )
    assert code == 0
    assert report is not None
    assert report["jumps"] == []
    assert report["unexplained_steps"] == 0


def test_total_delta_must_reconcile(module, tmp_path: Path) -> None:
    rows = [
        {"timestamp": "2026-01-01T12:00:00Z", "type": "deposit", "amount": 200, "reference": "DEP-1"},
        {"timestamp": "2026-01-03T12:00:00Z", "type": "fee", "amount": -10, "reference": "FEE-1"},
    ]

    code, report = _run(module, tmp_path, rows)

    assert code == 1
    assert report is not None
    assert report["unexplained_steps"] == 0
    assert report["within_tolerance"] is False
    assert report["delta"] == pytest.approx(10.0)
    assert report["verdict"] == "FAIL"


def test_report_schema(module, tmp_path: Path) -> None:
    code, report = _run(
        module,
        tmp_path,
        [{"timestamp": "2026-01-01T12:00:00Z", "type": "deposit", "amount": 200, "reference": "DEP-1"}],
    )

    assert code == 0
    assert report is not None
    expected = {
        "schema_version",
        "generated_at_utc",
        "start",
        "end",
        "snapshot_path",
        "snapshot_count",
        "statement_path",
        "statement_sha256",
        "statement_row_count",
        "jump_threshold_pct",
        "opening_equity",
        "closing_equity",
        "net_equity_change",
        "statement_totals",
        "total_statement_delta",
        "reconstructed_equity",
        "delta",
        "within_tolerance",
        "steps",
        "jumps",
        "unexplained_steps",
        "unexplained_jumps",
        "verdict",
    }
    assert expected <= set(report)
    assert report["schema_version"] == "1.0"
    assert len(report["statement_sha256"]) == 64
    assert report["statement_totals"] == {"deposit": 200.0}
    assert report["jump_threshold_pct"] == 10.0
