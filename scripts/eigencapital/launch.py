#!/usr/bin/env python3
"""EigenCapital System Launcher — cross-platform replacement for ``monitor_all``.

Starts all EigenCapital processes in the correct order:
  1. MT5 terminal (platform-specific: Wine on Linux, native on Windows)
  2. MT5 bridge server
  3. Dashboard HTTP server (built-in)
  4. Trading engine main loop
  5. Model health monitor (optional, periodic)
  6. Slack alerter (optional)

Gracefully shuts down all processes on Ctrl+C / SIGINT / SIGTERM.

Usage:
    python -m scripts.eigencapital.launch [--no-mt5] [--no-dashboard] [--quiet]

Environment variables:
    MT5_BRIDGE_PORT    Bridge TCP port (default: 9879)
    MT5_ACCOUNT        MT5 account number
    MT5_PASSWORD       MT5 account password
    MT5_SERVER         MT5 server name
    SLACK_WEBHOOK_URL  Optional: Slack webhook for alerts
    EIGENCAPITAL_REFRESH_INTERVAL  Engine cycle interval in seconds (default: 60)
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
import threading
import time

from eigencapital.platform.detector import detect as _detect
from eigencapital.platform.mt5_bridge_manager import MT5BridgeManager, BridgeManagerConfig
from eigencapital.platform.process import wait_for_port
from eigencapital.platform.signals import ShutdownManager, install_graceful_shutdown

logger = logging.getLogger("eigencapital.launcher")

_DEFAULT_BRIDGE_PORT = 9879
_DEFAULT_HEALTH_PORT = 9880


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EigenCapital System Launcher")
    parser.add_argument("--no-mt5", action="store_true", help="Skip MT5 terminal and bridge startup")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard server")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    parser.add_argument("--bridge-port", type=int, default=_DEFAULT_BRIDGE_PORT, help="MT5 bridge TCP port")
    parser.add_argument("--health-port", type=int, default=_DEFAULT_HEALTH_PORT, help="Health check HTTP port")
    return parser.parse_args()


def _setup_logging(quiet: bool) -> None:
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _print_banner() -> None:
    plat = _detect()
    print("=" * 60)
    print("  EigenCapital Paper Trading System")
    print(f"  Platform: {plat.platform_tag}  Python: {plat.python_version}")
    print("=" * 60)
    print()


def _start_mt5_bridge(args: argparse.Namespace, shutdown: ShutdownManager) -> MT5BridgeManager | None:
    """Start the MT5 terminal and bridge, wait for readiness."""
    plat = _detect()
    if not plat.mt5_available and plat.is_linux and not plat.is_wine:
        logger.info("MT5 not available on this platform — skipping MT5 bridge startup")
        return None

    config = BridgeManagerConfig(
        bridge_port=args.bridge_port,
        health_port=args.health_port,
    )
    mgr = MT5BridgeManager(config=config, shutdown=shutdown)
    mgr.start()
    mgr.start_watchdog()
    return mgr


def _start_engine(shutdown: ShutdownManager) -> None:
    """Start the paper trading engine main loop."""
    from paper_trading.engine import PaperTradingEngine
    from paper_trading.governance.health import register_engine

    refresh = int(os.environ.get("EIGENCAPITAL_REFRESH_INTERVAL", "60"))
    engine = PaperTradingEngine()
    register_engine(engine)

    # Initial training
    for name, asset in engine.assets.items():
        if shutdown.is_set():
            return
        asset.train(force=False)

    logger.info("Engine initialised with %d assets", len(engine.assets))
    engine.save_state()

    # Main loop
    logger.info("Starting engine main loop (refresh=%ds)", refresh)
    while not shutdown.is_set():
        try:
            results = engine.run_once()
            engine.save_state()
            for name, r in results.items():
                if not isinstance(r, dict):
                    continue
                if "error" in r:
                    logger.error("%s: ERROR - %s", name, r["error"])
                elif "signal" in r:
                    logger.info(
                        "%s: %s  conf=%s%%  @ $%s",
                        name,
                        r["signal"],
                        r["confidence"],
                        r["close_price"],
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Error in engine cycle")

        if shutdown.wait(timeout=refresh):
            break

    engine.shutdown()
    logger.info("Engine stopped")


def _start_dashboard(shutdown: ShutdownManager) -> threading.Thread:
    """Start the dashboard HTTP server in a background thread."""
    from paper_trading.serve import serve

    thread = threading.Thread(
        target=serve,
        args=(5000, shutdown),
        daemon=True,
        name="qf-dashboard",
    )
    thread.start()

    # Wait a moment for the server to start
    time.sleep(1)
    logger.info("Dashboard: http://127.0.0.1:5000")
    return thread


def _start_slack_alerter(shutdown: ShutdownManager) -> threading.Thread | None:
    """Start the Slack alerter in a background thread if configured."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack alerter")
        return None

    def _run_alerter() -> None:
        from paper_trading.ops.slack_alerter import main as slack_main

        sys.argv = ["slack_alerter"]
        slack_main()

    thread = threading.Thread(target=_run_alerter, daemon=True, name="qf-slack-alerter")
    thread.start()
    logger.info("Slack alerter started")
    return thread


def _start_health_monitor(shutdown: ShutdownManager) -> threading.Thread | None:
    """Start the model health monitor in a background thread (6h interval)."""
    def _run_health_monitor() -> None:
        from scripts.ops.model_health_monitor import main as health_main

        sys.argv = ["model_health_monitor", "--loop", "21600"]
        try:
            health_main()
        except Exception:  # noqa: BLE001
            if not shutdown.is_set():
                logger.exception("Health monitor exited unexpectedly")

    thread = threading.Thread(target=_run_health_monitor, daemon=True, name="qf-health-monitor")
    thread.start()
    logger.info("Health monitor started (interval=6h)")
    return thread


def main() -> int:
    args = _parse_args()
    _setup_logging(args.quiet)
    _print_banner()

    shutdown = install_graceful_shutdown()
    threads: list[threading.Thread] = []
    bridge_mgr: MT5BridgeManager | None = None

    try:
        # Phase 1: MT5 terminal + bridge
        if not args.no_mt5:
            bridge_mgr = _start_mt5_bridge(args, shutdown)

        # Phase 2: Dashboard
        if not args.no_dashboard:
            dash_thread = _start_dashboard(shutdown)
            threads.append(dash_thread)

        # Phase 3: Slack alerter
        alerter = _start_slack_alerter(shutdown)
        if alerter:
            threads.append(alerter)

        # Phase 4: Health monitor
        monitor = _start_health_monitor(shutdown)
        if monitor:
            threads.append(monitor)

        # Phase 5: Engine main loop (runs in main thread)
        _start_engine(shutdown)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt — shutting down")
    except Exception:  # noqa: BLE001
        logger.exception("Fatal error in launcher")
        return 1
    finally:
        logger.info("Shutting down all components...")
        shutdown.trigger()

        if bridge_mgr is not None:
            bridge_mgr.stop()

        for t in threads:
            t.join(timeout=5)

    logger.info("All components stopped. Goodbye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
