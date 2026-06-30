#!/usr/bin/env python3
import logging
import os
import signal as sigmod
import threading
import time
import warnings

from paper_trading.engine import LOG_PATH, PaperTradingEngine  # noqa: E402
from paper_trading.governance.health import register_engine  # noqa: E402
from paper_trading.serve import serve  # noqa: E402
from quorrin import setup_logging  # noqa: E402

warnings.filterwarnings("ignore")

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logger = setup_logging(logging.INFO, log_file=LOG_PATH)

REFRESH_INTERVAL = int(os.environ.get("QUORRIN_REFRESH_INTERVAL") or 60)
_shutdown = threading.Event()


def _signal_handler(signum, frame):
    _shutdown.set()


def main():
    sigmod.signal(sigmod.SIGTERM, _signal_handler)
    sigmod.signal(sigmod.SIGINT, _signal_handler)

    engine = PaperTradingEngine()
    register_engine(engine)

    for name, asset in engine.assets.items():
        if _shutdown.is_set():
            return
        asset.train(force=False)

    if not _shutdown.is_set():
        logger.info("Pulling live data from yfinance...")
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
            except Exception as e:
                logger.error("Error: %s", e)
    finally:
        engine.shutdown()
    server_thread.join(timeout=3)
    logger.info("Server stopped.")


if __name__ == "__main__":
    main()
