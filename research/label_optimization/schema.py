"""Experiment database schema — SQLite-backed, normalized.

Supports uncertainty quantification (fold-level storage → aggregated
mean/std/95% CI), production cost tracking, and versioned strategies.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import t as t_dist

EXPERIMENT_DB = Path("data/processed/label_optimization.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT UNIQUE NOT NULL,
    asset           TEXT NOT NULL,
    label_method    TEXT NOT NULL,
    pt              REAL NOT NULL,
    sl              REAL NOT NULL,
    vb              INTEGER NOT NULL,
    vol_method      TEXT,
    atr_period      INTEGER,
    label_strategy_version TEXT DEFAULT 'TB_v1',
    git_commit      TEXT,
    dataset_hash    TEXT,
    config_hash     TEXT,
    timestamp       TEXT NOT NULL,
    runtime_sec     REAL,
    baseline_id     TEXT,
    status          TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS label_metrics (
    experiment_id   TEXT PRIMARY KEY,
    buy_pct         REAL,   buy_pct_std    REAL,
    sell_pct        REAL,   sell_pct_std   REAL,
    timeout_pct     REAL,   timeout_pct_std REAL,
    n_buy           INTEGER,
    n_sell          INTEGER,
    n_timeout       INTEGER,
    n_total         INTEGER,
    entropy         REAL,   entropy_std    REAL,
    imbalance_ratio REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS model_metrics (
    experiment_id   TEXT PRIMARY KEY,
    auc_mean        REAL,   auc_std         REAL,
    auc_ci95        REAL,
    n_train         INTEGER,
    n_valid         INTEGER,
    feature_count   INTEGER,
    peak_mem_mb     REAL,
    feature_time_sec REAL,
    train_time_sec  REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS calibration_metrics (
    experiment_id   TEXT PRIMARY KEY,
    ece_mean        REAL,   ece_std         REAL,   ece_ci95        REAL,
    brier_mean      REAL,   brier_std       REAL,   brier_ci95      REAL,
    calibration_slope   REAL,
    calibration_intercept REAL,
    reliability_max_dev REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS trading_metrics (
    experiment_id   TEXT PRIMARY KEY,
    sharpe_mean     REAL,   sharpe_std      REAL,   sharpe_ci95     REAL,
    sortino_mean    REAL,   sortino_std     REAL,
    profit_factor_mean REAL, profit_factor_std REAL, profit_factor_ci95 REAL,
    cagr_mean       REAL,   cagr_std        REAL,
    total_return_pct REAL,  total_return_std REAL,
    max_drawdown_mean REAL, max_drawdown_std REAL,
    avg_r_mean      REAL,   avg_r_std       REAL,
    total_r         REAL,
    trade_count     INTEGER,
    turnover_mean   REAL,   turnover_std    REAL,
    calmar_mean     REAL,   calmar_std      REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS behavioral_metrics (
    experiment_id   TEXT PRIMARY KEY,
    cal_inversion_rate_mean REAL,  cal_inversion_rate_std REAL,
    avg_pred_buy_pct    REAL,
    avg_pred_sell_pct   REAL,
    pred_entropy        REAL,
    sell_only_blocks    INTEGER,
    conf_rejections     INTEGER,
    avg_cal_correction  REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS fold_results (
    experiment_id   TEXT NOT NULL,
    fold            INTEGER NOT NULL,
    n_train         INTEGER,
    n_test          INTEGER,
    n_buy           INTEGER,
    n_sell          INTEGER,
    n_timeout       INTEGER,
    buy_pct         REAL,
    sell_pct        REAL,
    entropy         REAL,
    imbalance_ratio REAL,
    sharpe          REAL,
    profit_factor   REAL,
    total_return_pct REAL,
    max_drawdown_pct REAL,
    ece             REAL,
    brier           REAL,
    cal_inversion_rate REAL,
    directional     REAL,
    spearman_ic     REAL,
    flat_rate       REAL,
    train_fold_sec  REAL,
    PRIMARY KEY (experiment_id, fold),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS production_cost_metrics (
    experiment_id       TEXT PRIMARY KEY,
    sell_only_avoids    INTEGER,
    conf_overrides      INTEGER,
    cal_correction_mean REAL,
    threshold_reject_rate REAL,
    edge_retention      REAL,
    parity_ratio        REAL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS baselines (
    experiment_id   TEXT PRIMARY KEY,
    asset           TEXT NOT NULL,
    pt              REAL NOT NULL,
    sl              REAL NOT NULL,
    sharpe_baseline REAL NOT NULL,
    ece_baseline    REAL NOT NULL,
    cal_inv_baseline REAL NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);
"""


def _t_cv(n: int, alpha: float = 0.05) -> float:
    return float(t_dist.ppf(1 - alpha / 2, max(n - 1, 1)))


