#!/usr/bin/env python3
"""Prune data files older than configured retention periods.

Per-type retention defaults (tuned for ~30MB/day total accumulation):
  - trace.jsonl:        30 days  (debug surface, recent only)
  - wal/engine.jsonl:   90 days  (audit trail, replay chain)
  - engine.log:         14 days  (live debugging, rotate fast)
  - shadow_feedback/:   90 days  (quarterly drift analysis)
  - shadow_memory/:     60 days  (biggest consumer, trim sooner)
  - equity_history:     90 days  (live Sharpe/equity curve)

Usage (CLI):
    # Dry-run
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/prune_data.py

    # Live run
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/prune_data.py --apply

Usage (programmatic — called by engine every cycle):
    from scripts.ops.prune_data import prune_all
    stats = prune_all(apply=True)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("prune_data")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Paths
LIVE_DIR = os.path.join(BASE, "data", "live")
WAL_DIR = os.path.join(LIVE_DIR, "wal")
SHADOW_FEEDBACK_DIR = os.path.join(BASE, "data", "shadow_feedback")
SHADOW_MEMORY_DIR = os.path.join(BASE, "data", "shadow_memory")
STATE_DB = os.path.join(LIVE_DIR, "state.db")

# Per-type retention in days
RETENTION: dict[str, int] = {
    "trace.jsonl": 30,
    "wal/engine.jsonl": 90,
    "engine.log": 14,
    "shadow_feedback": 90,
    "shadow_memory": 60,
    "equity_history": 90,
}

# Timestamp regex for engine.log lines: "2026-06-26 09:16:51 ..."
LOG_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}")


def parse_timestamp_iso(ts_str: str) -> datetime | None:
    """Parse ISO 8601 timestamp, handling optional timezone offset.

    trace.jsonl timestamps are naive (no TZ):  ``2026-06-26T09:17:11.363450``
    wal/engine.jsonl timestamps are aware:    ``2026-06-26T09:16:52.060911+00:00``
    equity_history timestamps have TZ offset: ``2026-06-26T05:17:54.493845-04:00``
    The cutoff is always aware (``datetime.now(timezone.utc)``).

    To avoid ``TypeError: can't compare offset-naive and offset-aware``,
    naive timestamps are assumed to be UTC and made aware.
    """
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def prune_jsonl(
    path: str,
    cutoff: datetime,
    *,
    apply: bool,
    dry_run_stats: dict,
    label: str,
) -> None:
    """Prune lines in a JSONL file where the timestamp is older than cutoff."""
    if not os.path.isfile(path):
        return

    total = 0
    kept = 0
    pruned = 0
    temp_path = path + ".tmp"

    try:
        with open(path) as fin, open(temp_path, "w") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    record = json.loads(line)
                    ts_str = record.get("timestamp", "")
                    ts = parse_timestamp_iso(ts_str)
                    if ts is not None and ts < cutoff:
                        pruned += 1
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass
                fout.write(line + "\n")
                kept += 1
    except OSError as e:
        logger.error("Failed to read %s: %s", path, e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return

    if apply:
        os.replace(temp_path, path)
    else:
        os.remove(temp_path)

    dry_run_stats[label] = {"total": total, "kept": kept, "pruned": pruned}


def prune_log(path: str, cutoff: datetime, *, apply: bool, dry_run_stats: dict) -> None:
    """Prune lines in a log file where the date prefix is older than cutoff."""
    if not os.path.isfile(path):
        return

    total = 0
    kept = 0
    pruned = 0
    temp_path = path + ".tmp"

    try:
        with open(path) as fin, open(temp_path, "w") as fout:
            for line in fin:
                total += 1
                m = LOG_TIMESTAMP_RE.match(line)
                if m:
                    try:
                        line_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if line_date < cutoff:
                            pruned += 1
                            continue
                    except ValueError:
                        pass
                fout.write(line)
                kept += 1
    except OSError as e:
        logger.error("Failed to read %s: %s", path, e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return

    if apply:
        os.replace(temp_path, path)
    else:
        os.remove(temp_path)

    dry_run_stats["engine_log"] = {"total": total, "kept": kept, "pruned": pruned}


def prune_date_files(
    root_dir: str,
    date_format: str,
    *,
    apply: bool,
    cutoff: datetime,
    dry_run_stats: dict,
    label: str,
) -> None:
    """Prune files in subdirectories where the filename encodes a date."""
    if not os.path.isdir(root_dir):
        return

    total_files = 0
    total_size = 0
    pruned_files = 0
    pruned_size = 0

    for asset_name in sorted(os.listdir(root_dir)):
        asset_dir = os.path.join(root_dir, asset_name)
        if not os.path.isdir(asset_dir):
            continue
        for fname in sorted(os.listdir(asset_dir)):
            if not fname.endswith(".jsonl"):
                continue
            date_str = fname.replace(".jsonl", "")
            try:
                fdate = datetime.strptime(date_str, date_format).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            total_files += 1
            fpath = os.path.join(asset_dir, fname)
            try:
                fsize = os.path.getsize(fpath)
                total_size += fsize
            except OSError:
                fsize = 0

            if fdate < cutoff:
                pruned_files += 1
                pruned_size += fsize
                if apply:
                    try:
                        os.remove(fpath)
                        logger.debug("Removed %s", fpath)
                    except OSError as e:
                        logger.error("Failed to remove %s: %s", fpath, e)

    remaining_files = total_files - pruned_files
    remaining_size = total_size - pruned_size
    dry_run_stats[label] = {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "pruned_files": pruned_files,
        "pruned_size_bytes": pruned_size,
        "remaining_files": remaining_files,
        "remaining_size_bytes": remaining_size,
    }


def prune_equity_history(
    cutoff: datetime,
    *,
    apply: bool,
    dry_run_stats: dict,
) -> None:
    """Delete equity_history rows where timestamp is older than cutoff.

    After deletion, runs VACUUM to reclaim space since SQLite does not
    automatically shrink the database file on DELETE.
    """
    if not os.path.isfile(STATE_DB):
        return

    try:
        import sqlite3

        conn = sqlite3.connect(STATE_DB)
        conn.row_factory = sqlite3.Row

        # Count total rows
        total = conn.execute("SELECT COUNT(*) FROM equity_history").fetchone()[0]

        # Find rows older than cutoff by parsing the ISO timestamp column
        rows = conn.execute("SELECT id, timestamp FROM equity_history ORDER BY id ASC").fetchall()
        to_delete: list[int] = []
        for row in rows:
            ts = parse_timestamp_iso(row["timestamp"])
            if ts is not None and ts < cutoff:
                to_delete.append(row["id"])

        pruned = len(to_delete)
        kept = total - pruned

        if pruned > 0 and apply:
            ids_str = ",".join(str(i) for i in to_delete)
            conn.execute(f"DELETE FROM equity_history WHERE id IN ({ids_str})")
            conn.execute("VACUUM")
            logger.info("Deleted %d equity_history rows, vacuumed DB", pruned)

        conn.close()

        dry_run_stats["equity_history"] = {
            "total": total,
            "kept": kept,
            "pruned": pruned,
        }

    except Exception as e:  # noqa: BLE001
        logger.error("Failed to prune equity_history: %s", e)
        dry_run_stats["equity_history"] = {"error": str(e)}


def _fmt_size(bytes_val: int) -> str:
    """Format bytes to human-readable string."""
    if bytes_val < 1024:
        return f"{bytes_val}B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f}K"
    else:
        return f"{bytes_val / (1024 * 1024):.1f}M"


def prune_all(
    apply: bool = False,
    retention: dict[str, int] | None = None,
) -> dict[str, object]:
    """Prune all data files using per-type retention configs.

    Called automatically by the engine once per day.

    Args:
        apply: If True, actually delete/prune files. Default False (dry-run).
        retention: Override per-type retention in days. Defaults to RETENTION.

    Returns:
        Stats dict with per-key prune results.
    """
    if retention is None:
        retention = RETENTION

    now = datetime.now(timezone.utc)
    stats: dict[str, object] = {}

    # 1. trace.jsonl — 30 days
    trace_days = retention.get("trace.jsonl", 30)
    cutoff = now - timedelta(days=trace_days)
    prune_jsonl(
        os.path.join(LIVE_DIR, "trace.jsonl"),
        cutoff,
        apply=apply,
        dry_run_stats=stats,
        label="trace.jsonl",
    )

    # 2. wal/engine.jsonl — 90 days
    wal_days = retention.get("wal/engine.jsonl", 90)
    cutoff = now - timedelta(days=wal_days)
    prune_jsonl(
        os.path.join(WAL_DIR, "engine.jsonl"),
        cutoff,
        apply=apply,
        dry_run_stats=stats,
        label="wal/engine.jsonl",
    )

    # 3. engine.log — 14 days
    log_days = retention.get("engine.log", 14)
    cutoff = now - timedelta(days=log_days)
    prune_log(
        os.path.join(LIVE_DIR, "engine.log"),
        cutoff,
        apply=apply,
        dry_run_stats=stats,
    )

    # 4. shadow_feedback — 90 days (monthly files)
    fb_days = retention.get("shadow_feedback", 90)
    cutoff_date = (now - timedelta(days=fb_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    prune_date_files(
        SHADOW_FEEDBACK_DIR,
        "%Y-%m",
        apply=apply,
        cutoff=cutoff_date,
        dry_run_stats=stats,
        label="shadow_feedback",
    )

    # 5. shadow_memory — 60 days (daily files)
    mem_days = retention.get("shadow_memory", 60)
    cutoff_date = (now - timedelta(days=mem_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    prune_date_files(
        SHADOW_MEMORY_DIR,
        "%Y-%m-%d",
        apply=apply,
        cutoff=cutoff_date,
        dry_run_stats=stats,
        label="shadow_memory",
    )

    # 6. equity_history — 90 days (SQLite)
    eq_days = retention.get("equity_history", 90)
    cutoff = now - timedelta(days=eq_days)
    prune_equity_history(
        cutoff,
        apply=apply,
        dry_run_stats=stats,
    )

    return stats


def print_summary(stats: dict, apply: bool) -> None:
    """Print a human-readable summary of what was done."""
    action = "PRUNED" if apply else "WOULD PRUNE (dry-run)"
    print(f"\n{'=' * 60}")
    print(f"  {action} SUMMARY")
    print(f"{'=' * 60}")

    total_pruned = 0
    total_freed = 0

    for key, data in sorted(stats.items()):
        if "error" in data:
            print(f"  {key:30s}  ERROR: {data['error']}")
        elif "pruned" in data:
            n = data["pruned"]
            total_pruned += n
            print(f"  {key:30s}  {n:>6d} rows removed")
        elif "pruned_files" in data:
            n = data["pruned_files"]
            size = data["pruned_size_bytes"]
            total_pruned += n
            total_freed += size
            print(f"  {key:30s}  {n:>6d} files removed  ({_fmt_size(size)} freed)")

    print(f"  {'─' * 50}")
    print(f"  {'TOTAL':30s}  {total_pruned:>6d} items  ({_fmt_size(total_freed)} freed)")
    print()


def main():
    parser = argparse.ArgumentParser(description="Prune data files older than N days")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override: single retention period for all types (default: per-type config)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files (default: dry-run only)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    retention = {k: args.days for k in RETENTION} if args.days else None
    logger.info("Retention: %s", "per-type config" if retention is None else f"flat {args.days}d")
    logger.info("Mode: %s", "LIVE (--apply)" if args.apply else "DRY-RUN")
    print()

    stats = prune_all(apply=args.apply, retention=retention)
    print_summary(stats, args.apply)

    if not args.apply:
        print("  Run with --apply to execute pruning.")
        print()


if __name__ == "__main__":
    main()
