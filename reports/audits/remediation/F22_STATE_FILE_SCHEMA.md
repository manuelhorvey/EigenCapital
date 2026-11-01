# F-22 — Operational State File Schema/Versioning

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** pending
**Severity:** Medium · **Phase:** P2
**Date:** 2026-11-01

---

## 1. Finding

Operational state files under `reports/r4_loop/` (`runtime_state.json`,
`daily_baseline.json`, `supervisor_state.json`, `last_equity.json`,
`last_health.json`, `rebalance_policy_state.json`, etc.) carried no schema
version; readers used `.get()` defaults, so malformed, legacy, or
differently-versioned files could be silently misinterpreted.

## 2. Correction

A general-purpose, isolated schema-versioning framework was added:

**`src/eigencapital/core/state_schema.py`** (new):

- `SchemaDefinition(name, version, required_fields, optional_fields,
  validator, migrator)` — declares one schema version per file.
- `SchemaRegistry` — maps file names to schemas.
- `read_versioned(path, schema)` — returns `(data, version)`; returns `None`
  for missing/unreadable/malformed files; raises `SchemaError` on unknown
  schema version or failed validation (fail closed — never silently
  interpreted). Legacy (unversioned / version-0) files are treated as
  version 0: if a migrator is registered it is applied (original fields
  preserved — no data loss); otherwise passthrough at version 0.
- `write_versioned(path, data, schema)` — atomically writes (temp file +
  `os.replace`) with `schema_version` set and validation run first.
- Unknown versions fail closed (`SchemaError`); no silent data loss, no
  destructive migration.

**Wired into two state files:**

- `src/eigencapital/live/daily_loss.py` — `daily_baseline.json` is now
  schema v1. Writing adds `schema_version=1`; legacy unversioned baselines
  are migrated (fields preserved, hash re-verified by caller); unknown
  versions fail closed (tracker blocks).
- `src/eigencapital/live/supervisor.py` — `supervisor_state.json` is now
  schema v1. Writing adds `schema_version=1`; unknown versions fail closed.

## 3. Backward-compatibility strategy

- Legacy (unversioned) files are version 0. With a migrator, they are
  migrated in place on read (original fields preserved). Without a
  migrator, they pass through unchanged at version 0.
- Migration never deletes or renames fields; it only adds `schema_version`.
- Unknown (non-0, non-current) versions are rejected with `SchemaError`
  — never interpreted.
- Malformed JSON / unreadable files return `None` (caller decides fail
  closed or fallback).

## 4. Files changed

- `src/eigencapital/core/state_schema.py` (new)
- `src/eigencapital/live/daily_loss.py`
- `src/eigencapital/live/supervisor.py`
- `tests/unit/core/test_state_schema.py` (new)
- `tests/unit/live/test_daily_loss_schema.py` (new)

## 5. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/core/test_state_schema.py -q` | **15 passed** |
| `pytest tests/unit/live/test_daily_loss_schema.py -q` | **11 passed** |
| `pytest tests/unit/live tests/unit/core -q` | **779 passed** |

Coverage: current-version read/write, legacy passthrough, legacy migration
(no data loss), unknown-version rejection, non-integer version rejection,
missing/malformed/non-dict file handling, field validation, atomic write
(no leftover temp), registry register/get, tracker writes schema version,
tracker reads+migrates legacy baseline, tracker unknown-version fail
closed, tracker valid legacy hash trusted.

## 6. Compatibility guarantees

- Readers that consume `DailyBaseline`/`SupervisorState` dataclasses see no
  change — `schema_version` is metadata only.
- Legacy unversioned `daily_baseline.json`/`supervisor_state.json` continue
  to load (migrated on read) until explicitly re-written at v1.
- Files written after this change are v1 and carry `schema_version`.
- Downgrade: a v1 file read by older code (no schema awareness) ignores the
  extra `schema_version` key — backward compatible.

## 7. Scope note

`state_schema.py` is general-purpose and can be applied to additional state
files (`last_health.json`, `rebalance_policy_state.json`, etc.) as a
follow-up. This unit wires `daily_baseline.json` and `supervisor_state.json`
because they feed the daily-loss and supervisor safety paths. The broader
state-file enumeration (F-06 path unification, one documented owner per
file) remains tracked separately.

## 8. What this does not establish

- Independent review has not occurred.
- Not every `reports/r4_loop/*` file is versioned yet; the framework is
  ready for the remaining files.
- Capital-readiness decision unchanged.

## 9. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
