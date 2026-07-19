#!/usr/bin/env python3
"""Retrain 5 underperforming assets with fresh OHLCV cache."""

import logging
from pathlib import Path
import sys
import time
from datetime import datetime

sys.path.insert(0, Path(__file__).resolve().parent.parent)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("retrain_5")

from paper_trading.asset_engine_factory import build_asset_engine
from paper_trading.config_manager import get_config
from paper_trading.execution.bridge import ExecutionBridge
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution_context import ExecutionContext
from paper_trading.portfolio_builder import build_paper_portfolio

ASSETS = ["AUDJPY", "NZDJPY", "BTCUSD", "GBPJPY", "NZDCAD"]

def main():
    cfg = get_config()
    broker = PaperBroker(initial_capital=cfg.capital, execution_configs={})
    bridge = ExecutionBridge(broker, is_real_broker=False)
    ctx = ExecutionContext(state_store=None, execution_bridge=bridge, engine_config=cfg)

    from shared.registry import StrategyRegistry
    _reg = StrategyRegistry.get_instance()
    portfolio = build_paper_portfolio(cfg.halt)
    _reg.register_defaults(list(portfolio.keys()))

    results = []
    for name in ASSETS:
        if name not in portfolio:
            logger.warning("  SKIP %s: not in portfolio", name)
            continue
        spec = portfolio[name]
        ticker = spec["ticker"]

        logger.info("=== %s (%s) ===", name, ticker)
        try:
            engine = build_asset_engine(
                ticker=ticker,
                name=name,
                contract=spec["contract"],
                allocation=spec["alloc"],
                halt_config=spec["halt"],
                config=spec["config"],
                sl_mult=spec.get("sl_mult", 1.0),
                tp_mult=spec.get("tp_mult", 2.5),
                max_depth=spec.get("max_depth", 2),
                regime_geometry=spec.get("regime_geometry", {}),
                context=ctx,
            )
            engine._trained = True
            t0 = time.perf_counter()
            engine._training.train(force=True)
            elapsed = time.perf_counter() - t0

            if engine._trained and engine.model is not None:
                results.append({"asset": name, "status": "OK", "time_s": round(elapsed, 1)})
                logger.info("  OK in %.1fs", elapsed)
            else:
                results.append({"asset": name, "status": "NO_MODEL", "time_s": round(elapsed, 1)})
                logger.warning("  NO_MODEL")
        except Exception as e:
            logger.error("  ERROR: %s", e)
            import traceback
            traceback.print_exc()
            results.append({"asset": name, "status": f"ERROR: {e}", "time_s": 0})

    print("\n" + "=" * 60)
    for r in results:
        print(f"  {r['asset']:8s}: {r['status']} ({r.get('time_s', 0):.1f}s)")
    print("=" * 60)

if __name__ == "__main__":
    main()
