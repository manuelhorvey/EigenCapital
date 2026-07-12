"""SQLite-backed append store for trades, attribution, shadow trades,
confidence buckets, and equity history.

Uses a thread-local connection pool to avoid creating a fresh connection
on every operation. Foreign keys are enforced. Schema migrations are
version-tracked via the ``strategy_metadata`` table.
"""

import atexit
import contextlib
import json
import logging
import sqlite3
import threading

import pandas as pd

logger = logging.getLogger("eigencapital.state_store")


class _DatabaseStore:
    """SQLite-backed append store with thread-local connection pool.

    Each thread gets its own connection, reused across operations.
    Connections are validated before use and re-created if dead.
    """

    REQUIRED_TABLES = [
        "trades",
        "attribution",
        "shadow_trades",
        "confidence_buckets",
        "equity_history",
        "equity_asset_snapshots",
    ]

    # Thread-local storage for connection reuse
    _local = threading.local()

    def __init__(self, db_path: str, checkpoint_interval: int = 50):
        self._db_path = db_path
        self._write_count = 0
        self._checkpoint_interval = checkpoint_interval
        try:
            self._init_db()
        except (RuntimeError, sqlite3.DatabaseError, OSError):
            logger.warning("DB init verification failed — retrying once: %s", db_path)
            self._init_db()
        atexit.register(self.close_all_connections)

    def _migrate_exit_reasons(self, conn) -> None:
        """One-time migration: canonicalize legacy exit reasons.

        Converts lowercase reasons to uppercase and normalizes
        legacy naming conventions. Idempotent — skipped if already applied.
        """
        with contextlib.suppress(sqlite3.OperationalError):
            conn.executescript("""
                UPDATE trades SET reason = 'SL' WHERE reason = 'sl';
                UPDATE trades SET reason = 'TP' WHERE reason = 'tp';
                UPDATE trades SET reason = 'BREAKEVEN' WHERE reason = 'breakeven';
                UPDATE trades SET reason = 'EXPIRY' WHERE reason = 'time_stop';
                UPDATE trades SET reason = 'FLIP' WHERE reason = 'signal_flip';
            """)

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                PRAGMA synchronous=NORMAL;
                PRAGMA wal_autocheckpoint=1000;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('long','short')),
                    entry REAL NOT NULL CHECK(entry > 0),
                    exit REAL CHECK(exit IS NULL OR exit > 0),
                    entry_date TEXT NOT NULL,
                    exit_date TEXT,
                    return REAL,
                    pnl REAL,
                    total_pnl REAL,
                    reason TEXT,
                    realized_r REAL,
                    bars INTEGER,
                    conf_at_entry REAL,
                    archetype_at_entry TEXT,
                    attribution_trade_id TEXT,
                    mae REAL,
                    mfe REAL,
                    mae_per_bar REAL,
                    mfe_per_bar REAL,
                    entry_slippage_bps REAL,
                    exit_slippage_bps REAL,
                    fill_qty_ratio REAL,
                    gap_fill INTEGER,
                    partial_fill INTEGER,
                    latency_bars INTEGER,
                    pred_confidence REAL,
                    pred_archetype TEXT,
                    pred_regime TEXT,
                    cycle_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS attribution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT,
                    trade_id TEXT,
                    entry_date TEXT,
                    exit_date TEXT,
                    side TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    exit_reason TEXT,
                    realized_r REAL,
                    realized_return REAL,
                    realized_pnl REAL,
                    theoretical_r REAL,
                    policy_hash TEXT,
                    archetype_version TEXT,
                    exit_archetype TEXT,
                    pred_signal TEXT,
                    pred_label INTEGER,
                    pred_confidence REAL,
                    pred_prob_long REAL,
                    pred_prob_short REAL,
                    pred_prob_neutral REAL,
                    pred_meta_proba REAL,
                    pred_regime_at_entry TEXT,
                    pred_archetype_at_entry TEXT,
                    exec_entry_type TEXT,
                    exec_deferred_bars INTEGER,
                    exec_entry_price REAL,
                    exec_mid_price_at_signal REAL,
                    exec_entry_slippage_bps REAL,
                    friction_entry_slippage_bps REAL,
                    friction_exit_slippage_bps REAL,
                    exit_mae REAL,
                    exit_mfe REAL,
                    exit_mae_per_bar REAL,
                    exit_mfe_per_bar REAL,
                    exit_realized_r REAL,
                    exit_bars_held INTEGER,
                    exit_exit_archetype TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS shadow_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT,
                    alt_label TEXT,
                    entry_date TEXT,
                    exit_date TEXT,
                    side TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    sl_price REAL,
                    tp_price REAL,
                    reason TEXT,
                    return REAL,
                    pnl REAL,
                    realized_r REAL,
                    bars_held INTEGER,
                    live_exit_reason TEXT,
                    live_realized_r REAL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS confidence_buckets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    date TEXT NOT NULL,
                    bucket_start INTEGER NOT NULL CHECK(bucket_start >= 0 AND bucket_start < 100),
                    bucket_end INTEGER NOT NULL CHECK(bucket_end > bucket_start AND bucket_end <= 100),
                    count INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
                    mean_conf REAL,
                    n_signals INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    portfolio_value REAL,
                    portfolio_return REAL,
                    drawdown REAL,
                    gross_exposure REAL,
                    net_exposure REAL,
                    vol_spike REAL,
                    var_95 REAL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS equity_asset_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equity_id INTEGER NOT NULL REFERENCES equity_history(id) ON DELETE CASCADE,
                    asset_name TEXT NOT NULL,
                    asset_value REAL NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS strategy_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            self._migrate_exit_reasons(conn)
            self._run_migrations(conn)
        self.verify()

    @staticmethod
    def _parse_version(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    def _read_db_version(self, conn) -> str:
        try:
            row = conn.execute("SELECT value FROM strategy_metadata WHERE key='db_schema_version'").fetchone()
            if row is not None:
                return str(row["value"])
        except sqlite3.OperationalError:
            pass
        return "0.0.0"

    def _write_db_version(self, conn, version: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO strategy_metadata (key, value) VALUES ('db_schema_version', ?)",
            (version,),
        )

    MIGRATIONS: dict[str, list[str]] = {
        "2.0.0": [
            "ALTER TABLE trades ADD COLUMN cycle_id INTEGER",
            "ALTER TABLE equity_history ADD COLUMN vol_spike REAL",
            "ALTER TABLE equity_history ADD COLUMN var_95 REAL",
            "CREATE INDEX IF NOT EXISTS idx_trades_asset_entry ON trades(asset, entry_date)",
            "CREATE INDEX IF NOT EXISTS idx_attribution_entry ON attribution(entry_date)",
        ],
        "3.0.0": [
            "CREATE INDEX IF NOT EXISTS idx_trades_exit_date ON trades(exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_trades_asset_exit ON trades(asset, exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_attribution_exit_date ON attribution(exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_attribution_filter ON attribution(asset, pred_archetype_at_entry, pred_regime_at_entry, exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_shadow_alt_label ON shadow_trades(alt_label, exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_shadow_exit_date ON shadow_trades(exit_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_confidence_asset_date ON confidence_buckets(asset, date)",
            "CREATE INDEX IF NOT EXISTS idx_equity_timestamp ON equity_history(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_equity_assets_equity_id ON equity_asset_snapshots(equity_id)",
            "CREATE INDEX IF NOT EXISTS idx_equity_assets_name ON equity_asset_snapshots(asset_name)",
        ],
    }

    def _run_migrations(self, conn) -> None:
        current = self._read_db_version(conn)
        target = "3.0.0"
        if self._parse_version(current) >= self._parse_version(target):
            return
        logger.info("DB schema migration: %s \u2192 %s", current, target)
        current_t = self._parse_version(current)
        versions = sorted((v for v in self.MIGRATIONS if self._parse_version(v) > current_t), key=self._parse_version)
        for version in versions:
            for stmt in self.MIGRATIONS[version]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e) or "already exists" in str(e):
                        logger.debug("Migration %s: skipped (%s)", version, e)
                    else:
                        logger.warning("Migration %s: %s (%s)", version, e, stmt)
        self._write_db_version(conn, target)

    def verify(self) -> None:
        with self._get_connection() as conn:
            existing = {
                row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        missing = [t for t in self.REQUIRED_TABLES if t not in existing]
        if missing:
            raise RuntimeError(f"Database {self._db_path} missing tables after init: {missing}")
        logger.debug("Database %s \u2014 all %d tables present", self._db_path, len(self.REQUIRED_TABLES))

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection. Validates liveness
        and that the connection points to the correct database path."""
        conn = getattr(_DatabaseStore._local, "conn", None)
        path_ok = getattr(_DatabaseStore._local, "db_path", None) == self._db_path
        if conn is not None and path_ok:
            try:
                conn.execute("SELECT 1").fetchone()
                return conn
            except (sqlite3.DatabaseError, sqlite3.ProgrammingError, AttributeError):
                logger.debug("Re-creating stale thread-local SQLite connection")
                try:
                    conn.close()
                except (sqlite3.Error, OSError):
                    pass
        # No live connection for this database path — create one
        conn = self._create_connection()
        _DatabaseStore._local.conn = conn
        _DatabaseStore._local.db_path = self._db_path
        return conn

    def _create_connection(self) -> sqlite3.Connection:
        """Create a fresh SQLite connection with WAL mode and foreign keys."""
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def checkpoint_wal(self) -> None:
        self._write_count += 1
        if self._write_count % self._checkpoint_interval == 0:
            try:
                with self._get_connection() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except (sqlite3.DatabaseError, OSError, RuntimeError) as _we:
                logger.debug("WAL checkpoint skipped: %s", _we, exc_info=True)

    def append_trade(self, trade: dict) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO trades (
                    asset, side, entry, exit, entry_date, exit_date,
                    return, pnl, total_pnl, reason, realized_r, bars,
                    conf_at_entry, archetype_at_entry, attribution_trade_id,
                    mae, mfe, mae_per_bar, mfe_per_bar,
                    entry_slippage_bps, exit_slippage_bps, fill_qty_ratio,
                    gap_fill, partial_fill, latency_bars,
                    pred_confidence, pred_archetype, pred_regime
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.get("asset"),
                    trade.get("side"),
                    trade.get("entry"),
                    trade.get("exit"),
                    str(trade.get("entry_date", "")),
                    str(trade.get("exit_date", "")),
                    trade.get("return"),
                    trade.get("pnl"),
                    trade.get("total_pnl"),
                    trade.get("reason"),
                    trade.get("realized_r"),
                    trade.get("bars"),
                    trade.get("conf_at_entry"),
                    trade.get("archetype_at_entry"),
                    trade.get("attribution_trade_id"),
                    trade.get("mae"),
                    trade.get("mfe"),
                    trade.get("mae_per_bar"),
                    trade.get("mfe_per_bar"),
                    trade.get("entry_slippage_bps"),
                    trade.get("exit_slippage_bps"),
                    trade.get("fill_qty_ratio"),
                    trade.get("gap_fill"),
                    trade.get("partial_fill"),
                    trade.get("latency_bars"),
                    trade.get("pred_confidence"),
                    trade.get("pred_archetype"),
                    trade.get("pred_regime"),
                ),
            )

    def read_trades(self, limit: int = 10) -> list:
        try:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT * FROM trades ORDER BY exit_date DESC LIMIT ?", (limit,)).fetchall()
                return [dict(r) for r in rows]
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.debug("read_trades failed: %s", _e, exc_info=True)
            return []

    def read_trades_since(self, date: str) -> pd.DataFrame:
        columns = ["asset", "side", "entry", "exit", "return", "bars", "reason", "entry_date", "exit_date"]
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT asset, side, entry, exit, return, bars, reason, entry_date, exit_date "
                    "FROM trades WHERE exit_date >= ? ORDER BY exit_date DESC",
                    (date,),
                ).fetchall()
                if not rows:
                    return pd.DataFrame(columns=columns)
                return pd.DataFrame([dict(r) for r in rows])
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.debug("read_trades_since failed: %s", _e, exc_info=True)
            return pd.DataFrame(columns=columns)

    def append_attribution(self, record_dict: dict) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO attribution (
                    asset, trade_id, entry_date, exit_date,
                    side, entry_price, exit_price, exit_reason,
                    realized_r, realized_return, realized_pnl, theoretical_r,
                    policy_hash, archetype_version, exit_archetype,
                    pred_signal, pred_label, pred_confidence,
                    pred_prob_long, pred_prob_short, pred_prob_neutral, pred_meta_proba,
                    pred_regime_at_entry, pred_archetype_at_entry,
                    exec_entry_type, exec_deferred_bars,
                    exec_entry_price, exec_mid_price_at_signal, exec_entry_slippage_bps,
                    friction_entry_slippage_bps, friction_exit_slippage_bps,
                    exit_mae, exit_mfe, exit_mae_per_bar, exit_mfe_per_bar,
                    exit_realized_r, exit_bars_held, exit_exit_archetype
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_dict.get("asset"),
                    record_dict.get("trade_id"),
                    str(record_dict.get("entry_date", "")),
                    str(record_dict.get("exit_date", "")),
                    record_dict.get("side"),
                    record_dict.get("entry_price"),
                    record_dict.get("exit_price"),
                    record_dict.get("exit_exit_reason"),
                    record_dict.get("exit_realized_r"),
                    record_dict.get("realized_return"),
                    record_dict.get("realized_pnl"),
                    record_dict.get("exit_theoretical_r"),
                    record_dict.get("policy_hash"),
                    record_dict.get("archetype_version"),
                    record_dict.get("exit_exit_archetype"),
                    record_dict.get("pred_signal"),
                    record_dict.get("pred_label"),
                    record_dict.get("pred_confidence"),
                    record_dict.get("pred_prob_long"),
                    record_dict.get("pred_prob_short"),
                    record_dict.get("pred_prob_neutral"),
                    record_dict.get("pred_meta_proba"),
                    record_dict.get("pred_regime_at_entry"),
                    record_dict.get("pred_archetype_at_entry"),
                    record_dict.get("exec_entry_type"),
                    record_dict.get("exec_deferred_bars"),
                    record_dict.get("exec_entry_price"),
                    record_dict.get("exec_mid_price_at_signal"),
                    record_dict.get("exec_entry_slippage_bps"),
                    record_dict.get("friction_entry_slippage_bps"),
                    record_dict.get("friction_exit_slippage_bps"),
                    record_dict.get("exit_mae"),
                    record_dict.get("exit_mfe"),
                    record_dict.get("exit_mae_per_bar"),
                    record_dict.get("exit_mfe_per_bar"),
                    record_dict.get("exit_realized_r"),
                    record_dict.get("exit_bars_held"),
                    record_dict.get("exit_exit_archetype"),
                ),
            )

    def read_attribution(
        self,
        limit: int = 100,
        offset: int = 0,
        archetype: str | None = None,
        regime: str | None = None,
        asset: str | None = None,
    ) -> list:
        try:
            with self._get_connection() as conn:
                query = "SELECT * FROM attribution WHERE 1=1"
                clause_strings = []
                clause_params = []
                if archetype:
                    clause_strings.append("AND pred_archetype_at_entry = ?")
                    clause_params.append(archetype)
                if regime:
                    clause_strings.append("AND pred_regime_at_entry = ?")
                    clause_params.append(regime)
                if asset:
                    clause_strings.append("AND asset = ?")
                    clause_params.append(asset)
                query += " " + " ".join(clause_strings)
                clause_params.extend([limit, offset])
                rows = conn.execute(
                    query + " ORDER BY exit_date DESC LIMIT ? OFFSET ?",
                    tuple(clause_params),
                ).fetchall()
                records = [dict(r) for r in rows]
                for rec in records:
                    if "entry_price" not in rec or rec["entry_price"] is None:
                        rec["entry_price"] = rec.get("exec_entry_price")
                    # Fix: map exit_reason column value to exit_exit_reason for backward compat
                    rec["exit_exit_reason"] = rec.get("exit_exit_reason") or rec.get("exit_reason")
                    rec["exit_theoretical_r"] = rec.get("theoretical_r")
                    if rec.get("exit_archetype") is None and rec.get("exit_exit_archetype") is not None:
                        rec["exit_archetype"] = rec["exit_exit_archetype"]
                return records
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.warning("Failed to read attribution: %s", _e, exc_info=True)
            return []

    def append_shadow_trade(self, record_dict: dict) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO shadow_trades (
                    asset, alt_label, entry_date, exit_date,
                    side, entry_price, exit_price,
                    sl_price, tp_price,
                    reason, return, pnl, realized_r, bars_held,
                    live_exit_reason, live_realized_r
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_dict.get("asset"),
                    record_dict.get("alt_label"),
                    str(record_dict.get("entry_date", "")),
                    str(record_dict.get("exit_date", "")),
                    record_dict.get("side"),
                    record_dict.get("entry_price"),
                    record_dict.get("exit_price"),
                    record_dict.get("sl_price"),
                    record_dict.get("tp_price"),
                    record_dict.get("reason"),
                    record_dict.get("return"),
                    record_dict.get("pnl"),
                    record_dict.get("realized_r"),
                    record_dict.get("bars_held"),
                    record_dict.get("live_exit_reason"),
                    record_dict.get("live_realized_r"),
                ),
            )

    def read_shadow_trades(self, limit: int = 100, offset: int = 0, alt_label: str | None = None) -> list:
        try:
            with self._get_connection() as conn:
                if alt_label:
                    rows = conn.execute(
                        "SELECT * FROM shadow_trades WHERE alt_label = ? ORDER BY exit_date DESC LIMIT ? OFFSET ?",
                        (alt_label, limit, offset),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM shadow_trades ORDER BY exit_date DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    ).fetchall()
                return [dict(r) for r in rows]
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.debug("read_shadow_trades failed: %s", _e, exc_info=True)
            return []

    def append_confidence_bucket(self, bucket: dict) -> None:
        """Append confidence bucket rows. Accepts both the legacy wide-format
        (10 count columns) and the normalized format (bucket_start, bucket_end, count).
        """
        with self._get_connection() as conn:
            # Check if this is the legacy format (has count_0_10, etc.)
            if "count_0_10" in bucket:
                # Legacy format: convert to normalized rows
                asset = bucket.get("asset")
                date = bucket.get("date")
                mean_conf = bucket.get("mean_conf", 0.0)
                n_signals = bucket.get("n_signals", 0)
                for i in range(10):
                    lo = i * 10
                    hi = (i + 1) * 10
                    count = bucket.get(f"count_{lo}_{hi}", 0)
                    if count > 0:
                        conn.execute(
                            """INSERT INTO confidence_buckets
                            (asset, date, bucket_start, bucket_end, count, mean_conf, n_signals)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (asset, date, lo, hi, count, mean_conf, n_signals),
                        )
            else:
                # Normalized format
                conn.execute(
                    """INSERT INTO confidence_buckets
                    (asset, date, bucket_start, bucket_end, count, mean_conf, n_signals)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        bucket.get("asset"),
                        bucket.get("date"),
                        bucket.get("bucket_start", 0),
                        bucket.get("bucket_end", 10),
                        bucket.get("count", 0),
                        bucket.get("mean_conf", 0.0),
                        bucket.get("n_signals", 0),
                    ),
                )

    def append_equity_history(self, record: dict) -> None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO equity_history (
                    timestamp, portfolio_value, portfolio_return, drawdown,
                    gross_exposure, net_exposure
                ) VALUES (?,?,?,?,?,?)""",
                (
                    record.get("timestamp"),
                    record.get("portfolio_value"),
                    record.get("portfolio_return"),
                    record.get("drawdown"),
                    record.get("gross_exposure"),
                    record.get("net_exposure"),
                ),
            )
            # Write per-asset values to normalized equity_asset_snapshots table
            assets_dict = record.get("assets", {})
            if isinstance(assets_dict, dict) and assets_dict:
                equity_id = cursor.lastrowid
                for asset_name, asset_value in assets_dict.items():
                    if isinstance(asset_value, (int, float)):
                        conn.execute(
                            "INSERT INTO equity_asset_snapshots (equity_id, asset_name, asset_value) VALUES (?, ?, ?)",
                            (equity_id, asset_name, asset_value),
                        )
        self.checkpoint_wal()

    def read_equity_history(self) -> list:
        """Read all equity history rows with per-asset values via a single JOIN."""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT eh.*, eav.asset_name, eav.asset_value
                    FROM equity_history eh
                    LEFT JOIN equity_asset_snapshots eav ON eh.id = eav.equity_id
                    ORDER BY eh.id ASC
                    """
                ).fetchall()
                # Assemble: group by equity_history.id
                result: list[dict] = []
                current_id = None
                current_row: dict = {}
                for r in rows:
                    row = dict(r)
                    equity_id = row["id"]
                    if equity_id != current_id:
                        if current_row:
                            result.append(current_row)
                        current_row = {
                            "id": equity_id,
                            "timestamp": row.get("timestamp"),
                            "portfolio_value": row.get("portfolio_value"),
                            "portfolio_return": row.get("portfolio_return"),
                            "drawdown": row.get("drawdown"),
                            "gross_exposure": row.get("gross_exposure"),
                            "net_exposure": row.get("net_exposure"),
                            "vol_spike": row.get("vol_spike"),
                            "var_95": row.get("var_95"),
                            "created_at": row.get("created_at"),
                            "assets": {},
                        }
                        current_id = equity_id
                    asset_name = row.get("asset_name")
                    asset_value = row.get("asset_value")
                    if asset_name is not None and asset_value is not None:
                        current_row["assets"][asset_name] = asset_value
                if current_row:
                    result.append(current_row)
                return result
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.debug("read_equity_history failed: %s", _e, exc_info=True)
            return []

    def append_equity_asset_snapshot(self, equity_id: int, asset_name: str, asset_value: float) -> None:
        """Add a single per-asset snapshot to an existing equity_history row."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO equity_asset_snapshots (equity_id, asset_name, asset_value) VALUES (?, ?, ?)",
                    (equity_id, asset_name, asset_value),
                )
        except (sqlite3.DatabaseError, OSError, RuntimeError) as _e:
            logger.debug("append_equity_asset_snapshot failed: %s", _e, exc_info=True)

    def prune_trades(self, cutoff_date: str, apply: bool = False) -> dict:
        """Delete trades with exit_date older than *cutoff_date* (ISO format).

        Returns stats dict with total, kept, pruned counts.
        """
        try:
            with self._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                to_delete = conn.execute(
                    "SELECT id FROM trades WHERE exit_date < ?", (cutoff_date,)
                ).fetchall()
                pruned = len(to_delete)
                if pruned > 0 and apply:
                    ids = tuple(r["id"] for r in to_delete)
                    conn.execute(
                        f"DELETE FROM trades WHERE id IN ({','.join('?' * len(ids))})", ids
                    )
                kept = total - pruned
                return {"total": total, "kept": kept, "pruned": pruned}
        except (sqlite3.DatabaseError, OSError, RuntimeError) as e:
            logger.warning("prune_trades failed: %s", e)
            return {"error": str(e)}

    def prune_attribution(self, cutoff_date: str, apply: bool = False) -> dict:
        """Delete attribution rows with exit_date older than *cutoff_date* (ISO format).

        Returns stats dict with total, kept, pruned counts.
        """
        try:
            with self._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM attribution").fetchone()[0]
                to_delete = conn.execute(
                    "SELECT id FROM attribution WHERE exit_date < ?", (cutoff_date,)
                ).fetchall()
                pruned = len(to_delete)
                if pruned > 0 and apply:
                    ids = tuple(r["id"] for r in to_delete)
                    conn.execute(
                        f"DELETE FROM attribution WHERE id IN ({','.join('?' * len(ids))})", ids
                    )
                kept = total - pruned
                return {"total": total, "kept": kept, "pruned": pruned}
        except (sqlite3.DatabaseError, OSError, RuntimeError) as e:
            logger.warning("prune_attribution failed: %s", e)
            return {"error": str(e)}

    def prune_equity_history(self, cutoff_date: str, apply: bool = False) -> dict:
        """Delete equity_history rows with timestamp older than *cutoff_date* (ISO format).

        Related rows in equity_asset_snapshots are deleted via ON DELETE CASCADE.
        Returns stats dict with total, kept, pruned counts.
        """
        try:
            with self._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM equity_history").fetchone()[0]
                to_delete = conn.execute(
                    "SELECT id FROM equity_history WHERE timestamp < ?", (cutoff_date,)
                ).fetchall()
                pruned = len(to_delete)
                if pruned > 0 and apply:
                    ids = tuple(r["id"] for r in to_delete)
                    conn.execute(
                        f"DELETE FROM equity_history WHERE id IN ({','.join('?' * len(ids))})", ids
                    )
                kept = total - pruned
                return {"total": total, "kept": kept, "pruned": pruned}
        except (sqlite3.DatabaseError, OSError, RuntimeError) as e:
            logger.warning("prune_equity_history failed: %s", e)
            return {"error": str(e)}

    def prune_all(self, cutoff_date: str, apply: bool = False) -> dict:
        """Prune all time-series tables (trades, attribution, equity_history).

        Convenience method that calls all three prune methods and aggregates
        results. Does NOT vacuum — caller should vacuum after a large prune.
        """
        return {
            "trades": self.prune_trades(cutoff_date, apply=apply),
            "attribution": self.prune_attribution(cutoff_date, apply=apply),
            "equity_history": self.prune_equity_history(cutoff_date, apply=apply),
        }

    def close_all_connections(self) -> None:
        """Close the thread-local connection if it exists. Call for cleanup."""
        conn = getattr(_DatabaseStore._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except (sqlite3.Error, OSError):
                pass
            _DatabaseStore._local.conn = None
