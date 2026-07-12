#!/usr/bin/env python3
"""Daily SQLite database backup with retention and optional S3 upload.

Creates a point-in-time backup of the state.db database using SQLite's
``.backup`` API (safe for concurrent reads). Old backups are pruned
to a configurable retention period.

Usage:
    python scripts/ops/backup_sqlite.py                          # daily backup
    python scripts/ops/backup_sqlite.py --retention 30           # keep 30 days
    python scripts/ops/backup_sqlite.py --s3-bucket my-bucket    # upload to S3
    python scripts/ops/backup_sqlite.py --verify                 # restore + verify

Dependencies (optional for S3):
    pip install boto3  # for S3 upload

Add to crontab for daily backups at midnight:
    0 0 * * * cd /path/to/project && PYTHONPATH=$PYTHONPATH:. python scripts/ops/backup_sqlite.py >> data/logs/backup.log 2>&1
"""

from __future__ import annotations

import argparse
import glob
import gzip
import logging
import os
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eigencapital.backup")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "live", "state.db")
DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "data", "backups", "sqlite")
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")


def create_backup(
    db_path: str = DEFAULT_DB_PATH,
    backup_dir: str = DEFAULT_BACKUP_DIR,
    compress: bool = True,
) -> str | None:
    """Create a point-in-time backup of the SQLite database using the backup API.

    The backup is taken via ``sqlite3.backup()``, which is safe for concurrent
    reads (the source database can be in use). The backup file is then
    optionally gzipped.

    Returns the path to the backup file, or None on failure.
    """
    if not os.path.exists(db_path):
        logger.error("Database not found at %s", db_path)
        return None

    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_name = os.path.basename(db_path)
    backup_name = f"{db_name}.{timestamp}"
    backup_path = os.path.join(backup_dir, backup_name)

    try:
        src = sqlite3.connect(db_path, timeout=10.0)
        src.execute("PRAGMA journal_mode=WAL")
        src.execute("PRAGMA busy_timeout=5000")
        dst = sqlite3.connect(backup_path, timeout=10.0)
        dst.execute("PRAGMA busy_timeout=5000")

        with dst:
            src.backup(dst, pages=-1, progress=lambda p, n, _: None)

        src.close()
        dst.close()

        # Verify backup integrity
        verify = sqlite3.connect(backup_path)
        try:
            verify.execute("PRAGMA integrity_check").fetchone()
        finally:
            verify.close()

        logger.info("Backup created: %s (%.1f MB)", backup_path, os.path.getsize(backup_path) / 1e6)

        if compress:
            compressed_path = backup_path + ".gz"
            with open(backup_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.unlink(backup_path)
            logger.info("Compressed: %s (%.1f MB)", compressed_path, os.path.getsize(compressed_path) / 1e6)
            return compressed_path

        return backup_path

    except (sqlite3.Error, OSError, ValueError) as e:
        logger.exception("Backup failed: %s", e)
        # Clean up partial backup
        for path in (backup_path, backup_path + ".gz"):
            if os.path.exists(path):
                os.unlink(path)
        return None


def prune_old_backups(
    backup_dir: str = DEFAULT_BACKUP_DIR,
    retention_days: int = 30,
) -> int:
    """Remove backups older than *retention_days*.

    Returns the number of files pruned.
    """
    cutoff = time.time() - retention_days * 86400
    pruned = 0
    if not os.path.exists(backup_dir):
        return 0

    for fname in os.listdir(backup_dir):
        fpath = os.path.join(backup_dir, fname)
        if not os.path.isfile(fpath):
            continue
        if os.path.getmtime(fpath) < cutoff:
            try:
                os.unlink(fpath)
                pruned += 1
            except OSError as e:
                logger.warning("Failed to prune %s: %s", fpath, e)

    if pruned:
        logger.info("Pruned %d old backup(s) (retention=%d days)", pruned, retention_days)
    return pruned


def upload_to_s3(backup_path: str, bucket: str, prefix: str = "backups/sqlite") -> bool:
    """Upload the backup file to an S3 bucket.

    Falls back to ``aws s3 cp`` CLI if boto3 is not available.
    """
    if not os.path.exists(backup_path):
        logger.error("Backup file not found: %s", backup_path)
        return False

    s3_key = f"{prefix}/{os.path.basename(backup_path)}"

    try:
        import boto3
        from botocore.exceptions import ClientError

        s3 = boto3.client("s3")
        s3.upload_file(backup_path, bucket, s3_key)
        logger.info("Uploaded to s3://%s/%s (%.1f MB)", bucket, s3_key, os.path.getsize(backup_path) / 1e6)
        return True

    except ImportError:
        # Fall back to AWS CLI
        logger.info("boto3 not available, using aws CLI for S3 upload")
        cmd = ["aws", "s3", "cp", backup_path, f"s3://{bucket}/{s3_key}"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info("Uploaded via aws CLI to s3://%s/%s", bucket, s3_key)
                return True
            else:
                logger.error("aws CLI upload failed: %s", result.stderr)
                return False
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.error("aws CLI upload failed: %s", e)
            return False

    except (OSError, ValueError, KeyError) as e:
        logger.error("S3 upload failed: %s", e)
        return False


def verify_backup(backup_path: str) -> bool:
    """Verify a backup file by restoring it to a temp location and checking integrity."""
    logger.info("Verifying backup: %s", backup_path)

    try:
        # Decompress if gzipped
        if backup_path.endswith(".gz"):
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                decompressed_path = tmp.name
            with gzip.open(backup_path, "rb") as f_in:
                with open(decompressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            decompressed_path = backup_path

        conn = sqlite3.connect(decompressed_path)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] == "ok":
                # Check that key tables exist
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                required = {"trades", "attribution", "equity_history", "strategy_metadata"}
                missing = required - tables
                if missing:
                    logger.warning("Backup missing tables: %s", missing)
                else:
                    logger.info("Backup verified OK (%d tables)", len(tables))
                    return True
            else:
                logger.error("Backup integrity check FAILED: %s", result)
                return False
        finally:
            conn.close()
        if decompressed_path != backup_path:
            os.unlink(decompressed_path)
    except (sqlite3.Error, OSError, ValueError) as e:
        logger.exception("Backup verification failed: %s", e)
        if decompressed_path != backup_path and os.path.exists(decompressed_path):
            os.unlink(decompressed_path)
        return False
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite database backup")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to state.db")
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, help="Backup directory")
    parser.add_argument("--retention", type=int, default=30, help="Days to keep backups")
    parser.add_argument("--compress", action="store_true", default=True, help="Gzip backup files")
    parser.add_argument("--no-compress", action="store_false", dest="compress", help="Skip compression")
    parser.add_argument("--s3-bucket", default="", help="S3 bucket for upload")
    parser.add_argument("--s3-prefix", default="backups/sqlite", help="S3 key prefix")
    parser.add_argument("--verify", action="store_true", help="Verify the latest backup")
    args = parser.parse_args()

    if args.verify:
        backups = sorted(glob.glob(os.path.join(args.backup_dir, "state.db.*")))
        if not backups:
            logger.error("No backups found in %s", args.backup_dir)
            return 1
        latest = backups[-1]
        if verify_backup(latest):
            return 0
        return 1

    # Create backup
    backup_path = create_backup(
        db_path=args.db_path,
        backup_dir=args.backup_dir,
        compress=args.compress,
    )
    if backup_path is None:
        return 1

    # Upload to S3 if configured
    if args.s3_bucket:
        upload_to_s3(backup_path, args.s3_bucket, args.s3_prefix)

    # Prune old backups
    prune_old_backups(args.backup_dir, args.retention)

    return 0


if __name__ == "__main__":
    sys.exit(main())
