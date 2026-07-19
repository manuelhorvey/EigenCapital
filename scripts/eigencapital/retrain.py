#!/usr/bin/env python3
"""EigenCapital Retrain Scheduler — cross-platform replacement for ``retrain_scheduler.sh``.

Runs the model retrain pipeline (``scripts/training/pipeline.py``) with:
  - Concurrency guard (lockfile)
  - Slack alerting on failure
  - Log rotation (90-day retention)
  - Pipeline report summarisation
  - Rollback on failure (--rollback flag)

Usage:
    python -m scripts.eigencapital.retrain [--dry-run]

Environment variables:
    RETRAIN_LOG_DIR   Override log directory (default: data/logs/retrain)
    SLACK_WEBHOOK_URL Optional: Slack webhook for failure alerts

Exit codes:
    0 — Pipeline succeeded
    1 — Pipeline failed (validation gates exceeded)
    2 — Script error (config issue, concurrent run)
"""

from __future__ import annotations

import argparse
import glob
import logging
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("eigencapital.retrain")


def _resolve_project_root() -> Path:
    """Resolve the project root from the script location."""
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _resolve_project_root()
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "retrain"
LOCKFILE = DEFAULT_LOG_DIR / "retrain.lock"
PIPELINE_SCRIPT = PROJECT_ROOT / "scripts" / "training" / "pipeline.py"


def _setup_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_path)),
            logging.StreamHandler(),
        ],
    )


def _acquire_lock(lockfile: Path) -> bool:
    """Try to acquire the retrain lock. Returns True if acquired."""
    try:
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        # Try creating lockfile atomically
        fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lockfile: Path) -> None:
    try:
        if lockfile.exists():
            lockfile.unlink()
    except OSError:
        pass


def _rotate_logs(log_dir: Path, retention_days: int = 90) -> None:
    """Remove log files older than *retention_days*."""
    cutoff = time.time() - retention_days * 86400
    for fpath in log_dir.glob("retrain_*.log"):
        try:
            if fpath.stat().st_mtime < cutoff:
                fpath.unlink()
        except OSError:
            pass


def _send_slack_alert(webhook_url: str, message: str) -> None:
    """Send a Slack alert via webhook."""
    try:
        import urllib.request

        payload = json.dumps({"text": message, "channel": "#ops-alerts", "username": "EigenCapital Retrain"}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
        logger.info("Slack alert sent")
    except Exception as e:  # noqa: BLE001
        logger.warning("Slack alert failed: %s", e)


def _parse_pipeline_report(report_path: Path) -> dict | None:
    """Parse a pipeline report JSON file and extract summary info."""
    try:
        data = json.loads(report_path.read_text())
        s = data.get("summary", {})
        return {
            "status": data.get("pipeline", {}).get("success", "?"),
            "pass": s.get("pass", 0),
            "warn": s.get("warn", 0),
            "fail": s.get("fail", 0),
            "total_r": s.get("total_R_sum_retrained", 0),
        }
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def _summarise_recent_reports(project_root: Path) -> list[dict]:
    """Summarise the last 3 pipeline reports."""
    reports = sorted(
        (project_root / "scripts" / "data" / "processed").glob("pipeline_report_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:3]

    summaries: list[dict] = []
    for rp in reports:
        info = _parse_pipeline_report(rp)
        if info:
            summaries.append({"path": rp.name, **info})
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="EigenCapital Retrain Scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no actual retrain)")
    args = parser.parse_args()

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_dir = Path(os.environ.get("RETRAIN_LOG_DIR", str(DEFAULT_LOG_DIR)))
    log_path = log_dir / f"retrain_{timestamp}.log"

    # Setup logging
    log_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(log_path)

    # Concurrency guard
    if not _acquire_lock(LOCKFILE):
        logger.warning("Previous retrain still running — exiting")
        return 0

    try:
        # Log rotation
        _rotate_logs(log_dir)

        logger.info("=" * 60)
        logger.info("EigenCapital Retrain Scheduler — %s", timestamp)
        logger.info("Project root: %s", PROJECT_ROOT)
        logger.info("Dry run: %s", args.dry_run)
        logger.info("=" * 60)

        # Build pipeline arguments
        pipeline_args = ["--rollback"]
        if args.dry_run:
            pipeline_args.append("--dry-run")

        # Run pipeline
        logger.info("Starting pipeline: python %s %s", PIPELINE_SCRIPT, " ".join(pipeline_args))
        pipeline_start = time.monotonic()

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}:{PROJECT_ROOT}"

        result = subprocess.run(
            [sys.executable, str(PIPELINE_SCRIPT)] + pipeline_args,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )

        pipeline_duration = time.monotonic() - pipeline_start
        pipeline_exit = result.returncode

        # Log output
        if result.stdout:
            logger.info("Pipeline stdout:\n%s", result.stdout)
        if result.stderr:
            logger.warning("Pipeline stderr:\n%s", result.stderr)

        logger.info("Pipeline finished: exit=%d duration=%.0fs", pipeline_exit, pipeline_duration)

        # Alert on failure
        if pipeline_exit != 0 and not args.dry_run:
            logger.error("ALERT: Pipeline failed (exit code %d)", pipeline_exit)
            webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
            if webhook:
                _send_slack_alert(
                    webhook,
                    f"[EigenCapital] Retrain pipeline FAILED at {timestamp}\n"
                    f"Exit code: {pipeline_exit}\n"
                    f"Duration: {pipeline_duration:.0f}s\n"
                    f"Log: {log_path}",
                )

            # Log a greppable failure marker
            logger.info("RETRAIN_FAILURE: %s exit=%d duration=%.0fs", timestamp, pipeline_exit, pipeline_duration)

        # Show recent reports
        reports = _summarise_recent_reports(PROJECT_ROOT)
        if reports:
            logger.info("Latest pipeline reports:")
            for r in reports:
                logger.info(
                    "  %s: %s  %sP/%sW/%sF  total_R=%.1f",
                    r["path"],
                    r["status"],
                    r["pass"],
                    r["warn"],
                    r["fail"],
                    r["total_r"],
                )

        logger.info("Done.")
        return pipeline_exit

    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 1 hour")
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        logger.error("Retrain scheduler failed: %s", e)
        return 2
    finally:
        _release_lock(LOCKFILE)


if __name__ == "__main__":
    sys.exit(main())
