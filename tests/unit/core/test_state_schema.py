"""Tests for the state-file schema versioning framework (F-22)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eigencapital.core.state_schema import (
    LEGACY_VERSION,
    SchemaDefinition,
    SchemaError,
    SchemaRegistry,
    read_versioned,
    write_versioned,
)


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


def _make_schema() -> SchemaDefinition:
    return SchemaDefinition(
        name="test_state.json",
        version=2,
        required_fields={"id", "value"},
        optional_fields={"note"},
    )


def _current_payload() -> dict:
    return {"schema_version": 2, "id": "abc", "value": 42, "note": "ok"}


def _legacy_payload() -> dict:
    return {"id": "legacy", "value": 7}


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════
# read_versioned — current version
# ═════════════════════════════════════════════════════════════════════


def test_read_current_version(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    _write(p, _current_payload())

    result = read_versioned(p, schema)
    assert result is not None
    data, version = result
    assert version == 2
    assert data["id"] == "abc"


def test_read_current_version_validates_required_fields(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    _write(p, {"schema_version": 2, "id": "abc"})  # missing "value"

    with pytest.raises(SchemaError, match="missing required fields"):
        read_versioned(p, schema)


def test_read_current_version_rejects_unknown_fields(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    _write(p, {"schema_version": 2, "id": "abc", "value": 1, "extra": "nope"})

    with pytest.raises(SchemaError, match="unexpected fields"):
        read_versioned(p, schema)


# ═════════════════════════════════════════════════════════════════════
# read_versioned — legacy (unversioned)
# ═════════════════════════════════════════════════════════════════════


def test_read_legacy_passthrough_without_migrator(tmp_path: Path) -> None:
    """Legacy file without migrator → passthrough at version 0, no data loss."""
    schema = SchemaDefinition(
        name="test_state.json", version=2, required_fields={"id"}
    )  # no migrator
    p = tmp_path / "test_state.json"
    _write(p, _legacy_payload())

    result = read_versioned(p, schema)
    assert result is not None
    data, version = result
    assert version == LEGACY_VERSION
    assert data["id"] == "legacy"


def test_read_legacy_migrated_with_migrator(tmp_path: Path) -> None:
    """Legacy file with migrator → migrated to current version, fields preserved."""
    schema = SchemaDefinition(
        name="test_state.json",
        version=2,
        required_fields={"id", "value"},
        optional_fields={"note"},
        migrator=lambda legacy: {**legacy, "schema_version": 2},
    )
    p = tmp_path / "test_state.json"
    _write(p, _legacy_payload())

    result = read_versioned(p, schema)
    assert result is not None
    data, version = result
    assert version == 2
    # Original fields preserved (no data loss)
    assert data["id"] == "legacy"
    assert data["value"] == 7
    assert data["schema_version"] == 2


# ═════════════════════════════════════════════════════════════════════
# read_versioned — unknown version
# ═════════════════════════════════════════════════════════════════════


def test_read_unknown_version_fails_closed(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    _write(p, {"schema_version": 99, "id": "x", "value": 1})

    with pytest.raises(SchemaError, match="unsupported schema version"):
        read_versioned(p, schema)


def test_read_non_integer_version_fails_closed(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    _write(p, {"schema_version": "two", "id": "x", "value": 1})

    with pytest.raises(SchemaError, match="not an integer"):
        read_versioned(p, schema)


# ═════════════════════════════════════════════════════════════════════
# read_versioned — missing / malformed / non-dict
# ═════════════════════════════════════════════════════════════════════


def test_read_missing_file_returns_none(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "does_not_exist.json"
    assert read_versioned(p, schema) is None


def test_read_malformed_json_returns_none(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_versioned(p, schema) is None


def test_read_non_dict_json_raises(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SchemaError, match="must contain a JSON object"):
        read_versioned(p, schema)


# ═════════════════════════════════════════════════════════════════════
# write_versioned
# ═════════════════════════════════════════════════════════════════════


def test_write_versioned_adds_schema_version(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    write_versioned(p, {"id": "abc", "value": 42}, schema)

    result = read_versioned(p, schema)
    assert result is not None
    data, version = result
    assert version == 2
    assert data["schema_version"] == 2


def test_write_versioned_validates_required_fields(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    with pytest.raises(SchemaError, match="missing required fields"):
        write_versioned(p, {"id": "abc"}, schema)  # missing "value"


def test_write_versioned_atomic_and_readback(tmp_path: Path) -> None:
    schema = _make_schema()
    p = tmp_path / "test_state.json"
    write_versioned(p, {"id": "xyz", "value": 9}, schema)
    # No leftover .tmp file
    assert not any(f.suffix == ".tmp" for f in tmp_path.iterdir())
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["id"] == "xyz"


# ═════════════════════════════════════════════════════════════════════
# SchemaRegistry
# ═════════════════════════════════════════════════════════════════════


def test_schema_registry_register_and_get() -> None:
    registry = SchemaRegistry()
    schema = _make_schema()
    registry.register(schema)
    assert registry.get("test_state.json") is schema
    assert "test_state.json" in registry.names()


def test_schema_version_must_be_positive() -> None:
    with pytest.raises(ValueError, match="version must be >= 1"):
        SchemaDefinition(name="x.json", version=0, required_fields=set())
