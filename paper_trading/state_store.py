import json
import logging
import math
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

logger = logging.getLogger("quantforge.state_store")

ET = pytz.timezone("US/Eastern")

SCHEMA_VERSION = "1.0.0"


@dataclass
class EngineSnapshot:
    schema_version: str = SCHEMA_VERSION
    timestamp: str = ""
    portfolio: dict | None = None
    assets: dict | None = None
    open_positions: dict | None = None
    engine_status: dict | None = None
    halt_conditions: dict | None = None
    risk_signals: dict | None = None
    shadow_actions: dict | None = None
    risk_parity: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSnapshot":
        return cls(
            schema_version=d.get("schema_version", "0.0.0"),
            timestamp=d.get("timestamp", ""),
            portfolio=d.get("portfolio"),
            assets=d.get("assets"),
            open_positions=d.get("open_positions"),
            engine_status=d.get("engine_status"),
            halt_conditions=d.get("halt_conditions"),
            risk_signals=d.get("risk_signals"),
            shadow_actions=d.get("shadow_actions"),
            risk_parity=d.get("risk_parity"),
        )


_SKIP_JOURNAL = object()


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    elif isinstance(obj, (float, np.floating)) and (math.isinf(obj) or math.isnan(obj)):
        return None
    return obj


def _atomic_write_json(path: str, data: dict) -> None:
    """Atomic JSON write using temp file + os.replace (atomic on POSIX)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, path)


# ═══════════════════════════════════════════════════════════════════════
# DatabaseStore — SQLite persistence
# ═══════════════════════════════════════════════════════════════════════

class _DatabaseStore:
    """SQLite-backed append store for trades, attribution, shadow trades,
    confidence buckets, and equity history."""

    def __init__(self, db_path: str, checkpoint_interval: int = 50):
        self._db_path = db_path
        self._write_count = 0
        self._checkpoint_interval = checkpoint_interval
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
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
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)

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

    # ── Trades ─────────────────────────────────────────────────────

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

    # ── Attribution ────────────────────────────────────────────────

    def append_attribution(self, record_dict: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO attribution (
                    asset, trade_id, entry_date, exit_date,
                    side, exit_price, exit_reason,
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
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_dict.get("asset"),
                    record_dict.get("trade_id"),
                    str(record_dict.get("entry_date", "")),
                    str(record_dict.get("exit_date", "")),
                    record_dict.get("side"),
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
                where_parts = []
                params = []
                if archetype:
                    where_parts.append("pred_archetype_at_entry = ?")
                    params.append(archetype)
                if regime:
                    where_parts.append("pred_regime_at_entry = ?")
                    params.append(regime)
                if asset:
                    where_parts.append("asset = ?")
                    params.append(asset)
                where_sql = " AND ".join(where_parts) if where_parts else "1=1"
                params.extend([limit, offset])
                rows = conn.execute(
                    f"SELECT * FROM attribution WHERE {where_sql} ORDER BY exit_date DESC LIMIT ? OFFSET ?",
                    tuple(params),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to read attribution: %s", e)
            return []

    # ── Shadow trades ──────────────────────────────────────────────

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

    # ── Confidence buckets ─────────────────────────────────────────

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

    # ── Equity history ─────────────────────────────────────────────

    def append_equity_history(self, record: dict) -> None:
        with self._connect() as conn:
            conn.execute(
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

    def read_equity_history(self) -> list:
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM equity_history ORDER BY id ASC").fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════════════
# SnapshotManager — JSON state snapshot with TTL cache
# ═══════════════════════════════════════════════════════════════════════

class _SnapshotManager:
    """JSON state snapshot save/load with monotonic-time TTL cache."""

    def __init__(self, state_path: str, cache_ttl: float = 1.0):
        self._state_path = state_path
        self._cache_ttl = cache_ttl
        self._cache: tuple[EngineSnapshot, float] | None = None

    def save(self, snapshot: EngineSnapshot) -> None:
        self._cache = (snapshot, time.monotonic())
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        data = sanitize(asdict(snapshot))
        _atomic_write_json(self._state_path, data)

    def load(self) -> EngineSnapshot | None:
        if self._cache is not None:
            cached, expiry = self._cache
            if time.monotonic() < expiry:
                return cached
            self._cache = None
        if not os.path.exists(self._state_path):
            return None
        try:
            with open(self._state_path) as f:
                data = json.load(f)
            snapshot = EngineSnapshot.from_dict(data)
            self._cache = (snapshot, time.monotonic() + self._cache_ttl)
            return snapshot
        except Exception as e:
            logger.warning("Failed to load state snapshot: %s", e)
            return None


# ═══════════════════════════════════════════════════════════════════════
# AnalyticsStore — precomputed analytics from SQLite data
# ═══════════════════════════════════════════════════════════════════════

class _AnalyticsStore:
    """Precomputed trade outcomes and aggregated analytics snapshots."""

    def __init__(self, db_store: _DatabaseStore, analytics_path: str, trade_outcomes_path: str):
        self._db = db_store
        self._analytics_path = analytics_path
        self._trade_outcomes_path = trade_outcomes_path
        self._analytics_snapshot_counter = 0
        self._analytics_snapshot_frequency = 5
        self._trade_outcomes_cache: tuple[dict, float] | None = None

    # ── Trade outcomes ─────────────────────────────────────────────

    def write_trade_outcomes_cache(self) -> None:
        self.read_trade_outcomes()

    def read_trade_outcomes(self) -> dict | None:
        now = time.monotonic()
        if self._trade_outcomes_cache is not None and now - self._trade_outcomes_cache[1] < 30.0:
            return self._trade_outcomes_cache[0]
        result = self._compute_trade_outcomes()
        if result is not None:
            self._trade_outcomes_cache = (result, now)
        return result

    def _compute_trade_outcomes(self) -> dict | None:
        try:
            with sqlite3.connect(self._db._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM trades").fetchall()
                if not rows:
                    return None
                df = pd.DataFrame([dict(r) for r in rows])

            reason_col = "reason" if "reason" in df.columns else "exit_reason"
            ret_col = "return" if "return" in df.columns else "pnl"
            r_col = "realized_r" if "realized_r" in df.columns else None

            if reason_col in df.columns:
                df[reason_col] = (
                    df[reason_col]
                    .astype(str)
                    .str.lower()
                    .replace({"sl_hit": "sl", "tp_hit": "tp", "gate_closed": "signal_flip"})
                )
            if ret_col in df.columns:
                df[ret_col] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)

            by_asset = []
            for asset_name, group in df.groupby("asset"):
                n = len(group)
                tp = int((group[reason_col] == "tp").sum())
                sl = int((group[reason_col] == "sl").sum())
                flip = int((group[reason_col] == "signal_flip").sum())
                wins = int((group[ret_col] > 0).sum())
                total_profit = float(group[ret_col].clip(lower=0).sum())
                total_loss = float((-group[ret_col].clip(upper=0)).sum())
                avg_r = float(group[r_col].mean()) if r_col and r_col in group else 0.0
                by_asset.append({
                    "asset": asset_name,
                    "n_trades": n,
                    "tp_rate": round(tp / n, 4) if n > 0 else 0.0,
                    "sl_rate": round(sl / n, 4) if n > 0 else 0.0,
                    "signal_flip_rate": round(flip / n, 4) if n > 0 else 0.0,
                    "avg_r": round(avg_r, 4),
                    "win_rate": round(wins / n, 4) if n > 0 else 0.0,
                    "profit_factor": round(total_profit / total_loss, 4) if total_loss > 0 else None,
                })

            n_total = len(df)
            tp_total = int((df[reason_col] == "tp").sum())
            sl_total = int((df[reason_col] == "sl").sum())
            flip_total = int((df[reason_col] == "signal_flip").sum())
            wins_total = int((df[ret_col] > 0).sum())
            profit_total = float(df[ret_col].clip(lower=0).sum())
            loss_total = float((-df[ret_col].clip(upper=0)).sum())
            avg_r_total = float(df[r_col].mean()) if r_col and r_col in df.columns else 0.0

            payload = {
                "overall": {
                    "tp_rate": round(tp_total / n_total, 4) if n_total > 0 else 0.0,
                    "sl_rate": round(sl_total / n_total, 4) if n_total > 0 else 0.0,
                    "signal_flip_rate": round(flip_total / n_total, 4) if n_total > 0 else 0.0,
                    "avg_r": round(avg_r_total, 4),
                    "win_rate": round(wins_total / n_total, 4) if n_total > 0 else 0.0,
                    "profit_factor": round(profit_total / loss_total, 4) if loss_total > 0 else None,
                },
                "by_asset": by_asset,
                "updated_at": datetime.now(tz=ET).isoformat(),
            }
            _atomic_write_json(self._trade_outcomes_path, payload)
            return payload
        except Exception:
            logger.exception("Failed to compute trade outcomes")
            return None

    # ── Analytics snapshot ─────────────────────────────────────────

    def write_snapshot(self) -> None:
        self._analytics_snapshot_counter += 1
        if self._analytics_snapshot_counter < self._analytics_snapshot_frequency:
            return
        self._analytics_snapshot_counter = 0

        attrs = self._db.read_attribution(limit=2000)
        shadows = self._db.read_shadow_trades(limit=2000)
        snapshot: dict = {}

        if attrs:
            df = pd.DataFrame(attrs)
            arch_col = "pred_archetype_at_entry"
            regime_col = "pred_regime_at_entry"
            reason_col = "exit_exit_reason"

            r_values = df.get("exit_realized_r", df.get("realized_r", 0))
            reason_series = df.get(reason_col) if reason_col in df.columns else pd.Series(dtype=object)
            has_reason = len(reason_series) > 0
            snapshot["overall"] = {
                "n_trades": len(df),
                "avg_r": float(r_values.mean()),
                "win_rate": float((r_values > 0).mean()),
                "tp_rate": float((reason_series == "tp").mean()) if has_reason else 0.0,
                "sl_rate": float((reason_series == "sl").mean()) if has_reason else 0.0,
            }
            by_arch = {}
            if arch_col in df.columns:
                for arch, grp in df.groupby(arch_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    grp_reason = grp.get(reason_col) if reason_col in grp.columns else pd.Series(dtype=object)
                    grp_has_reason = len(grp_reason) > 0
                    by_arch[arch] = {
                        "n": len(grp),
                        "avg_r": float(grp_r.mean()),
                        "win_rate": float((grp_r > 0).mean()),
                        "tp_rate": float((grp_reason == "tp").mean()) if grp_has_reason else 0.0,
                        "sl_rate": float((grp_reason == "sl").mean()) if grp_has_reason else 0.0,
                        "avg_entry_slippage": float(grp.get("friction_entry_slippage_bps", 0).mean()),
                        "avg_mae": float(grp.get("exit_mae", 0).mean()),
                        "avg_mfe": float(grp.get("exit_mfe", 0).mean()),
                    }
            snapshot["by_archetype"] = by_arch
            by_reg = {}
            if regime_col in df.columns:
                for reg, grp in df.groupby(regime_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    by_reg[reg] = {"n": len(grp), "avg_r": float(grp_r.mean()), "win_rate": float((grp_r > 0).mean())}
            snapshot["by_regime"] = by_reg

        if shadows:
            sdf = pd.DataFrame(shadows)
            n = len(sdf)
            same = (sdf.get("exit_reason", "") == sdf.get("live_exit_reason", "")).sum()
            shadow_divergence_rate = 1 - (same / n) if n > 0 else 0
            r_delta = sdf.get("realized_r", 0) - sdf.get("live_realized_r", 0)
            snapshot["shadow"] = {
                "n": n,
                "divergence_rate": round(shadow_divergence_rate, 4),
                "avg_r_delta": round(float(r_delta.mean()), 4),
            }

        snapshot["updated_at"] = datetime.now(tz=ET).isoformat()
        try:
            _atomic_write_json(self._analytics_path, snapshot)
        except OSError as e:
            logger.error("Failed to write analytics snapshot: %s", e)

    def read_snapshot(self) -> dict | None:
        if not os.path.exists(self._analytics_path):
            return None
        try:
            with open(self._analytics_path) as f:
                return json.load(f)
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════════
# DataCache — parquet file cache for downloaded market data
# ═══════════════════════════════════════════════════════════════════════

class _DataCache:
    """Parquet file cache for downloaded OHLCV data."""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        os.makedirs(self._cache_dir, exist_ok=True)

    def path_for(self, ticker: str) -> str:
        safe_name = ticker.replace("=", "_").replace("-", "_")
        return os.path.join(self._cache_dir, f"{safe_name}.parquet")

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        path = self.path_for(ticker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path)

    def load(self, ticker: str) -> pd.DataFrame | None:
        path = self.path_for(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning("Cache read error for %s: %s", ticker, e)
        return None


# ═══════════════════════════════════════════════════════════════════════
# StateStore — facade delegating to focused internal stores
# ═══════════════════════════════════════════════════════════════════════

class StateStore:
    """Facade that delegates to DatabaseStore, SnapshotManager, AnalyticsStore, and DataCache."""

    def __init__(self, base_dir: str, snapshot_cache_ttl: float = 1.0):
        self.base_dir = base_dir
        self.live_dir = os.path.join(base_dir, "data", "live")
        self.state_path = os.path.join(self.live_dir, "state.json")
        self.equity_history_path = os.path.join(self.live_dir, "equity_history.json")
        self.review_log_path = os.path.join(self.live_dir, "review_log.json")
        self.trade_outcomes_path = os.path.join(self.live_dir, "trade_outcomes.json")
        self.cache_dir = os.path.join(self.live_dir, "cache")

        db_path = os.path.join(self.live_dir, "state.db")
        os.makedirs(self.live_dir, exist_ok=True)

        self.db = _DatabaseStore(db_path)
        self.snapshot = _SnapshotManager(self.state_path, cache_ttl=snapshot_cache_ttl)
        self.analytics = _AnalyticsStore(
            self.db,
            os.path.join(self.live_dir, "analytics_snapshot.json"),
            self.trade_outcomes_path,
        )
        self.cache = _DataCache(self.cache_dir)

    # ── Snapshot ───────────────────────────────────────────────────

    def save_snapshot(self, snapshot: EngineSnapshot) -> None:
        self.snapshot.save(snapshot)
        self.db.checkpoint_wal()

    def load_snapshot(self) -> EngineSnapshot | None:
        return self.snapshot.load()

    # ── Trades ─────────────────────────────────────────────────────

    def append_trade(self, trade: dict) -> None:
        self.db.append_trade(trade)

    def read_trades(self, limit: int = 10) -> list:
        return self.db.read_trades(limit)

    def read_trades_since(self, date: str) -> pd.DataFrame:
        return self.db.read_trades_since(date)

    def write_trade_outcomes_cache(self) -> None:
        self.analytics.write_trade_outcomes_cache()

    def read_trade_outcomes(self) -> dict | None:
        return self.analytics.read_trade_outcomes()

    # ── Attribution ────────────────────────────────────────────────

    def append_attribution(self, record_dict: dict) -> None:
        self.db.append_attribution(record_dict)

    def read_attribution(
        self,
        limit: int = 100,
        offset: int = 0,
        archetype: str | None = None,
        regime: str | None = None,
        asset: str | None = None,
    ) -> list:
        return self.db.read_attribution(limit, offset, archetype, regime, asset)

    # ── Shadow trades ──────────────────────────────────────────────

    def append_shadow_trade(self, record_dict: dict) -> None:
        self.db.append_shadow_trade(record_dict)

    def read_shadow_trades(self, limit: int = 100, offset: int = 0, alt_label: str | None = None) -> list:
        return self.db.read_shadow_trades(limit, offset, alt_label)

    # ── Analytics ──────────────────────────────────────────────────

    def write_analytics_snapshot(self) -> None:
        self.analytics.write_snapshot()

    def read_analytics_snapshot(self) -> dict | None:
        return self.analytics.read_snapshot()

    # ── Confidence buckets ─────────────────────────────────────────

    def append_confidence_bucket(self, bucket: dict) -> None:
        self.db.append_confidence_bucket(bucket)

    # ── Equity history ─────────────────────────────────────────────

    def append_equity_history(self, record: dict) -> None:
        self.db.append_equity_history(record)

    def read_equity_history(self) -> list:
        return self.db.read_equity_history()

    # ── Raw DB access (for tests / direct queries) ────────────────

    def connect(self) -> sqlite3.Connection:
        """Open a direct SQLite connection. Used by tests."""
        return self.db._connect()

    # ── Data cache ─────────────────────────────────────────────────

    def cache_path(self, ticker: str) -> str:
        return self.cache.path_for(ticker)

    def save_cache(self, ticker: str, df: pd.DataFrame) -> None:
        self.cache.save(ticker, df)

    def load_cache(self, ticker: str) -> pd.DataFrame | None:
        return self.cache.load(ticker)
