#!/usr/bin/env python3
"""Retrain ALL assets using the fixed AssetTrainingPipeline.

Applies fixes:
  1. day_of_week_signal look-ahead removed
  2. vertical_barrier read from contract (not hardcoded 10)
  3. scale_pos_weight added to XGBClassifier
  4. DXY/VIX/SPX features included in backtest
  5. Embargo gap >= vertical_barrier
  6. Conviction gate debug log
  7. Ensemble dead config removed
  8. COT has_cot flag + zero-fill

After production models are trained, also regenerates per-asset canary shadow
models via ``train_canary.py`` so the shadow-comparison infrastructure stays
in sync (unless ``--skip-canary`` is passed).

Output: paper_trading/models/{name}_model.json per asset
        data/processed/training_report_{timestamp}.csv
        paper_trading/models/canary/{name}.json (canary models)
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime

import pandas as pd
import pytz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("retrain_all")

BASE = PROJECT_ROOT
MODEL_DIR = os.path.join(BASE, "paper_trading", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

ET = pytz.timezone("US/Eastern")


def main(skip_canary: bool = False, canary_only: bool = False):
    # Ensure data fetcher has a no-op store so yfinance can serve as the
    # data source during offline training (no live engine running).
    from paper_trading.ops.data_fetcher import _set_store

    class _NullStore:
        def save_cache(self, *args, **kwargs): pass
        def load_cache(self, *args, **kwargs): return None
        def cache_path(self, *args, **kwargs): return "/dev/null"

    _set_store(_NullStore())

    from paper_trading.asset_engine_factory import build_asset_engine
    from paper_trading.config_manager import get_config
    from paper_trading.execution.bridge import ExecutionBridge
    from paper_trading.execution.paper_broker import PaperBroker
    from paper_trading.execution_context import ExecutionContext
    from paper_trading.portfolio_builder import build_paper_portfolio

    cfg = get_config()
    logger.info("Loaded config: capital=%s, retrain_freq=%s", cfg.capital, cfg.retrain_freq)

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

    results = []
    assets_to_train = list(portfolio.keys())
    n_total = len(assets_to_train)

    # ── Pre-fetch full panel for cross-sectional features ────────────
    # When EIGENCAPITAL_EXPANDED_DATA_DIR is set (or a 10y cache is present
    # under data/yfinance_10yr/), read the panel from cached parquets
    # instead of live yfinance — broader history, monotonically noisier
    # data path, no live fetch delays.
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _data_sources import build_expanded_full_panel, resolve_expanded_dir

    _expanded_dir = resolve_expanded_dir()
    full_panel = build_expanded_full_panel(dict(portfolio), expanded_dir=_expanded_dir)
    if _expanded_dir is not None:
        logger.info(
            "Using 10-year expanded cache at %s — full panel: %d assets × %d rows (%s..%s)",
            _expanded_dir,
            len(full_panel.columns),
            len(full_panel),
            full_panel.index[0].date() if len(full_panel) else "n/a",
            full_panel.index[-1].date() if len(full_panel) else "n/a",
        )
    else:
        logger.info(
            "No expanded cache — using live yfinance path. "
            "Full panel: %d assets × %d rows.",
            len(full_panel.columns),
            len(full_panel),
        )
        from features.data_fetch import fetch_asset_data

        # Live fallback (already computed in full_panel, but resolv the
        # legacy behaviour explicitly so this branch mirrors the original
        # script verbatim).

    logger.info("=== RETRAINING %d ASSETS (fixed pipeline) ===", n_total)

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
            engine._trained = True  # will retrain

            t0 = time.perf_counter()
            engine._training.train(
                force=True,
                full_panel=full_panel,
                expanded_data_dir=str(_expanded_dir) if _expanded_dir else None,
            )
            elapsed = time.perf_counter() - t0

            if engine._trained and engine.model is not None:
                # Read back the training metrics
                vb = engine.contract.label_params.get("vertical_barrier", "N/A")
                tp = engine.tp_mult
                sl = engine.sl_mult

                results.append(
                    {
                        "asset": name,
                        "ticker": ticker,
                        "vertical_barrier": vb,
                        "tp_mult": tp,
                        "sl_mult": sl,
                        "max_depth": engine.max_depth,
                        "n_features": len(getattr(engine, "_alpha_feature_cols", [])),
                        "train_start": getattr(engine, "_current_window_train_start", ""),
                        "train_end": getattr(engine, "_current_window_train_end", ""),
                        "train_time_s": round(elapsed, 1),
                        "model_path": engine.model_path,
                        "status": "OK",
                    }
                )
                logger.info(
                    "  ✓ %s: trained in %.1fs (vb=%s, %d features, tp=%.2f, sl=%.2f)",
                    name,
                    elapsed,
                    vb,
                    results[-1]["n_features"],
                    tp,
                    sl,
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
    report_path = os.path.join(BASE, "data", "processed", f"training_report_{ts}.csv")
    report_df = pd.DataFrame(results)
    report_df.to_csv(report_path, index=False)

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    fail_count = n_total - ok_count

    print("\n" + "=" * 80)
    print(f"TRAINING REPORT — {ts}")
    print("=" * 80)
    print(f"  Total: {n_total}  OK: {ok_count}  Failed: {fail_count}")
    if ok_count:
        print("\nTrained assets:")
        print(
            report_df[report_df["status"] == "OK"][
                ["asset", "vertical_barrier", "n_features", "train_time_s"]
            ].to_string(index=False)
        )
    if fail_count:
        print("\nFailed assets:")
        print(report_df[report_df["status"] != "OK"][["asset", "status"]].to_string(index=False))
    print(f"\nReport saved: {report_path}")
    print("=" * 80)

    # ── Canary model training (after production retrain) ─────────────────
    if not skip_canary:
        _run_canary_after_retrain()


def _run_canary_after_retrain() -> None:
    """Subprocess train_canary.py to regenerate shadow-comparison models."""
    # train_canary.py lives in the same directory as retrain_all_fixed.py
    canary_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "train_canary.py")
    logger.info("=" * 60)
    logger.info("Regenerating canary shadow models...")
    logger.info("=" * 60)
    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, canary_script],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(BASE),
    )
    elapsed = time.perf_counter() - t0
    for line in result.stdout.splitlines():
        if any(kw in line for kw in ("✓", "✗", "ERROR", "CANARY TRAINING REPORT", "OK:", "Failed:")):
            logger.info("[CANARY] %s", line.strip())
    logger.info("Canary models regenerated in %.1fs", elapsed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Retrain all production models + regenerate canary shadow models",
    )
    parser.add_argument(
        "--skip-canary",
        action="store_true",
        help="Skip canary shadow model regeneration after production retrain",
    )
    parser.add_argument(
        "--canary-only",
        action="store_true",
        help="Only regenerate canary shadow models (skip production retrain)",
    )
    args = parser.parse_args()

    if args.canary_only:
        logger.info("=== CANARY-ONLY MODE — regenerating shadow models ===")
        _run_canary_after_retrain()
    else:
        main(skip_canary=args.skip_canary)
