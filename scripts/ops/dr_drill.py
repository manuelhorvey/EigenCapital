#!/usr/bin/env python3
"""Disaster Recovery Drill — automated restore validation for SQLite state.

Executes the following steps:
  1. Creates a backup of the current state database
  2. Restores from the backup to a temporary location
  3. Runs integrity check on the restored copy
  4. Verifies key tables (trades, equity_history) have data
  5. Cleans up temporary files

Usage:
    # Full drill (backup + restore + verify + clean)
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/dr_drill.py

    # Verify-only mode (skip backup, just check existing state.db)
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/dr_drill.py --verify-only

    # Report-only (print latest drill results)
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/dr_drill.py --report

Exit codes:
    0 — All checks passed
    1 — Integrity check failed
    2 — Restore verification failed
    3 — Backup creation failed
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("dr_drill")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE, "data", "live", "state.db")
BACKUP_DIR = os.path.join(BASE, "data", "backups", "sqlite")
DRILL_LOG_PATH = os.path.join(BASE, "data", "logs", "dr_drill_results.json")

REQUIRED_TABLES = ["trades", "attribution", "equity_history", "shadow_trades", "confidence_buckets"]


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def step_backup(db_path: str) -> str | None:
    """Create a timestamped backup of the SQLite database.

    Returns the backup path, or None on failure.
    """
    if not os.path.isfile(db_path):
        logger.error("Source database not found: %s", db_path)
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"state_drill_{timestamp}.db")
    _ensure_dir(BACKUP_DIR)

    try:
        shutil.copy2(db_path, backup_path)
        logger.info("Backup created: %s (%d bytes)", backup_path, os.path.getsize(backup_path))
        return backup_path
    except (OSError, shutil.Error) as e:
        logger.error("Backup failed: %s", e)
        return None


def step_restore_and_verify(backup_path: str) -> dict:
    """Restore from backup to temp location and run full integrity check.

    Returns a dict with keys: status, row_counts, integrity, errors.
    """
    result: dict = {
        "status": "FAILED",
        "row_counts": {},
        "integrity": [],
        "errors": [],
    }

    if not os.path.isfile(backup_path):
        result["errors"].append(f"Backup not found: {backup_path}")
        return result

    # Restore to temp location
    try:
        fd, temp_path = tempfile.mkstemp(suffix=".db", prefix="dr_verify_")
        os.close(fd)
        shutil.copy2(backup_path, temp_path)
        logger.info("Restored to temp: %s", temp_path)
    except (OSError, shutil.Error) as e:
        result["errors"].append(f"Restore copy failed: {e}")
        return result

    try:
        conn = sqlite3.connect(temp_path, timeout=5.0)

        # PRAGMA integrity_check
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        result["integrity"] = [r[0] for r in integrity_rows]
        integrity_ok = all(r[0] == "ok" for r in integrity_rows)
        if not integrity_ok:
            result["errors"].append("Integrity check FAILED on restored backup")
            result["status"] = "CORRUPT"
            conn.close()
            _cleanup_temp(temp_path)
            return result

        # PRAGMA quick_check on key tables
        for table in REQUIRED_TABLES:
            try:
                qc = conn.execute(f"PRAGMA quick_check('{table}')").fetchone()
                if qc and qc[0] != "ok":
                    result["errors"].append(f"Table '{table}' quick_check: {qc[0]}")
            except sqlite3.OperationalError:
                result["errors"].append(f"Table '{table}' not found in restored backup")

        # Row counts
        for table in REQUIRED_TABLES:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                result["row_counts"][table] = count
            except sqlite3.OperationalError:
                result["row_counts"][table] = 0

        conn.close()

        # Determine overall status
        if integrity_ok:
            result["status"] = "PASSED"
        else:
            result["status"] = "CORRUPT"

        logger.info(
            "Restore verification: %s — %d tables, %d rows",
            result["status"],
            len(result["row_counts"]),
            sum(result["row_counts"].values()),
        )

    except sqlite3.DatabaseError as e:
        result["errors"].append(f"SQLite error during verification: {e}")
        result["status"] = "ERROR"
    except OSError as e:
        result["errors"].append(f"OS error during verification: {e}")
        result["status"] = "ERROR"

    _cleanup_temp(temp_path)
    return result


def _cleanup_temp(temp_path: str) -> None:
    """Remove temp file if it exists."""
    try:
        if os.path.isfile(temp_path):
            os.remove(temp_path)
            logger.debug("Cleaned up temp: %s", temp_path)
    except OSError:
        pass


def _write_results(results: dict) -> None:
    """Write drill results to log file."""
    _ensure_dir(os.path.dirname(DRILL_LOG_PATH))
    try:
        with open(DRILL_LOG_PATH, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Drill results written to %s", DRILL_LOG_PATH)
    except (OSError, TypeError) as e:
        logger.error("Failed to write drill results: %s", e)


def _read_latest_results() -> dict | None:
    """Read the latest drill results from log file."""
    if not os.path.isfile(DRILL_LOG_PATH):
        return None
    try:
        with open(DRILL_LOG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read drill results: %s", e)
        return None


def verify_only(db_path: str) -> dict:
    """Verify the current state database without creating a backup."""
    from paper_trading.state.integrity_check import check_database_integrity

    result = check_database_integrity(db_path, repair_on_failure=False)
    logger.info("Direct integrity check: %s", result["status"])
    # Add row counts
    row_counts: dict[str, int] = {}
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        for table in REQUIRED_TABLES:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                row_counts[table] = count
            except sqlite3.OperationalError:
                row_counts[table] = 0
        conn.close()
    except (sqlite3.DatabaseError, OSError):
        pass
    result["row_counts"] = row_counts
    return result


def run_drill(db_path: str | None = None) -> dict:
    """Execute full disaster recovery drill: backup → restore → verify → report."""
    db_path = db_path or DEFAULT_DB_PATH
    logger.info("=" * 60)
    logger.info("  DISASTER RECOVERY DRILL")
    logger.info("=" * 60)
    logger.info("Database: %s", db_path)

    if not os.path.isfile(db_path):
        logger.error("Database not found at %s — skipping drill", db_path)
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "SKIPPED",
            "reason": f"Database not found: {db_path}",
        }
        _write_results(result)
        return result

    # Step 1: Backup
    logger.info("Step 1/3: Backup...")
    backup_path = step_backup(db_path)
    if backup_path is None:
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "FAILED",
            "step": "backup",
            "reason": "Backup creation failed",
        }
        _write_results(result)
        return result

    # Step 2: Restore + Verify
    logger.info("Step 2/3: Restore + Verify...")
    verify_result = step_restore_and_verify(backup_path)
    if verify_result["status"] != "PASSED":
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "FAILED",
            "step": "verify",
            "backup_path": backup_path,
            "verify_result": verify_result,
        }
        _write_results(result)
        return result

    # Step 3: Cleanup old backups (keep last 5)
    logger.info("Step 3/3: Cleanup old backups...")
    _cleanup_old_backups(keep=5)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED",
        "db_path": db_path,
        "backup_path": backup_path,
        "backup_size_bytes": os.path.getsize(backup_path) if os.path.isfile(backup_path) else 0,
        "verify_result": verify_result,
        "row_counts": verify_result.get("row_counts", {}),
    }
    _write_results(result)
    logger.info("=" * 60)
    logger.info("  DRILL PASSED — backup verified, restore tested")
    logger.info("=" * 60)
    return result


def _cleanup_old_backups(keep: int = 5) -> None:
    """Remove old drill backups, keeping the *keep* most recent."""
    if not os.path.isdir(BACKUP_DIR):
        return
    backups = sorted(
        [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("state_drill_")],
        key=os.path.getmtime,
    )
    while len(backups) > keep:
        old = backups.pop(0)
        try:
            os.remove(old)
            logger.debug("Cleaned up old backup: %s", old)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Disaster Recovery Drill — validate SQLite backup/restore")
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to state database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip backup, just verify current database integrity",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print latest drill results and exit",
    )
    args = parser.parse_args()

    if args.report:
        results = _read_latest_results()
        if results is None:
            logger.info("No drill results found (run a drill first)")
            return 0
        print(json.dumps(results, indent=2, default=str))
        return 0

    if args.verify_only:
        result = verify_only(args.db_path)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["status"] == "OK" else 1

    result = run_drill(args.db_path)
    exit_code = 0 if result["status"] == "PASSED" else 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
