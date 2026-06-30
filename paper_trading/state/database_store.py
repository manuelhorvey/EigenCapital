import contextlib
import json
import logging
import sqlite3

import pandas as pd

logger = logging.getLogger("quorrin.state_store")


class _DatabaseStore:
    """SQLite-backed append store for trades, attribution, shadow trades,
    confidence buckets, and equity history."""

    REQUIRED_TABLES = [
        "trades",
        "attribution",
        "shadow_trades",
        "confidence_buckets",
        "equity_history",
    ]

    def __init__(self, db_path: str, checkpoint_interval: int = 50):
        self._db_path = db_path
        self._write_count = 0
        self._checkpoint_interval = checkpoint_interval
        try:
            self._init_db()
        except RuntimeError:
            logger.warning("DB init verification failed — retrying once: %s", db_path)
            self._init_db()

    def _migrate_exit_reasons(self, conn) -> None:
        """One-time migration: canonicalize legacy lowercase exit reasons."""
        with contextlib.suppress(Exception):
            conn.executescript("""
                UPDATE trades SET reason = 'SL' WHERE reason = 'sl';
                UPDATE trades SET reason = 'TP' WHERE reason = 'tp';
                UPDATE trades SET reason = 'BREAKEVEN' WHERE reason = 'breakeven';
                UPDATE trades SET reason = 'EXPIRY' WHERE reason = 'time_stop';
                UPDATE trades SET reason = 'FLIP' WHERE reason = 'signal_flip';
            """)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA synchronous=NORMAL;
                PRAGMA wal_autocheckpoint=1000;

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    side TEXT,
                    entry REAL,
                    exit REAL,
                    entry_date TEXT,
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
                    stop_loss REAL,
                    take_profit REAL,
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
                    asset TEXT,
                    date TEXT,
                    count_0_10 INTEGER DEFAULT 0,
                    count_10_20 INTEGER DEFAULT 0,
                    count_20_30 INTEGER DEFAULT 0,
                    count_30_40 INTEGER DEFAULT 0,
                    count_40_50 INTEGER DEFAULT 0,
                    count_50_60 INTEGER DEFAULT 0,
                    count_60_70 INTEGER DEFAULT 0,
                    count_70_80 INTEGER DEFAULT 0,
                    count_80_90 INTEGER DEFAULT 0,
                    count_90_100 INTEGER DEFAULT 0,
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
                    assets TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS strategy_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE equity_history ADD COLUMN assets TEXT")
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
    }

    def _run_migrations(self, conn) -> None:
        current = self._read_db_version(conn)
        target = "2.0.0"
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
        with self._connect() as conn:
            existing = {
                row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        missing = [t for t in self.REQUIRED_TABLES if t not in existing]
        if missing:
            raise RuntimeError(f"Database {self._db_path} missing tables after init: {missing}")
        logger.debug("Database %s \u2014 all %d tables present", self._db_path, len(self.REQUIRED_TABLES))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def checkpoint_wal(self) -> None:
        self._write_count += 1
        if self._write_count % self._checkpoint_interval == 0:
            try:
                with self._connect() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                logger.debug("WAL checkpoint skipped: %s", e)

    def append_trade(self, trade: dict) -> None:
        with self._connect() as conn:
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
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM trades ORDER BY exit_date DESC LIMIT ?", (limit,)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def read_trades_since(self, date: str) -> pd.DataFrame:
        columns = ["asset", "side", "entry", "exit", "return", "bars", "reason", "entry_date", "exit_date"]
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT asset, side, entry, exit, return, bars, reason, entry_date, exit_date "
                    "FROM trades WHERE exit_date >= ? ORDER BY exit_date DESC",
                    (date,),
                ).fetchall()
                if not rows:
                    return pd.DataFrame(columns=columns)
                return pd.DataFrame([dict(r) for r in rows])
        except Exception:
            return pd.DataFrame(columns=columns)

    def append_attribution(self, record_dict: dict) -> None:
        with self._connect() as conn:
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
                    record_dict.get("exit_reason"),
                    record_dict.get("realized_r"),
                    record_dict.get("realized_return"),
                    record_dict.get("realized_pnl"),
                    record_dict.get("theoretical_r"),
                    record_dict.get("policy_hash"),
                    record_dict.get("archetype_version"),
                    record_dict.get("exit_archetype"),
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
            with self._connect() as conn:
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
                return records
        except Exception as e:
            logger.warning("Failed to read attribution: %s", e)
            return []

    def append_shadow_trade(self, record_dict: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO shadow_trades (
                    asset, alt_label, entry_date, exit_date,
                    side, entry_price, exit_price,
                    sl_price, tp_price, stop_loss, take_profit,
                    reason, return, pnl, realized_r, bars_held,
                    live_exit_reason, live_realized_r
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    record_dict.get("stop_loss"),
                    record_dict.get("take_profit"),
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
            with self._connect() as conn:
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
        except Exception:
            return []

    def append_confidence_bucket(self, bucket: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO confidence_buckets (
                    asset, date,
                    count_0_10, count_10_20, count_20_30, count_30_40,
                    count_40_50, count_50_60, count_60_70, count_70_80,
                    count_80_90, count_90_100,
                    mean_conf, n_signals
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bucket.get("asset"),
                    bucket.get("date"),
                    bucket.get("count_0_10", 0),
                    bucket.get("count_10_20", 0),
                    bucket.get("count_20_30", 0),
                    bucket.get("count_30_40", 0),
                    bucket.get("count_40_50", 0),
                    bucket.get("count_50_60", 0),
                    bucket.get("count_60_70", 0),
                    bucket.get("count_70_80", 0),
                    bucket.get("count_80_90", 0),
                    bucket.get("count_90_100", 0),
                    bucket.get("mean_conf", 0.0),
                    bucket.get("n_signals", 0),
                ),
            )

    def append_equity_history(self, record: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO equity_history (
                    timestamp, portfolio_value, portfolio_return, drawdown,
                    gross_exposure, net_exposure, assets
                ) VALUES (?,?,?,?,?,?,?)""",
                (
                    record.get("timestamp"),
                    record.get("portfolio_value"),
                    record.get("portfolio_return"),
                    record.get("drawdown"),
                    record.get("gross_exposure"),
                    record.get("net_exposure"),
                    json.dumps(record.get("assets", {})),
                ),
            )

    def read_equity_history(self) -> list:
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM equity_history ORDER BY id ASC").fetchall()
                result = []
                for r in rows:
                    row = dict(r)
                    if isinstance(row.get("assets"), str):
                        row["assets"] = json.loads(row["assets"])
                    elif row.get("assets") is None:
                        row["assets"] = {}
                    result.append(row)
                return result
        except Exception:
            return []
