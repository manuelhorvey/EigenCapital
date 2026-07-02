#!/usr/bin/env python3
"""Train regime-conditional models for all 21 portfolio assets.

Regime models are second XGBoost classifiers trained on alpha features +
regime features (hurst, kaufman_er, adx, vol_zscore, compression, ...).

The ensemble blends 60% base model P(LONG) + 40% regime model P(LONG).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/train_regime_models.py
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
logger = logging.getLogger("train_regime")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    from paper_trading.asset_engine_factory import build_asset_engine
    from paper_trading.config_manager import get_config
    from paper_trading.execution.bridge import ExecutionBridge
    from paper_trading.execution.paper_broker import PaperBroker
    from paper_trading.execution_context import ExecutionContext
    from paper_trading.portfolio_builder import build_paper_portfolio

    cfg = get_config()
    broker = PaperBroker(initial_capital=cfg.capital, execution_configs={})
    bridge = ExecutionBridge(broker, is_real_broker=False)
    ctx = ExecutionContext(state_store=None, execution_bridge=bridge, engine_config=cfg)

    from shared.registry import StrategyRegistry
    _reg = StrategyRegistry.get_instance()
    portfolio = build_paper_portfolio(cfg.halt)
    _reg.register_defaults(list(portfolio.keys()))

    assets_to_train = list(portfolio.keys())
    n_total = len(assets_to_train)

    logger.info("=== REGIME MODEL TRAINING for %d assets ===", n_total)

    results = []
    for idx, name in enumerate(assets_to_train, 1):
        spec = portfolio[name]
        ticker = spec["ticker"]

        logger.info("[%d/%d] %s (%s) — training regime model...", idx, n_total, name, ticker)

        try:
            engine = build_asset_engine(
                ticker=ticker, name=name, contract=spec["contract"],
                allocation=spec["alloc"], halt_config=spec["halt"],
                config=spec["config"], sl_mult=spec["sl_mult"],
                tp_mult=spec["tp_mult"], max_depth=spec["max_depth"],
                regime_geometry=spec.get("regime_geometry", {}),
                context=ctx,
            )
            engine._trained = True
            t0 = time.perf_counter()
            engine._training.train(force=True)
            elapsed = time.perf_counter() - t0

            regime_ok = getattr(engine, "_regime_model", None) is not None
            ensemble_ok = getattr(engine, "_ensemble", None) is not None
            n_regime_feats = len(getattr(engine, "regime_feature_names", []))

            logger.info(
                "  %s: regime=%s ensemble=%s feats=%d (%.1fs)",
                name, regime_ok, ensemble_ok, n_regime_feats, elapsed,
            )

            # Compute regime distribution from last 504 bars
            dist = ""
            if regime_ok:
                try:
                    from features.data_fetch import fetch_asset_ohlcv
                    from features.regime_features import generate_regime_features
                    ohlcv = fetch_asset_ohlcv(ticker)
                    if ohlcv is not None and len(ohlcv) > 100:
                        rf = generate_regime_features(ohlcv.iloc[-504:])
                        hurst = rf["hurst"].dropna()
                        if len(hurst) > 0:
                            trending = (hurst > 0.6).mean()
                            meanrev = (hurst < 0.4).mean()
                            neutral = ((hurst >= 0.4) & (hurst <= 0.6)).mean()
                            dist = "  H=%.2f/%.2f/%.2f" % (trending, neutral, meanrev)
                            if trending > 0.7 or meanrev > 0.7:
                                logger.warning("  %s: >70%% single regime — ensemble adds little value", name)
                except Exception:
                    pass

            results.append({
                "asset": name, "ticker": ticker,
                "regime_trained": regime_ok, "ensemble_configured": ensemble_ok,
                "n_regime_features": n_regime_feats,
                "train_time_s": round(elapsed, 1),
                "regime_dist": dist,
            })

        except Exception as e:
            logger.error("%s: ERROR — %s", name, e)
            import traceback
            traceback.print_exc()
            results.append({"asset": name, "ticker": ticker, "regime_trained": False, "error": str(e)})

    # Summary
    print("\n" + "=" * 80)
    print("REGIME MODEL TRAINING REPORT")
    print("=" * 80)
    ok = sum(1 for r in results if r.get("regime_trained"))
    print(f"  Total: {n_total}  Regime OK: {ok}  Ensemble configured: {sum(1 for r in results if r.get('ensemble_configured'))}")
    print()
    for r in results:
        status = "OK" if r.get("regime_trained") else "FAIL"
        dist = r.get("regime_dist", "")
        print(f"  {r['asset']:<12} {status:<6} feats={r.get('n_regime_features', 0):<2}  {r.get('train_time_s', 0):.1f}s{dist}")
    print("=" * 80)

    # Save report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(BASE, "data", "processed", f"regime_training_report_{ts}.csv")
    pd.DataFrame(results).to_csv(report_path, index=False)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
