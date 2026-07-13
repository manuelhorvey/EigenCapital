#!/usr/bin/env python3
"""Train per-asset canary models for shadow comparison.

Trains an XGBoost model per asset using the same pipeline as production
but saves the model files to ``paper_trading/models/canary/{ASSET}.json``
so the shadow model infrastructure can load and compare them side-by-side
with live production inference.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/training/train_canary.py

Output:
    paper_trading/models/canary/{ASSET}.json  — per-asset canary model
    data/processed/canary_report_{timestamp}.csv
"""

import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_canary")

# Go up three levels: scripts/training/ -> scripts/ -> project root
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANARY_DIR = os.path.join(BASE, "paper_trading", "models", "canary")
os.makedirs(CANARY_DIR, exist_ok=True)


def main() -> None:
    # Ensure data fetcher has a no-op store so yfinance can serve as the
    # data source during offline training (no live engine running).
    from paper_trading.ops.data_fetcher import _set_store

    class _NullStore:
        def save_cache(self, *args, **kwargs):
            pass

        def load_cache(self, *args, **kwargs):
            return None

        def cache_path(self, *args, **kwargs):
            return "/dev/null"

    _set_store(_NullStore())

    from paper_trading.asset_engine_factory import build_asset_engine
    from paper_trading.config_manager import get_config
    from paper_trading.execution.bridge import ExecutionBridge
    from paper_trading.execution.paper_broker import PaperBroker
    from paper_trading.execution_context import ExecutionContext
    from paper_trading.portfolio_builder import build_paper_portfolio

    cfg = get_config()
    logger.info("Loaded config: capital=%s", cfg.capital)

    broker = PaperBroker(
        initial_capital=cfg.capital,
        execution_configs={},
    )
    bridge = ExecutionBridge(broker, is_real_broker=False)
    ctx = ExecutionContext(
        state_store=None,
        execution_bridge=bridge,
        engine_config=cfg,
    )

    from shared.registry import StrategyRegistry

    _reg = StrategyRegistry.get_instance()
    portfolio = build_paper_portfolio(cfg.halt)
    _reg.register_defaults(list(portfolio.keys()))

    # ── Pre-fetch full panel for cross-sectional features ────────────
    # When EIGENCAPITAL_EXPANDED_DATA_DIR is set (or data/yfinance_10yr/
    # exists), read the panel from cached parquets via the shared helper
    # at scripts/training/_data_sources.py.
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _data_sources import build_expanded_full_panel, resolve_expanded_dir

    _expanded_dir = resolve_expanded_dir()
    full_panel = build_expanded_full_panel(dict(portfolio), expanded_dir=_expanded_dir)

    results = []
    assets_to_train = sorted(portfolio.keys())
    n_total = len(assets_to_train)

    logger.info("=== TRAINING %d CANARY MODELS ===", n_total)

    for idx, name in enumerate(assets_to_train, 1):
        spec = portfolio[name]
        ticker = spec["ticker"]

        logger.info("[%d/%d] %s (%s) — building engine...", idx, n_total, name, ticker)

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

            # Override model_path to canary directory
            canary_path = os.path.join(CANARY_DIR, f"{name}.json")
            engine.model_path = canary_path
            engine._trained = True  # force retrain

            t0 = time.perf_counter()
            engine._training.train(
                force=True,
                full_panel=full_panel,
                expanded_data_dir=str(_expanded_dir) if _expanded_dir else None,
            )
            elapsed = time.perf_counter() - t0

            if engine._trained and engine.model is not None:
                # Verify the file exists
                file_size = os.path.getsize(canary_path) if os.path.exists(canary_path) else 0
                results.append(
                    {
                        "asset": name,
                        "ticker": ticker,
                        "model_path": canary_path,
                        "file_size_bytes": file_size,
                        "train_time_s": round(elapsed, 1),
                        "status": "OK",
                    }
                )
                logger.info(
                    "  ✓ %s: trained in %.1fs → %s (%d bytes)",
                    name,
                    elapsed,
                    canary_path,
                    file_size,
                )
            else:
                results.append(
                    {
                        "asset": name,
                        "ticker": ticker,
                        "status": "FAILED",
                        "train_time_s": round(elapsed, 1),
                    }
                )
                logger.warning("  ✗ %s: training returned no model", name)

        except Exception as e:  # noqa: BLE001
            logger.error("  ✗ %s: ERROR — %s", name, e)
            import traceback

            traceback.print_exc()
            results.append(
                {
                    "asset": name,
                    "ticker": ticker,
                    "status": f"ERROR: {e}",
                }
            )

    # Save report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(BASE, "data", "processed", f"canary_report_{ts}.csv")
    report_df = pd.DataFrame(results)
    report_df.to_csv(report_path, index=False)

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    fail_count = n_total - ok_count

    print("\n" + "=" * 80)
    print(f"CANARY TRAINING REPORT — {ts}")
    print("=" * 80)
    print(f"  Total: {n_total}  OK: {ok_count}  Failed: {fail_count}")
    if ok_count:
        print("\nTrained canary models:")
        for r in results:
            if r.get("status") == "OK":
                print(f"  ✓ {r['asset']}: {r['model_path']} ({r['file_size_bytes']} bytes, {r['train_time_s']}s)")
    if fail_count:
        print("\nFailed:")
        for r in results:
            if r.get("status") != "OK":
                print(f"  ✗ {r['asset']}: {r['status']}")
    print(f"\nReport saved: {report_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
