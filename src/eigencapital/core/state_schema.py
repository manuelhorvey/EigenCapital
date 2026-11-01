"""State-file schema versioning framework.

Provides explicit schema versions for operational state files (e.g.
``daily_baseline.json``, ``supervisor_state.json``), with:

* Explicit ``schema_version`` on every written file.
* Validation of required fields on read.
* Backward-compatible handling of legacy (unversioned) files.
* Safe, explicit migration of legacy files to the current version.
* Fail-closed rejection of unknown schema versions (never silently
  interpreted).
* Atomic writes with no silent data loss.

Design principles:
- A file without ``schema_version`` is treated as legacy version 0. If a
  migrator is registered, it is applied to produce current-version data; the
  original legacy fields are preserved (no data loss). If no migrator is
  registered, the legacy data is returned as-is (passthrough).
- A file with an unknown ``schema_version`` (not 0, not the current version)
  is rejected with :class:`SchemaError` — it is never silently interpreted.
- Malformed JSON / unreadable files are handled safely (return ``None`` or
  raise :class:`SchemaError` depending on caller preference).
- Writes are atomic (temp file + os.replace) and always include the current
  ``schema_version``.

Usage:
    from eigencapital.core.state_schema import (
        SchemaDefinition, SchemaRegistry, SchemaError,
        read_versioned, write_versioned,
    )

    registry = SchemaRegistry()
    registry.register(SchemaDefinition(
        name="daily_baseline.json",
        version=1,
        required_fields={"date_str", "equity", "timestamp_utc"},
    ))

    data, version = read_versioned(path, registry.get("daily_baseline.json"))
    write_versioned(path, {"date_str": ..., "equity": ...},
                    registry.get("daily_baseline.json"))
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class SchemaError(Exception):
    """Raised when a state file's schema version is unknown, unsupported, or
    fails validation."""


@dataclass(frozen=True)
class SchemaDefinition:
    """Describes one versioned state-file schema.

    Attributes:
        name: Human-readable file name (used in error messages).
        version: Current schema version (positive int). Version 0 is reserved
            for legacy (unversioned) files.
        required_fields: Field names that must be present in current-version
            data.
        optional_fields: Field names that are allowed but not required.
        validator: Optional callable ``validator(data)`` that raises
            :class:`SchemaError` on invalid data. Runs after version match.
        migrator: Optional callable ``migrator(legacy_data) -> current_data``
            that converts a legacy (version 0) payload into the current
            version. Must preserve all original fields (no data loss) and set
            ``schema_version`` to the current version.
    """

    name: str
    version: int
    required_fields: frozenset
    optional_fields: frozenset = frozenset()
    validator: Callable[[dict], None] | None = None
    migrator: Callable[[dict], dict] | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("schema version must be >= 1")
        object.__setattr__(
            self, "required_fields", frozenset(self.required_fields)
        )
        object.__setattr__(
            self, "optional_fields", frozenset(self.optional_fields)
        )


class SchemaRegistry:
    """Registry mapping state-file names to their schema definitions."""

    def __init__(self) -> None:
        self._schemas: dict[str, SchemaDefinition] = {}

    def register(self, schema: SchemaDefinition) -> None:
        self._schemas[schema.name] = schema

    def get(self, name: str) -> SchemaDefinition | None:
        return self._schemas.get(name)

    def names(self) -> list[str]:
        return sorted(self._schemas.keys())


# Legacy (unversioned) files are treated as schema version 0.
LEGACY_VERSION = 0


def _read_json_file(path: Path) -> dict | None:
    """Read a JSON file, returning None on any read/parse error."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomically write JSON to ``path`` via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except OSError:
        # Best effort — do not crash the caller; clean up temp file.
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass


def _validate_fields(data: dict, schema: SchemaDefinition) -> None:
    missing = schema.required_fields - set(data.keys())
    if missing:
        raise SchemaError(
            f"{schema.name}: missing required fields {sorted(missing)} "
            f"(schema v{schema.version})"
        )
    unknown = set(data.keys()) - schema.required_fields - schema.optional_fields - {
        "schema_version",
    }
    if unknown:
        raise SchemaError(
            f"{schema.name}: unexpected fields {sorted(unknown)} "
            f"(schema v{schema.version})"
        )


def read_versioned(
    path: Path, schema: SchemaDefinition | None
) -> tuple[dict, int] | None:
    """Read a versioned state file.

    Returns ``(data, version)`` on success, or ``None`` if the file is
    missing or unreadable (malformed JSON).

    Raises :class:`SchemaError` if the schema version is unknown or the data
    fails validation.

    Legacy (unversioned) files are treated as version 0. If the schema has a
    migrator, it is applied and migrated data is returned at the current
    version. Without a migrator, legacy data is returned as-is at version 0
    (passthrough — no data loss).
    """
    data = _read_json_file(path)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: state file must contain a JSON object")

    raw_version = data.get("schema_version")

    if raw_version is None:
        return _apply_legacy(data, schema, path)

    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        raise SchemaError(f"{path}: schema_version is not an integer: {raw_version!r}")

    if version == LEGACY_VERSION:
        return _apply_legacy(data, schema, path)

    if schema is None:
        return data, version

    if version == schema.version:
        _validate_fields(data, schema)
        if schema.validator is not None:
            schema.validator(data)
        return data, version

    raise SchemaError(
        f"{path}: unsupported schema version {version} for {schema.name}; "
        f"expected {schema.version} or legacy {LEGACY_VERSION}"
    )


def _apply_legacy(
    data: dict, schema: SchemaDefinition | None, path: Path
) -> tuple[dict, int]:
    """Handle a legacy (unversioned or version-0) state file.

    If a migrator is registered, apply it and return current-version data
    (original fields preserved — no data loss). Without a migrator, return
    the data as-is at version 0 (passthrough).
    """
    if schema is None:
        return data, LEGACY_VERSION
    if schema.migrator is not None:
        migrated = schema.migrator(dict(data))
        migrated["schema_version"] = schema.version
        _validate_fields(migrated, schema)
        if schema.validator is not None:
            schema.validator(migrated)
        return migrated, schema.version
    return data, LEGACY_VERSION


def write_versioned(
    path: Path, data: dict, schema: SchemaDefinition | None = None
) -> None:
    """Atomically write a state file with the current schema version.

    If a schema is registered, ``schema_version`` is set to the current
    version and validation runs before writing. Without a schema, the data
    is written unchanged (no version field added).
    """
    payload = dict(data)
    if schema is not None:
        payload["schema_version"] = schema.version
        _validate_fields(payload, schema)
        if schema.validator is not None:
            schema.validator(payload)
    _atomic_write_json(path, payload)
