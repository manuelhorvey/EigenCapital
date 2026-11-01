"""Schema-versioning tests for DailyLossTracker (F-22).

Covers daily_baseline.json schema v1: writing adds schema_version,
legacy (unversioned) files migrate preserving all fields, unknown
schema versions fail closed (never silently interpreted).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eigencapital.live.daily_loss import (
    BASELINE_SCHEMA,
    DailyBaseline,
    DailyLossTracker,
    SchemaError,
    read_versioned,
    write_versioned,
)


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _current_baseline_payload() -> dict:
    return {
        "schema_version": 1,
        "date_str": "2026-10-29",
        "equity": 18177.0,
        "timestamp_utc": "2026-10-29T13:31:37.639575+00:00",
        "hash": "0f29e7a5b257a4e4b0e6d93c36cdb4f5bce54ea72a8c31fab2eba2174d65bbf6",
    }


def _legacy_baseline_payload() -> dict:
    return {
        "date_str": "2026-10-29",
        "equity": 18177.0,
        "timestamp_utc": "2026-10-29T13:31:37.639575+00:00",
        "hash": "0f29e7a5b257a4e4b0e6d93c36cdb4f5bce54ea72a8c31fab2eba2174d65bbf6",
    }


# ═════════════════════════════════════════════════════════════════════
# BASELINE_SCHEMA validation
# ═════════════════════════════════════════════════════════════════════


def test_baseline_schema_version_is_one() -> None:
    assert BASELINE_SCHEMA.version == 1
    assert BASELINE_SCHEMA.name == "daily_baseline.json"
    assert BASELINE_SCHEMA.migrator is not None


# ═════════════════════════════════════════════════════════════════════
# read_versioned on daily_baseline.json
# ═════════════════════════════════════════════════════════════════════


def test_read_current_baseline_version(tmp_path: Path) -> None:
    p = tmp_path / "daily_baseline.json"
    _write(p, _current_baseline_payload())

    result = read_versioned(p, BASELINE_SCHEMA)
    assert result is not None
    data, version = result
    assert version == 1
    assert data["date_str"] == "2026-10-29"
    assert data["equity"] == 18177.0


def test_read_legacy_baseline_migrated(tmp_path: Path) -> None:
    """Legacy (unversioned) baseline migrates to v1, fields preserved."""
    p = tmp_path / "daily_baseline.json"
    _write(p, _legacy_baseline_payload())

    result = read_versioned(p, BASELINE_SCHEMA)
    assert result is not None
    data, version = result
    assert version == 1
    # All original fields preserved (no data loss)
    assert data["date_str"] == "2026-10-29"
    assert data["equity"] == 18177.0
    assert data["timestamp_utc"] == "2026-10-29T13:31:37.639575+00:00"
    assert data["schema_version"] == 1


def test_read_unknown_baseline_version_fails_closed(tmp_path: Path) -> None:
    """Unknown schema version → SchemaError, never silently interpreted."""
    p = tmp_path / "daily_baseline.json"
    payload = _current_baseline_payload()
    payload["schema_version"] = 99
    _write(p, payload)

    with pytest.raises(SchemaError, match="unsupported schema version"):
        read_versioned(p, BASELINE_SCHEMA)


def test_read_missing_baseline_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "daily_baseline.json"
    assert read_versioned(p, BASELINE_SCHEMA) is None


def test_read_malformed_baseline_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "daily_baseline.json"
    p.write_text("{not valid", encoding="utf-8")
    assert read_versioned(p, BASELINE_SCHEMA) is None


# ═════════════════════════════════════════════════════════════════════
# write_versioned on daily_baseline.json
# ═════════════════════════════════════════════════════════════════════


def test_write_baseline_adds_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "daily_baseline.json"
    write_versioned(
        p,
        {
            "date_str": "2026-10-29",
            "equity": 18177.0,
            "timestamp_utc": "2026-10-29T13:31:37Z",
        },
        BASELINE_SCHEMA,
    )

    result = read_versioned(p, BASELINE_SCHEMA)
    assert result is not None
    data, version = result
    assert version == 1
    assert data["schema_version"] == 1


def test_write_baseline_rejects_missing_required_field(tmp_path: Path) -> None:
    p = tmp_path / "daily_baseline.json"
    with pytest.raises(SchemaError, match="missing required fields"):
        write_versioned(
            p,
            {"date_str": "2026-10-29", "equity": 18177.0},
            BASELINE_SCHEMA,
        )  # missing timestamp_utc


# ═════════════════════════════════════════════════════════════════════
# DailyLossTracker integration with schema
# ═════════════════════════════════════════════════════════════════════


def test_tracker_writes_schema_version_on_initialize(tmp_path: Path) -> None:
    tracker = DailyLossTracker(persistence_dir=str(tmp_path))
    tracker.initialize(broker_equity=5010.94)

    raw = json.loads((tmp_path / "daily_baseline.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["date_str"] == tracker.baseline_date
    assert raw["equity"] == 5010.94


def test_tracker_reads_legacy_baseline_and_migrates(tmp_path: Path) -> None:
    """Tracker loads a legacy baseline (unversioned) and migrates it."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    # Build a valid legacy payload (no schema_version) with a correct hash.
    tmp_baseline = DailyBaseline(
        date_str=today, equity=18177.0, timestamp_utc="2026-10-29T13:31:37Z"
    )
    valid_hash = tmp_baseline.compute_hash()

    (tmp_path / "daily_baseline.json").write_text(
        json.dumps(
            {
                "date_str": today,
                "equity": 18177.0,
                "timestamp_utc": "2026-10-29T13:31:37Z",
                "hash": valid_hash,
            }
        ),
        encoding="utf-8",
    )
    tracker = DailyLossTracker(persistence_dir=str(tmp_path))
    tracker.initialize(broker_equity=9999.0)  # ignored — valid baseline exists today

    # Should use the migrated legacy baseline, not re-baseline from 9999
    assert tracker.baseline_equity == 18177.0
    assert tracker.baseline_date == today
    assert tracker.baseline_trusted is True


def test_tracker_unknown_schema_version_fail_closed(tmp_path: Path) -> None:
    """Unknown baseline schema version → fail closed (blocked)."""
    (tmp_path / "daily_baseline.json").write_text(
        json.dumps(
            {
                "schema_version": 99,
                "date_str": "2026-10-29",
                "equity": 18177.0,
                "timestamp_utc": "2026-10-29T13:31:37Z",
            }
        ),
        encoding="utf-8",
    )
    tracker = DailyLossTracker(persistence_dir=str(tmp_path))
    tracker.initialize(broker_equity=5010.94)

    # Fail closed: untrusted baseline → blocked
    assert tracker.is_daily_loss_breached is True
    assert tracker.baseline_trusted is False