def _mean_std_ci(values: list[float]) -> tuple[float, float, float]:
    arr = np.array(values, dtype=float)
    n = len(arr)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    ci = _t_cv(n) * std / max(np.sqrt(n), 1e-10)
    return round(mean, 6), round(std, 6), round(ci, 6)


def compute_fold_aggregates(experiment_id: str) -> None:
    """Compute mean, std, 95% CI across folds and write to main tables."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM fold_results WHERE experiment_id = ? ORDER BY fold",
        (experiment_id,)
    ).fetchall()
    if len(rows) < 2:
        return

    def _agg(col: str) -> tuple[float, float, float]:
        vals = [float(r[col]) for r in rows if r[col] is not None]
        if len(vals) < 1:
            return 0.0, 0.0, 0.0
        return _mean_std_ci(vals)

    # label_metrics
    lm = {
        "buy_pct": _agg("buy_pct")[0], "buy_pct_std": _agg("buy_pct")[1],
        "sell_pct": _agg("sell_pct")[0], "sell_pct_std": _agg("sell_pct")[1],
        "timeout_pct": 1 - _agg("buy_pct")[0] - _agg("sell_pct")[0],
        "timeout_pct_std": 0.0,
        "n_buy": int(sum(r["n_buy"] or 0 for r in rows) // len(rows)),
        "n_sell": int(sum(r["n_sell"] or 0 for r in rows) // len(rows)),
        "n_timeout": int(sum(r["n_timeout"] or 0 for r in rows) // len(rows)),
        "n_total": int(sum(r["n_buy"] or 0 for r in rows) + sum(r["n_sell"] or 0 for r in rows) + sum(r["n_timeout"] or 0 for r in rows) // len(rows)),
        "entropy": _agg("entropy")[0], "entropy_std": _agg("entropy")[1],
        "imbalance_ratio": _agg("imbalance_ratio")[0],
    }
    _store_dict(conn, "label_metrics", experiment_id, lm)

    # calibration_metrics
    cm = {
        "ece_mean": _agg("ece")[0], "ece_std": _agg("ece")[1], "ece_ci95": _agg("ece")[2],
        "brier_mean": _agg("brier")[0], "brier_std": _agg("brier")[1], "brier_ci95": _agg("brier")[2],
        "calibration_slope": 0.0, "calibration_intercept": 0.0, "reliability_max_dev": 0.0,
    }
    _store_dict(conn, "calibration_metrics", experiment_id, cm)

    # trading_metrics
    tm = {
        "sharpe_mean": _agg("sharpe")[0], "sharpe_std": _agg("sharpe")[1], "sharpe_ci95": _agg("sharpe")[2],
        "sortino_mean": 0.0, "sortino_std": 0.0,
        "profit_factor_mean": _agg("profit_factor")[0], "profit_factor_std": _agg("profit_factor")[1], "profit_factor_ci95": _agg("profit_factor")[2],
        "cagr_mean": 0.0, "cagr_std": 0.0,
        "total_return_pct": _agg("total_return_pct")[0], "total_return_std": _agg("total_return_pct")[1],
        "max_drawdown_mean": _agg("max_drawdown_pct")[0], "max_drawdown_std": _agg("max_drawdown_pct")[1],
        "avg_r_mean": 0.0, "avg_r_std": 0.0,
        "total_r": _agg("total_return_pct")[0],
        "trade_count": int(sum(r["n_buy"] or 0 for r in rows) // len(rows) + sum(r["n_sell"] or 0 for r in rows) // len(rows)),
        "turnover_mean": 0.0, "turnover_std": 0.0,
        "calmar_mean": 0.0, "calmar_std": 0.0,
    }
    _store_dict(conn, "trading_metrics", experiment_id, tm)

    # behavioral_metrics
    bm = {
        "cal_inversion_rate_mean": _agg("cal_inversion_rate")[0],
        "cal_inversion_rate_std": _agg("cal_inversion_rate")[1],
        "avg_pred_buy_pct": 0.0, "avg_pred_sell_pct": 0.0,
        "pred_entropy": _agg("entropy")[0],
        "sell_only_blocks": 0, "conf_rejections": 0,
        "avg_cal_correction": 0.0,
    }
    _store_dict(conn, "behavioral_metrics", experiment_id, bm)

    conn.close()


def _store_dict(conn: sqlite3.Connection, table: str, experiment_id: str, data: dict) -> None:
    cols = ", ".join(k for k in data if k != "experiment_id")
    vals = [v for k, v in data.items() if k != "experiment_id"]
    placeholders = ", ".join(["?"] * len(vals))
    conn.execute(
        f"INSERT OR REPLACE INTO {table} (experiment_id, {cols}) VALUES (?, {placeholders})",
        [experiment_id] + vals,
    )
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent schema migrations for columns added after initial creation."""
    migrations = [
        "ALTER TABLE experiments ADD COLUMN config_hash TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def get_db() -> sqlite3.Connection:
    EXPERIMENT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(EXPERIMENT_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    _migrate(conn)
    return conn


def experiment_id(asset: str, method: str, pt: float, sl: float, vb: int) -> str:
    return f"{asset}__{method}__{pt:.2f}x{sl:.2f}x{vb}"


def create_experiment(
    asset: str, method: str, pt: float, sl: float, vb: int,
    vol_method: str | None = None, atr_period: int | None = None,
    git_commit: str | None = None,
    label_strategy_version: str = "TB_v1",
    config_hash: str | None = None,
    baseline_id: str | None = None,
) -> str:
    eid = experiment_id(asset, method, pt, sl, vb)
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO experiments
               (experiment_id, asset, label_method, pt, sl, vb, vol_method, atr_period,
                label_strategy_version, git_commit, config_hash, timestamp, status, baseline_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            (eid, asset, method, pt, sl, vb, vol_method, atr_period,
             label_strategy_version, git_commit, config_hash,
             datetime.utcnow().isoformat(), baseline_id)
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


def save_fold_result(experiment_id: str, fold: int, metrics: dict[str, Any]) -> None:
    conn = get_db()
    cols = ", ".join(metrics.keys())
    placeholders = ", ".join(["?"] * len(metrics))
    sql = f"INSERT OR REPLACE INTO fold_results (experiment_id, fold, {cols}) VALUES (?, ?, {placeholders})"
    try:
        conn.execute(sql, [experiment_id, fold] + list(metrics.values()))
        conn.commit()
    finally:
        conn.close()


def save_baseline(experiment_id: str, asset: str, pt: float, sl: float,
                  sharpe_baseline: float, ece_baseline: float,
                  cal_inv_baseline: float) -> None:
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO baselines
               (experiment_id, asset, pt, sl, sharpe_baseline, ece_baseline, cal_inv_baseline)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (experiment_id, asset, pt, sl, sharpe_baseline, ece_baseline, cal_inv_baseline)
        )
        conn.commit()
    finally:
        conn.close()


def finalize_experiment(experiment_id: str, status: str,
                        runtime_sec: float | None = None,
                        peak_mem_mb: float | None = None) -> None:
    conn = get_db()
    try:
        conn.execute(
            """UPDATE experiments SET status = ?, runtime_sec = COALESCE(?, runtime_sec)
               WHERE experiment_id = ?""",
            (status, runtime_sec, experiment_id)
        )
        if peak_mem_mb is not None:
            conn.execute(
                "UPDATE model_metrics SET peak_mem_mb = ? WHERE experiment_id = ?",
                (peak_mem_mb, experiment_id)
            )
        conn.commit()
    finally:
        conn.close()


def get_all_experiments() -> list[sqlite3.Row]:
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM experiments ORDER BY asset, pt, sl"
        ).fetchall()
    finally:
        conn.close()


def get_experiment_results() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT e.*, lm.*, mm.*, cm.*, tm.*, bm.*, pc.*
            FROM experiments e
            LEFT JOIN label_metrics lm ON e.experiment_id = lm.experiment_id
            LEFT JOIN model_metrics mm ON e.experiment_id = mm.experiment_id
            LEFT JOIN calibration_metrics cm ON e.experiment_id = cm.experiment_id
            LEFT JOIN trading_metrics tm ON e.experiment_id = tm.experiment_id
            LEFT JOIN behavioral_metrics bm ON e.experiment_id = bm.experiment_id
            LEFT JOIN production_cost_metrics pc ON e.experiment_id = pc.experiment_id
            WHERE e.status = 'done'
            ORDER BY e.asset, e.pt, e.sl
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_baseline_id(asset: str) -> str | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT experiment_id FROM baselines WHERE asset = ?",
            (asset,)
        ).fetchone()
        return row["experiment_id"] if row else None
    finally:
        conn.close()


def get_baseline_sharpe(asset: str) -> float | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT sharpe_baseline FROM baselines WHERE asset = ?",
            (asset,)
        ).fetchone()
        return row["sharpe_baseline"] if row else None
    finally:
        conn.close()


def delete_experiment(experiment_id: str) -> None:
    conn = get_db()
    tables = ["fold_results", "label_metrics", "model_metrics", "calibration_metrics",
              "trading_metrics", "behavioral_metrics", "production_cost_metrics", "experiments"]
    try:
        for t in tables:
            conn.execute(f"DELETE FROM {t} WHERE experiment_id = ?", (experiment_id,))
        conn.commit()
    finally:
        conn.close()
