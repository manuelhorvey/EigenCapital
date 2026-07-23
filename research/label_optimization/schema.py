"""Experiment database schema — SQLite-backed, normalized."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

EXPERIMENT_DB = Path("data/processed/label_optimization.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT UNIQUE NOT NULL,       -- "{asset}__{label_method}__{pt}x{sl}x{vb}"
    asset           TEXT NOT NULL,
    label_method    TEXT NOT NULL,              -- "triple_barrier", "symmetric", "forward_return"
    pt              REAL NOT NULL,
    sl              REAL NOT NULL,
    vb              INTEGER NOT NULL,
    vol_method      TEXT,
    atr_period      INTEGER,
    git_commit      TEXT,
    dataset_hash    TEXT,
    timestamp       TEXT NOT NULL,
    runtime_sec     REAL,
    status          TEXT DEFAULT 'running'      -- "running", "done", "failed"
);

CREATE TABLE IF NOT EXISTS label_metrics (
    experiment_id   TEXT PRIMARY KEY,
    buy_pct         REAL,
    sell_pct        REAL,
    timeout_pct     REAL,
    n_buy           INTEGER,
    n_sell          INTEGER,
    n_timeout       INTEGER,
    n_total         INTEGER,
    entropy         REAL,
    imbalance_ratio REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS model_metrics (
    experiment_id   TEXT PRIMARY KEY,
    auc             REAL,
    log_loss        REAL,
    f1              REAL,
    mcc             REAL,
    precision_buy   REAL,
    recall_buy      REAL,
    precision_sell  REAL,
    recall_sell     REAL,
    n_train         INTEGER,
    n_valid         INTEGER,
    feature_count   INTEGER,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS calibration_metrics (
    experiment_id   TEXT PRIMARY KEY,
    ece             REAL,
    brier           REAL,
    calibration_slope   REAL,
    calibration_intercept REAL,
    reliability_max_dev REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS trading_metrics (
    experiment_id   TEXT PRIMARY KEY,
    sharpe          REAL,
    sortino         REAL,
    profit_factor   REAL,
    cagr_pct        REAL,
    total_return_pct REAL,
    max_drawdown_pct REAL,
    win_rate_pct    REAL,
    avg_r           REAL,
    total_r         REAL,
    trade_count     INTEGER,
    turnover        REAL,
    calmar_ratio    REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS behavioral_metrics (
    experiment_id   TEXT PRIMARY KEY,
    cal_inversion_rate  REAL,       -- fraction of predictions flipped by calibration
    avg_pred_buy_pct    REAL,       -- mean predicted P(buy) across all predictions
    avg_pred_sell_pct   REAL,
    pred_entropy        REAL,       -- entropy of prediction distribution
    sell_only_blocks    INTEGER,    -- count of SELL_ONLY activations in WF test windows
    conf_rejections     INTEGER,    -- count of confidence-gate rejections
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);
"""


def get_db() -> sqlite3.Connection:
    EXPERIMENT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(EXPERIMENT_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def experiment_id(asset: str, method: str, pt: float, sl: float, vb: int) -> str:
    return f"{asset}__{method}__{pt:.2f}x{sl:.2f}x{vb}"


def create_experiment(asset: str, method: str, pt: float, sl: float, vb: int,
                      vol_method: str | None = None, atr_period: int | None = None,
                      git_commit: str | None = None) -> str:
    eid = experiment_id(asset, method, pt, sl, vb)
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO experiments
               (experiment_id, asset, label_method, pt, sl, vb, vol_method, atr_period, git_commit, timestamp, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
            (eid, asset, method, pt, sl, vb, vol_method, atr_period, git_commit, datetime.utcnow().isoformat())
        )
        conn.commit()
    finally:
        conn.close()
    return eid


def save_metrics(table: str, experiment_id: str, metrics: dict[str, Any]) -> None:
    conn = get_db()
    cols = ", ".join(metrics.keys())
    placeholders = ", ".join(["?"] * len(metrics))
    sql = f"INSERT OR REPLACE INTO {table} (experiment_id, {cols}) VALUES (?, {placeholders})"
    try:
        conn.execute(sql, [experiment_id] + list(metrics.values()))
        conn.commit()
    finally:
        conn.close()


def finalize_experiment(experiment_id: str, status: str, runtime_sec: float | None = None) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE experiments SET status = ?, runtime_sec = COALESCE(?, runtime_sec) WHERE experiment_id = ?",
            (status, runtime_sec, experiment_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_experiments() -> list[sqlite3.Row]:
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM experiments ORDER BY asset, pt, sl").fetchall()
    finally:
        conn.close()


def get_experiment_results() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT e.*, lm.*, mm.*, cm.*, tm.*, bm.*
            FROM experiments e
            LEFT JOIN label_metrics lm ON e.experiment_id = lm.experiment_id
            LEFT JOIN model_metrics mm ON e.experiment_id = mm.experiment_id
            LEFT JOIN calibration_metrics cm ON e.experiment_id = cm.experiment_id
            LEFT JOIN trading_metrics tm ON e.experiment_id = tm.experiment_id
            LEFT JOIN behavioral_metrics bm ON e.experiment_id = bm.experiment_id
            WHERE e.status = 'done'
            ORDER BY e.asset, e.pt, e.sl
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
