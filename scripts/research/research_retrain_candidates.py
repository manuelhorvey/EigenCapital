#!/usr/bin/env python3
"""
Production-pipeline retrain on 7 promising candidates.
Models saved to paper_trading/models/research/ — NOT live models.
Reports training metrics and asks before any config changes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("research_retrain")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Research model dir — NOT the live models directory
RESEARCH_MODEL_DIR = os.path.join(BASE, "paper_trading", "models", "research")
os.makedirs(RESEARCH_MODEL_DIR, exist_ok=True)

ET = pytz.timezone("US/Eastern")

CANDIDATES = [
    {"name": "VIX", "ticker": "^VIX", "tp_mult": 1.5, "sl_mult": 1.5, "ensemble_threshold": 0.15, "max_depth": 2},
    {"name": "EURAUD", "ticker": "EURAUD=X", "tp_mult": 1.77, "sl_mult": 0.54, "ensemble_threshold": 0.20, "max_depth": 2},
    {"name": "GBPUSD", "ticker": "GBPUSD=X", "tp_mult": 0.52, "sl_mult": 1.97, "ensemble_threshold": 0.05, "max_depth": 2},
    {"name": "AUDJPY", "ticker": "AUDJPY=X", "tp_mult": 0.52, "sl_mult": 2.01, "ensemble_threshold": 0.05, "max_depth": 2},
    {"name": "CADJPY", "ticker": "CADJPY=X", "tp_mult": 0.52, "sl_mult": 1.65, "ensemble_threshold": 0.05, "max_depth": 2},
    {"name": "USDJPY", "ticker": "USDJPY=X", "tp_mult": 0.52, "sl_mult": 1.97, "ensemble_threshold": 0.05, "max_depth": 2},
    {"name": "NZDJPY", "ticker": "NZDJPY=X", "tp_mult": 0.51, "sl_mult": 2.02, "ensemble_threshold": 0.05, "max_depth": 2},
]


def build_contract(name: str, ticker: str) -> object:
    from features.registry import FEATURE_REGISTRY
    contract = FEATURE_REGISTRY.get(ticker)
    if contract is None:
        logger.error("No contract for %s (%s)", name, ticker)
        raise ValueError(f"No contract for {ticker}")
    return contract


def main():
    from paper_trading.config_manager import get_config
    from paper_trading.execution.bridge import ExecutionBridge
    from paper_trading.execution.paper_broker import PaperBroker
    from paper_trading.execution_context import ExecutionContext
    from paper_trading.asset_engine_factory import build_asset_engine
    from features.registry import FEATURE_REGISTRY
    from shared.registry import StrategyRegistry

    cfg = get_config()
    broker = PaperBroker(initial_capital=cfg.capital, execution_configs={})
    bridge = ExecutionBridge(broker, is_real_broker=False)
    ctx = ExecutionContext(state_store=None, execution_bridge=bridge, engine_config=cfg)

    _reg = StrategyRegistry.get_instance()
    # Register defaults for all candidates so the registry has entries
    _reg.register_defaults([c["name"] for c in CANDIDATES])

    results = []
    for cand in CANDIDATES:
        name = cand["name"]
        ticker = cand["ticker"]
        tp_mult = cand["tp_mult"]
        sl_mult = cand["sl_mult"]
        et = cand["ensemble_threshold"]
        depth = cand.get("max_depth", 2)

        logger.info("=== %s (%s) — tp=%.2f sl=%.2f et=%.2f depth=%d ===",
                     name, ticker, tp_mult, sl_mult, et, depth)

        contract = build_contract(name, ticker)
        if contract is None:
            continue

        try:
            engine = build_asset_engine(
                ticker=ticker,
                name=name,
                contract=contract,
                allocation=0.0,
                halt_config={},
                config={},
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                max_depth=depth,
                regime_geometry={},
                context=ctx,
            )
            # Override model path to research directory
            engine.model_path = os.path.join(RESEARCH_MODEL_DIR, f"{contract.name}_model.json")
            # Set ensemble config for regime model training
            engine.config.setdefault("ensemble", {})["base_weight"] = 0.6
            engine.config.setdefault("ensemble", {})["threshold"] = et
            engine._trained = True  # will retrain (force=True below)

            t0 = time.perf_counter()
            engine._training.train(force=True)
            elapsed = time.perf_counter() - t0

            if engine._trained and engine.model is not None:
                # Gather metrics
                vb = getattr(engine.contract.label_params, "vertical_barrier", 20)
                if isinstance(engine.contract.label_params, dict):
                    vb = engine.contract.label_params.get("vertical_barrier", 20)
                elif hasattr(engine.contract, "label_params"):
                    vb = getattr(engine.contract.label_params, "vertical_barrier", 20)

                results.append({
                    "asset": name,
                    "ticker": ticker,
                    "tp_mult": tp_mult,
                    "sl_mult": sl_mult,
                    "ensemble_threshold": et,
                    "max_depth": depth,
                    "vertical_barrier": vb,
                    "n_features": len(getattr(engine, "_alpha_feature_cols", [])),
                    "n_regime_features": len(getattr(engine, "regime_feature_names", [])),
                    "has_regime_model": getattr(engine, "_regime_model", None) is not None,
                    "has_ensemble": getattr(engine, "_ensemble", None) is not None,
                    "train_time_s": round(elapsed, 1),
                    "model_path": engine.model_path,
                    "status": "OK",
                })
                logger.info("  ✓ %s: trained in %.1fs (%d features, %d regime features, tp=%.2f, sl=%.2f)",
                            name, elapsed, results[-1]["n_features"],
                            results[-1]["n_regime_features"], tp_mult, sl_mult)
            else:
                results.append({"asset": name, "ticker": ticker, "status": "FAILED",
                                "train_time_s": round(elapsed, 1)})
                logger.warning("  ✗ %s: training returned no model", name)

        except Exception as e:
            logger.error("  ✗ %s: ERROR — %s", name, e)
            import traceback
            traceback.print_exc()
            results.append({"asset": name, "ticker": ticker, "status": f"ERROR: {e}"})

    # Save report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(BASE, "data", "processed", f"research_retrain_{ts}.csv")
    report_df = pd.DataFrame(results)
    report_df.to_csv(report_path, index=False)

    # Also save as JSON for easy reading
    report_json_path = os.path.join(RESEARCH_MODEL_DIR, "research_retrain_results.json")
    report_json = []
    for r in results:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (pd.Timestamp,)):
                d[k] = str(v)
        report_json.append(d)
    with open(report_json_path, "w") as f:
        json.dump(report_json, f, indent=2)

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    fail_count = len(results) - ok_count

    print("\n" + "=" * 100)
    print(f"RESEARCH RETRAIN RESULTS — {ts}")
    print(f"Models saved to: {RESEARCH_MODEL_DIR}")
    print("=" * 100)
    print(f"  Total: {len(results)}  OK: {ok_count}  Failed: {fail_count}")
    print()
    if ok_count:
        print(f"{'Asset':<8} {'tp_mult':>8} {'sl_mult':>8} {'et':>5} {'depth':>6} "
              f"{'n_feat':>7} {'n_regime':>9} {'regime?':>8} {'ensemble?':>10} {'time':>6}")
        print("-" * 80)
        for r in results:
            if r.get("status") == "OK":
                print(f"{r['asset']:<8} {r['tp_mult']:>8.2f} {r['sl_mult']:>8.2f} "
                      f"{r['ensemble_threshold']:>5.2f} {r['max_depth']:>6d} "
                      f"{r['n_features']:>7d} {r['n_regime_features']:>9d} "
                      f"{'yes' if r.get('has_regime_model') else 'no':>8} "
                      f"{'yes' if r.get('has_ensemble') else 'no':>10} "
                      f"{r['train_time_s']:>6.1f}s")
        print()
        print(f"Models: {RESEARCH_MODEL_DIR}/")
        for r in results:
            if r.get("status") == "OK":
                print(f"  {r['model_path']}")

    if fail_count:
        print("\nFailed:")
        for r in results:
            if r.get("status") != "OK":
                print(f"  {r['asset']}: {r['status']}")

    print(f"\nReport saved: {report_path}")
    print(f"JSON report: {report_json_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()
