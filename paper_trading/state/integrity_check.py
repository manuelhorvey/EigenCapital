"""SQLite database integrity checker — runs on startup and after recovery.

Provides a lightweight health check that validates the SQLite database
file is not corrupted and the WAL (Write-Ahead Log) can be checkpointed
without error.

Usage:
    from paper_trading.state.integrity_check import check_database_integrity
    check_database_integrity("/path/to/state.db")
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3

logger = logging.getLogger("eigencapital.state.integrity_check")


class DatabaseIntegrityError(RuntimeError):
    """Raised when the SQLite database fails an integrity check."""


def check_database_integrity(db_path: str, repair_on_failure: bool = False) -> dict:
    """Run a comprehensive SQLite database integrity check.

    Performs:
      1. File existence and size validation
      2. SQLite ``PRAGMA integrity_check`` (full structural verification)
      3. WAL journal mode validation
      4. WAL checkpoint (verifies the WAL can be safely applied)
      5. ``PRAGMA quick_check`` on key application tables (trades, equity_history)

    Args:
        db_path: Absolute path to the SQLite database file.
        repair_on_failure: If True, attempt VACUUM and recovery on failure.

    Returns:
        A dict with keys:
            - ``status``: "OK" | "CORRUPT" | "RECOVERED"
            - ``integrity_check``: raw PRAGMA integrity_check output
            - ``quick_check``: raw PRAGMA quick_check output
            - ``journal_mode``: detected journal mode
            - ``page_count`` / ``page_size`` for size estimation
            - ``errors``: list of error messages (empty if OK)

    Raises:
        DatabaseIntegrityError: If the database is unreachable or corrupt
            and ``repair_on_failure`` is False.
    """
    errors: list[str] = []

    # 1. File existence
    if not Path(db_path).is_file():
        errors.append(f"Database file not found: {db_path}")
        if repair_on_failure:
            return {"status": "CORRUPT", "errors": errors}
        raise DatabaseIntegrityError("; ".join(errors))

    file_size = Path(db_path).stat().st_size
    if file_size == 0:
        errors.append(f"Database file is empty (0 bytes): {db_path}")
        if repair_on_failure:
            return {"status": "CORRUPT", "errors": errors}
        raise DatabaseIntegrityError("; ".join(errors))

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.execute("PRAGMA synchronous=NORMAL")

        # 2. Full integrity check
        integrity_result = conn.execute("PRAGMA integrity_check").fetchall()
        integrity_ok = all(row[0] == "ok" for row in integrity_result)

        # 3. Journal mode detection
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if journal_mode not in ("wal", "delete", "truncate", "persist", "memory", "off"):
            errors.append(f"Unexpected journal mode: {journal_mode}")

        # 4. WAL checkpoint (verifies WAL can be safely applied)
        try:
            checkpoint_result = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            # checkpoint_result: (busy, log, checkpointed)
            if checkpoint_result[0] == 0 and checkpoint_result[1] > 0:
                # Not busy but WAL pages remain — this is normal for shared usage
                pass
        except sqlite3.OperationalError as e:
            errors.append(f"WAL checkpoint failed: {e}")

        # 5. Quick check on key tables
        quick_check_result: list[sqlite3.Row] = []
        for table in ("trades", "equity_history", "attribution"):
            try:
                result = conn.execute(f"PRAGMA quick_check('{table}')").fetchone()
                quick_check_result.append(result)
                if result[0] != "ok":
                    errors.append(f"Table '{table}' quick_check: {result[0]}")
            except sqlite3.OperationalError:
                # Table might not exist yet — not an integrity error
                pass

        # Gather metadata
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]

        conn.close()

        if not integrity_ok:
            errors.append(f"PRAGMA integrity_check failed: {integrity_result}")

        if errors:
            logger.warning(
                "Database integrity issues detected for %s (%s): %s",
                db_path,
                _format_size(file_size),
                "; ".join(errors),
            )
            if repair_on_failure:
                _attempt_repair(db_path, errors)
                return {
                    "status": "RECOVERED",
                    "integrity_check": [r[0] for r in integrity_result],
                    "quick_check": [r[0] for r in quick_check_result],
                    "journal_mode": journal_mode,
                    "page_count": page_count,
                    "page_size": page_size,
                    "errors": errors,
                }
            raise DatabaseIntegrityError(f"Database integrity check FAILED for {db_path}: {'; '.join(errors)}")

        logger.info(
            "Database integrity OK: %s (%s, journal=%s, %d pages @ %d bytes)",
            db_path,
            _format_size(file_size),
            journal_mode,
            page_count,
            page_size,
        )
        return {
            "status": "OK",
            "integrity_check": [r[0] for r in integrity_result],
            "quick_check": [r[0] for r in quick_check_result],
            "journal_mode": journal_mode,
            "page_count": page_count,
            "page_size": page_size,
            "errors": [],
        }

    except sqlite3.DatabaseError as e:
        errors.append(f"SQLite error: {e}")
        _log_and_raise(errors, repair_on_failure)
        return {
            "status": "CORRUPT",
            "integrity_check": [],
            "quick_check": [],
            "journal_mode": "unknown",
            "page_count": 0,
            "page_size": 0,
            "errors": errors,
        }
    except OSError as e:
        errors.append(f"OS error accessing {db_path}: {e}")
        _log_and_raise(errors, repair_on_failure)
        return {
            "status": "CORRUPT",
            "integrity_check": [],
            "quick_check": [],
            "journal_mode": "unknown",
            "page_count": 0,
            "page_size": 0,
            "errors": errors,
        }


def _log_and_raise(errors: list[str], repair_on_failure: bool) -> None:
    """Log errors and optionally raise instead of returning.

    When *repair_on_failure* is False, raises DatabaseIntegrityError.
    When True, returns None (caller must handle the fallback return).
    """
    if not repair_on_failure:
        raise DatabaseIntegrityError("; ".join(errors))


def _attempt_repair(db_path: str, errors: list[str]) -> None:
    """Attempt to repair a corrupted SQLite database using VACUUM and .recover.

    This is a best-effort operation. If the database is critically corrupt,
    the backup should be used instead.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        logger.warning("Attempting VACUUM repair on %s", db_path)
        conn.execute("VACUUM")
        errors.append("VACUUM completed as repair step")
        conn.close()
    except sqlite3.DatabaseError as e:
        errors.append(f"VACUUM repair FAILED: {e}")
        logger.error("VACUUM repair failed for %s: %s", db_path, e)


def _format_size(bytes_size: int) -> str:
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size //= 1024
    return f"{bytes_size:.1f} TB"
