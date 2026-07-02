#!/usr/bin/env python3
"""Standalone hot-path microbenchmark for EigenCapital.

Mocks at the network boundary (data_fetch.fetch_live / features.data_fetch.*)
so the full feature build, inference, and state-write path runs without
network I/O.

Usage::

    # Quick smoke test (1 asset, 1 worker, skip model training)
    python benchmarks/microbenchmark.py --quick

    # Full portfolio cold + warm cycles
    python benchmarks/microbenchmark.py --assets 15 --workers 8 --cycles 10

    # Sweep assets vs workers (run sequentially, output as JSONL)
    python benchmarks/microbenchmark.py --sweep

Output is JSONL to stdout; pass ``--output <file>`` to also write to file.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time

import numpy as np

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
# Suppress noisy loggers during benchmark
for name in ["eigencapital", "yfinance", "matplotlib", "urllib3"]:
    logging.getLogger(name).setLevel(logging.ERROR)

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DEFAULT_TICKERS = [
    "BTC-USD",
    "EURGBP=X",
    "GC=F",
    "NZDCHF=X",
    "CHFJPY=X",
    "CADJPY=X",
    "USDCHF=X",
    "EURJPY=X",
    "EURCAD=X",
    "AUDCHF=X",
    "USDJPY=X",
    "USDCAD=X",
    "GBPCHF=X",
    "ES=F",
    "NQ=F",
]


def _make_dummy_model(asset) -> None:
    """Train a minimal XGBoost on synthetic features so the pipeline
    has a real callable ``asset.model`` with ``predict_proba``.

    Runs inside the mock fixture so data_fetch returns synthetic data.
    Uses tiny hyperparams (10 trees, depth 2) to keep setup fast.
    """
    import xgboost as xgb

    from features.alpha_features import build_alpha_features
    from features.data_fetch import fetch_asset_data

    if getattr(asset, "_trained", False):
        return

    try:
        prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset.name, asset.ticker)
        features = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities)
        if features.empty:
            raise ValueError("empty features")
        asset._alpha_feature_cols = list(features.columns)

        rng = np.random.RandomState(42)
        n = len(features)
        y = rng.randint(0, 2, size=n)
        x_data = features.values
        model = xgb.XGBClassifier(n_estimators=10, max_depth=2, verbosity=0, tree_method="hist")
        model.fit(x_data, y)
        asset.model = model
        asset._trained = True
        asset._truncate_inference = True
        logger = logging.getLogger("benchmark")
        logger.info("%s: dummy model trained on %d rows x %d cols", asset.name, n, len(features.columns))
    except (ValueError, TypeError, RuntimeError) as e:
        raise RuntimeError(f"Failed to create dummy model for {asset.name}: {e}")


def build_engine(n_assets: int, n_workers: int, skip_validation: bool, quick: bool, state_dir: str | None = None):
    """Build a PaperTradingEngine with a subset of assets and config tweaks.

    If *state_dir* is ``None`` a temporary directory is created so the
    benchmark never touches the production ``data/live/`` state store.
    """
    from paper_trading.config_manager import get_config, reset_config
    from paper_trading.state_store import StateStore

    reset_config()
    cfg = get_config()

    # Isolated state store — never write to production data/live/
    if not state_dir:
        state_dir = tempfile.mkdtemp(prefix="qf_bench_")
    store = StateStore(state_dir)
    logger = logging.getLogger("benchmark")
    logger.info("state store: %s", store._db_path)

    # Trim to requested asset count
    asset_items = sorted(cfg.assets.items())[:n_assets]
    cfg.assets = dict(asset_items)

    # Force optimisations on
    cfg.optimizations["async_diagnostics"] = True
    cfg.optimizations["truncate_inference"] = "auto"
    # Disable circuit breaker — synthetic data can trip drawdown limits
    cfg.portfolio_drawdown_limit = None

    from paper_trading.engine import PaperTradingEngine

    engine = PaperTradingEngine(state_store=store)
    engine._orchestrator._max_workers = n_workers

    if skip_validation:
        for a in engine.assets.values():
            a._truncate_inference = True

    if quick:
        for a in engine.assets.values():
            _make_dummy_model(a)

    return engine


def run_benchmark(args) -> list[dict]:
    """Run cold + warm cycles and return JSONL-serialisable results."""
    tickers = DEFAULT_TICKERS[: args.assets]
    from benchmarks.mock_data import MockDataFixture

    mock = MockDataFixture(tickers, n_bars=args.bars)
    mock.install()

    results: list[dict] = []
    try:
        engine = build_engine(args.assets, args.workers, args.skip_validation, args.quick, args.state_dir)

        # Initialise (train models on synthetic data) unless quick
        if not args.quick:
            t0 = time.monotonic()
            engine.initialize()
            init_s = time.monotonic() - t0
            results.append({"event": "init", "init_s": round(init_s, 3), "n_assets": args.assets})

        # Cold cycle (first run — TTLCache empty, PSI baseline set)
        t0 = time.monotonic()
        engine.run_once()
        cold_s = time.monotonic() - t0
        cold = {
            "event": "cycle",
            "cold": True,
            "wall_s": round(cold_s, 4),
            "n_assets": args.assets,
            "n_workers": args.workers,
            "n_bars": args.bars,
            "skip_validation": args.skip_validation,
            "quick": args.quick,
        }
        results.append(cold)
        print(json.dumps(cold), flush=True)

        # Warm cycles
        for i in range(args.cycles):
            t0 = time.monotonic()
            engine.run_once()
            wall_s = time.monotonic() - t0
            warm = {
                "event": "cycle",
                "cold": False,
                "cycle": i + 1,
                "wall_s": round(wall_s, 4),
                "n_assets": args.assets,
                "n_workers": args.workers,
                "n_bars": args.bars,
            }
            results.append(warm)
            print(json.dumps(warm), flush=True)

        # Summary
        warm_times = [r["wall_s"] for r in results if not r.get("cold") and r["event"] == "cycle"]
        if warm_times:
            p50 = float(np.median(warm_times))
            p95 = float(np.percentile(warm_times, 95))
            mean = float(np.mean(warm_times))
        else:
            p50 = p95 = mean = 0.0
        summary = {
            "event": "summary",
            "n_assets": args.assets,
            "n_workers": args.workers,
            "n_bars": args.bars,
            "cold_s": cold_s,
            "warm_p50_s": round(p50, 4),
            "warm_p95_s": round(p95, 4),
            "warm_mean_s": round(mean, 4),
            "warm_n": len(warm_times),
        }
        results.append(summary)
        print(json.dumps(summary), flush=True)

    finally:
        mock.uninstall()

    return results


def run_sweep(args) -> None:
    """Run a grid of (n_assets, n_workers) combinations."""
    asset_counts = [1, 5, 10, 15]
    worker_counts = [1, 4, 8]
    all_results = []

    for n_assets in asset_counts:
        for n_workers in worker_counts:
            if n_workers > n_assets:
                continue
            print(
                json.dumps({"event": "sweep_start", "n_assets": n_assets, "n_workers": n_workers}),
                flush=True,
            )
            args.assets = n_assets
            args.workers = n_workers
            all_results.extend(run_benchmark(args))

    # Overall summary
    print(json.dumps({"event": "sweep_done", "total_runs": len(all_results)}), flush=True)

    if args.output:
        with open(args.output, "w") as f:
            for r in all_results:
                f.write(json.dumps(r) + "\n")


def run_profiled(args) -> None:
    """Run one full cycle under cProfile and dump results."""
    import cProfile
    import pstats

    tickers = DEFAULT_TICKERS[: args.assets]
    from benchmarks.mock_data import MockDataFixture

    mock = MockDataFixture(tickers, n_bars=args.bars)
    mock.install()

    try:
        engine = build_engine(args.assets, args.workers, args.skip_validation, args.quick, args.state_dir)

        if not args.quick:
            engine.initialize()

        # One warm-up cycle (populates caches)
        engine.run_once()

        prof_path = args.profile
        prof = cProfile.Profile()
        prof.enable()
        engine.run_once()
        prof.disable()

        prof.dump_stats(prof_path)
        print(json.dumps({"event": "profile_saved", "path": prof_path}), flush=True)

        # Print top callers by cumulative time
        stats = pstats.Stats(prof).sort_stats("cumtime")
        stats.print_stats(30)

        # Print top by total time (self-time, excludes children)
        print("\n=== By total time (self) ===")
        stats.sort_stats("time").print_stats(20)

    finally:
        mock.uninstall()


def main():
    parser = argparse.ArgumentParser(description="EigenCapital hot-path microbenchmark")
    parser.add_argument("--assets", type=int, default=15, help="number of assets (default: 15)")
    parser.add_argument("--workers", type=int, default=8, help="ThreadPoolExecutor workers (default: 8)")
    parser.add_argument("--cycles", type=int, default=5, help="warm cycles after cold run (default: 5)")
    parser.add_argument("--bars", type=int, default=500, help="synthetic OHLCV bars per asset (default: 500)")
    parser.add_argument("--output", type=str, default="", help="path to write JSONL results")
    parser.add_argument("--profile", type=str, default="", help="path to write cProfile .prof file")
    parser.add_argument("--skip-validation", action="store_true", help="force truncation on")
    parser.add_argument("--state-dir", type=str, default="", help="state store directory (default: temp dir)")
    parser.add_argument("--quick", action="store_true", help="skip full model training, use dummy models")
    parser.add_argument("--sweep", action="store_true", help="sweep asset x worker grid")

    args = parser.parse_args()

    if args.profile:
        run_profiled(args)
    elif args.sweep:
        run_sweep(args)
    else:
        run_benchmark(args)


if __name__ == "__main__":
    main()
