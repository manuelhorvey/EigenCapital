"""ProvenanceStore — persistence layer for Decision Provenance.

Provides a storage interface and SQLite implementation for writing and
querying decision provenance records.

Storage strategy:
    - Each context is stored as a JSON column (using EigenCapitalJSONEncoder)
    - Metadata columns (cycle_id, asset, decision, etc.) are indexed for
      efficient querying without deserializing the full JSON payload.
    - Schema versioning supports forward compatibility as the provenance
      domain model evolves.

Usage::

    from eigencapital.domain.provenance.provenance_store import (
        ProvenanceStore,
        SqliteProvenanceStore,
    )
    store: ProvenanceStore = SqliteProvenanceStore("data/provenance.db")
    store.initialize()
    store.store(provenance)
    records = store.query(asset="GBPJPY", limit=50)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from eigencapital.domain.provenance.decision_provenance import DecisionProvenance, PROVENANCE_SCHEMA_VERSION

logger = logging.getLogger("eigencapital.provenance.store")


def compute_config_hash(config_dir: str | Path = "configs") -> str:
    """Compute a deterministic hash of the active configuration tree.

    Scans all YAML files under *config_dir*, canonicalizes their contents
    (sorted keys, stripped whitespace), and produces a single SHA-256 hex
    digest.  This gives a fingerprint that changes iff any config file
    changes.

    Args:
        config_dir: Root path of the configuration directory tree.

    Returns:
        64-character hex SHA-256 hash string.
    """
    config_root = Path(config_dir)
    if not config_root.is_dir():
        return "no_config_dir"

    hasher = hashlib.sha256()
    # Walk all .yaml files in sorted order for determinism
    yaml_files = sorted(config_root.rglob("*.yaml"))
    for fpath in yaml_files:
        try:
            content = fpath.read_bytes()
            hasher.update(content)
        except OSError:
            continue
    return hasher.hexdigest()


def compute_git_hash() -> str:
    """Return the current Git commit hash, or empty string if unavailable.

    Uses ``.git/HEAD`` directly to avoid a subprocess call.
    """
    try:
        git_dir = Path(".git")
        head_path = git_dir / "HEAD"
        if not head_path.is_file():
            return ""
        ref = head_path.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = git_dir / ref[5:]
            if ref_path.is_file():
                return ref_path.read_text().strip()[:40]
        return ref[:40]
    except OSError:
        return ""


class ProvenanceStore(ABC):
    """Abstract storage interface for decision provenance records."""

    @abstractmethod
    def initialize(self) -> None:
        """Create schema and indexes if they do not exist."""

    @abstractmethod
    def store(self, provenance: DecisionProvenance) -> None:
        """Persist a single decision provenance record."""

    @abstractmethod
    def query(
        self,
        asset: str | None = None,
        cycle_id: int | None = None,
        decision_type: str | None = None,
        model_hash: str | None = None,
        feature_hash: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecisionProvenance]: ...

    @abstractmethod
    def get_by_decision_id(self, decision_id: str) -> DecisionProvenance | None: ...

    @abstractmethod
    def count(self) -> int: ...


class SqliteProvenanceStore(ProvenanceStore):
    """SQLite-backed implementation of ProvenanceStore.

    Thread-safe via thread-local connections (same pattern as
    ``_DatabaseStore`` in ``paper_trading.state.database_store``).
    """

    _local = threading.local()

    def __init__(self, db_path: str):
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._checkpoint_count = 0

    # ── Schema ─────────────────────────────────────────────────────────

    SCHEMA_SQL = f"""
        CREATE TABLE IF NOT EXISTS decision_provenance (
            decision_id TEXT PRIMARY KEY,
            lineage_id TEXT NOT NULL,
            provenance_schema_version INTEGER NOT NULL DEFAULT {PROVENANCE_SCHEMA_VERSION},
            cycle_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            decision_timestamp TEXT NOT NULL,
            decision_type TEXT NOT NULL DEFAULT 'LIVE',
            git_hash TEXT,
            config_hash TEXT,
            model_version TEXT,
            model_hash TEXT,
            feature_hash TEXT,
            decision TEXT,
            market_context TEXT,
            feature_context TEXT,
            model_context TEXT,
            portfolio_context TEXT,
            execution_context TEXT,
            decision_trace TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_dp_timestamp ON decision_provenance(decision_timestamp);
        CREATE INDEX IF NOT EXISTS idx_dp_asset ON decision_provenance(asset);
        CREATE INDEX IF NOT EXISTS idx_dp_cycle ON decision_provenance(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_dp_model ON decision_provenance(model_hash);
        CREATE INDEX IF NOT EXISTS idx_dp_feature ON decision_provenance(feature_hash);
        CREATE INDEX IF NOT EXISTS idx_dp_decision ON decision_provenance(decision);
        CREATE INDEX IF NOT EXISTS idx_dp_type ON decision_provenance(decision_type);
        CREATE INDEX IF NOT EXISTS idx_dp_lineage ON decision_provenance(lineage_id);
    """

    # ── Connection management ──────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(SqliteProvenanceStore._local, "conn", None)
        path_ok = getattr(SqliteProvenanceStore._local, "db_path", None) == self._db_path
        if conn is not None and path_ok:
            try:
                conn.execute("SELECT 1").fetchone()
                return conn
            except (sqlite3.DatabaseError, sqlite3.ProgrammingError):
                with contextlib.suppress(sqlite3.Error, OSError):
                    conn.close()
        conn = self._create_connection()
        SqliteProvenanceStore._local.conn = conn
        SqliteProvenanceStore._local.db_path = self._db_path
        return conn

    def _create_connection(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def close(self) -> None:
        conn = getattr(SqliteProvenanceStore._local, "conn", None)
        if conn is not None:
            with contextlib.suppress(sqlite3.Error, OSError):
                conn.close()
            SqliteProvenanceStore._local.conn = None

    # ── ProvenanceStore interface ──────────────────────────────────────

    def initialize(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA_SQL)

    def store(self, provenance: DecisionProvenance) -> None:
        with self._get_connection() as conn:
            did = provenance.decision_id
            merged = provenance.to_dict()
            conn.execute(
                """INSERT OR REPLACE INTO decision_provenance (
                    decision_id, lineage_id, provenance_schema_version,
                    cycle_id, asset, decision_timestamp, decision_type,
                    git_hash, config_hash,
                    model_version, model_hash, feature_hash, decision,
                    market_context, feature_context, model_context,
                    portfolio_context, execution_context, decision_trace
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    did.decision_id,
                    did.lineage_id,
                    provenance.schema_version,
                    provenance.cycle_id,
                    provenance.asset,
                    provenance.decision_timestamp,
                    provenance.decision_type,
                    provenance.git_hash,
                    provenance.config_hash,
                    (merged.get("model") or {}).get("model_version", ""),
                    (merged.get("model") or {}).get("model_hash", ""),
                    (merged.get("features") or {}).get("feature_hash", ""),
                    (merged.get("decision") or {}).get("final_signal", ""),
                    json.dumps(merged.get("market") or {}, cls=EigenCapitalJSONEncoder),
                    json.dumps(merged.get("features") or {}, cls=EigenCapitalJSONEncoder),
                    json.dumps(merged.get("model") or {}, cls=EigenCapitalJSONEncoder),
                    json.dumps(merged.get("portfolio") or {}, cls=EigenCapitalJSONEncoder),
                    json.dumps(merged.get("runtime") or {}, cls=EigenCapitalJSONEncoder),
                    json.dumps(merged.get("decision") or {}, cls=EigenCapitalJSONEncoder),
                ),
            )
        self._checkpoint_count += 1
        if self._checkpoint_count % 100 == 0:
            with contextlib.suppress(sqlite3.DatabaseError, OSError):
                with self._get_connection() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def query(
        self,
        asset: str | None = None,
        cycle_id: int | None = None,
        decision_type: str | None = None,
        model_hash: str | None = None,
        feature_hash: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecisionProvenance]:
        clauses: list[str] = ["1=1"]
        params: list[Any] = []
        if asset is not None:
            clauses.append("asset = ?")
            params.append(asset)
        if cycle_id is not None:
            clauses.append("cycle_id = ?")
            params.append(cycle_id)
        if decision_type is not None:
            clauses.append("decision_type = ?")
            params.append(decision_type)
        if model_hash is not None:
            clauses.append("model_hash = ?")
            params.append(model_hash)
        if feature_hash is not None:
            clauses.append("feature_hash = ?")
            params.append(feature_hash)
        if since is not None:
            clauses.append("decision_timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("decision_timestamp <= ?")
            params.append(until)
        params.extend([limit, offset])
        sql = (
            "SELECT * FROM decision_provenance WHERE "
            + " AND ".join(clauses)
            + " ORDER BY decision_timestamp DESC LIMIT ? OFFSET ?"
        )
        try:
            with self._get_connection() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [self._row_to_provenance(r) for r in rows]
        except (sqlite3.DatabaseError, OSError, RuntimeError) as e:
            logger.warning("Decision provenance query failed: %s", e, exc_info=True)
            return []

    def get_by_decision_id(self, decision_id: str) -> DecisionProvenance | None:
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM decision_provenance WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()
                return self._row_to_provenance(row) if row else None
        except (sqlite3.DatabaseError, OSError, RuntimeError) as e:
            logger.warning("get_by_decision_id failed: %s", e, exc_info=True)
            return None

    def count(self) -> int:
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM decision_provenance").fetchone()
                return row["cnt"] if row else 0
        except (sqlite3.DatabaseError, OSError, RuntimeError):
            return 0

    # ── Maintenance operations ──────────────────────────────────────────

    def prune(self, before: str) -> int:
        """Delete records older than a given timestamp.

        Args:
            before: ISO-8601 timestamp. Records with ``decision_timestamp``
                strictly less than this value are removed.

        Returns:
            Number of records deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM decision_provenance WHERE decision_timestamp < ?",
                (before,),
            )
            return cursor.rowcount

    def health(self) -> dict:
        """Return a health-check dict for the store.

        Returns:
            Dict with keys::
                - status: ``"ok"`` or ``"error"``
                - total_records: int
                - db_size_bytes: int
                - oldest_timestamp: str or None
                - newest_timestamp: str or None
                - error: str (only present if unhealthy)
        """
        result: dict = {"status": "ok"}
        try:
            with self._get_connection() as conn:
                count = conn.execute("SELECT COUNT(*) AS cnt FROM decision_provenance").fetchone()["cnt"]
                result["total_records"] = count

                oldest = conn.execute(
                    "SELECT decision_timestamp FROM decision_provenance ORDER BY decision_timestamp ASC LIMIT 1"
                ).fetchone()
                result["oldest_timestamp"] = oldest["decision_timestamp"] if oldest else None

                newest = conn.execute(
                    "SELECT decision_timestamp FROM decision_provenance ORDER BY decision_timestamp DESC LIMIT 1"
                ).fetchone()
                result["newest_timestamp"] = newest["decision_timestamp"] if newest else None

            try:
                result["db_size_bytes"] = Path(self._db_path).stat().st_size
            except OSError:
                result["db_size_bytes"] = -1
        except (sqlite3.DatabaseError, OSError) as e:
            result["status"] = "error"
            result["error"] = str(e)
        return result

    def count_by_asset(self) -> dict[str, int]:
        """Return record counts grouped by asset."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT asset, COUNT(*) AS cnt FROM decision_provenance GROUP BY asset ORDER BY cnt DESC"
            ).fetchall()
            return {r["asset"]: r["cnt"] for r in rows}

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_provenance(row: sqlite3.Row) -> DecisionProvenance:
        def _load(col: str) -> dict:
            raw = row[col]
            if raw is None:
                return {}
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                return {}

        return DecisionProvenance.from_dict(
            {
                "decision_id": {
                    "decision_id": row["decision_id"],
                    "lineage_id": row["lineage_id"],
                },
                "schema_version": row["provenance_schema_version"],
                "cycle_id": row["cycle_id"],
                "asset": row["asset"],
                "decision_timestamp": row["decision_timestamp"],
                "decision_type": row["decision_type"],
                "git_hash": row["git_hash"] or "",
                "config_hash": row["config_hash"] or "",
                "market": _load("market_context"),
                "features": _load("feature_context"),
                "model": _load("model_context"),
                "portfolio": _load("portfolio_context"),
                "runtime": _load("execution_context"),
                "decision": _load("decision_trace"),
            }
        )
