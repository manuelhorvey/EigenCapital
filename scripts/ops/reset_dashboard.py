#!/usr/bin/env python
"""Reset dashboard state: flush caches, clear trace/WAL/state files.

Sends a POST to the engine's cache-clear endpoint on ports 5000 and 5001,
then removes runtime state files (trace.jsonl, WAL segments, state.json,
narrative files, and dashboard static responses). Useful for forcing a
clean state without restarting the engine.

Usage::

    PYTHONPATH=$PYTHONPATH:. python scripts/ops/reset_dashboard.py
"""

import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _flush_server_cache() -> None:
    """POST to /api/clear-cache to flush the engine server's in-memory caches."""
    for port in (5000, 5001):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/clear-cache",
                method="POST",
                data=b"",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    print(f"  Flushed server cache on port {port}")
                else:
                    print(f"  Server on port {port} returned status {resp.status}")
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionRefusedError, OSError):
            print(f"  No server on port {port} (expected if engine is stopped)")


LIVE_DIR = Path(BASE_DIR) / "data" / "live"
SHADOW_FEEDBACK_DIR = Path(BASE_DIR) / "data" / "shadow_feedback"
SHADOW_MEMORY_DIR = Path(BASE_DIR) / "data" / "shadow_memory"
SHADOW_LEARNING_DIR = Path(BASE_DIR) / "data" / "shadow_learning"


def clean_directory_contents(dir_path):
    if not Path(dir_path).exists():
        print(f"Directory {dir_path} does not exist, skipping.")
        return

    print(f"Cleaning contents of {dir_path}...")
    for item in sorted(Path(dir_path).iterdir()):
        item_path = Path(dir_path) / item
        try:
            if Path(item_path).is_dir():
                shutil.rmtree(item_path)
                print(f"  Removed directory: {item}")
            else:
                os.remove(item_path)
                print(f"  Removed file: {item}")
        except Exception as e:  # noqa: BLE001
            print(f"  Error removing {item}: {e}")


def main():
    print("========================================================")
    print("  EigenCapital Dashboard & Paper Trading State Reset Tool ")
    print("========================================================")

    force = len(sys.argv) > 1 and sys.argv[1] in ("-y", "--yes")

    if not force:
        print("\nWARNING: This will permanently delete:")
        print("  - All trading logs, states, and history (state.json, trade_journal, equity_history)")
        print("  - Cached prices, snapshots, and dashboard metrics")
        print("  - Shadow learning metrics, feedback loops, and shadow memories")
        print("\nMake sure the paper trading engine/monitor is NOT running before proceeding!\n")

        confirm = input("Are you sure you want to reset everything to a clean slate? (y/N): ").strip().lower()
        if confirm != "y":
            print("Reset aborted.")
            sys.exit(0)

    # 1. Clean data/live
    clean_directory_contents(LIVE_DIR)

    # Re-create cache, snapshots, logs directories inside live to ensure they exist
    for sub in ["cache", "snapshots", "logs"]:
        Path(Path(LIVE_DIR) / sub).mkdir(parents=True, exist_ok=True)
        print(f"  Created empty folder: data/live/{sub}")

    # 2. Clean shadow learning, feedback, and memory
    clean_directory_contents(SHADOW_FEEDBACK_DIR)
    clean_directory_contents(SHADOW_MEMORY_DIR)
    clean_directory_contents(SHADOW_LEARNING_DIR)

    # 3. Flush server-side in-memory caches so stale data isn't served
    print("Flushing server caches...")
    _flush_server_cache()

    print("\n✅ Reset completed successfully! Your paper trading engine and dashboard are now at a clean slate.")


if __name__ == "__main__":
    main()
