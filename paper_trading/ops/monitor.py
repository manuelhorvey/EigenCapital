#!/usr/bin/env python3
"""EigenCapital Paper Trading Monitor — main entry point.

Starts the trading engine, dashboard server, and optional Slack alerter.
Uses cross-platform signal handling that works identically on Linux and Windows.

Usage:
    python -m paper_trading.ops.monitor
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
import time
import warnings

from eigencapital import setup_logging  # noqa: E402
from eigencapital.platform.signals import ShutdownManager  # noqa: E402
from paper_trading.engine import LOG_PATH, PaperTradingEngine  # noqa: E402
from paper_trading.governance.health import register_engine  # noqa: E402
from paper_trading.serve import serve  # noqa: E402

warnings.filterwarnings("ignore")

Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
logger = setup_logging(logging.INFO, log_file=LOG_PATH)

REFRESH_INTERVAL = int(os.environ.get("EIGENCAPITAL_REFRESH_INTERVAL") or 60)
_shutdown = ShutdownManager()


def main():
    _shutdown.install_handlers()

    engine = PaperTradingEngine()
    register_engine(engine)

    for name, asset in engine.assets.items():
        if _shutdown.is_set():
            return
        asset.train(force=False)

    if not _shutdown.is_set():
        logger.info("Pulling live data from yfinance...")
        engine.save_state()
        results = engine.run_once()
        engine.save_state()
        for name, r in results.items():
            if not isinstance(r, dict):
                continue
            if "error" in r:
                logger.error("%s: ERROR - %s", name, r["error"])
            elif "signal" in r:
                logger.info("%s: %s  conf=%s%%  @ $%s", name, r["signal"], r["confidence"], r["close_price"])
        p = engine.get_state()["portfolio"]
        logger.info("Portfolio: $%.2f (%s%%)", p["total_value"], p["total_return"])

    logger.info("Starting dashboard server...")

    server_thread = threading.Thread(target=serve, args=(5000, _shutdown), daemon=True)
    server_thread.start()
    time.sleep(1)
    logger.info("State API: http://127.0.0.1:5000/state.json")
    logger.info("Signals refresh every %d minutes from live yfinance data.", REFRESH_INTERVAL // 60)
    logger.info("Press Ctrl+C to stop.")

    try:
        while not _shutdown.is_set():
            interrupted = _shutdown.wait(REFRESH_INTERVAL)
            if interrupted:
                break
            logger.info("Refreshing signals...")
            try:
                engine.run_once()
                engine.save_state()
                logger.info("Done.")
            except Exception:
                logger.exception("Error in refresh cycle")
    finally:
        engine.shutdown()
    server_thread.join(timeout=3)
    logger.info("Server stopped.")


if __name__ == "__main__":
    main()
