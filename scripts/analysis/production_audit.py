#!/usr/bin/env python3
"""
Production Trade Lifecycle, Timing & Edge Optimization Audit.

Comprehensive 18-phase forensic analysis of the entire trading lifecycle.
Runs all phases sequentially, produces structured JSON output and formatted
terminal report.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py --phases 4,5,7
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py --output audit_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime).is_absolute()s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.audit")

# Add project root
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.analysis.audit_phases import (
    phase1_lifecycle,
    phase2_path_dependency,
    phase4_time_profitability,
    phase6_holding_period,
    phase7_exit_strategies,
    phase8_entry_quality,
    phase9_opportunity_cost,
    phase11_overlap,
    phase12_risk_of_ruin,
    phase13_sensitivity,
    phase14_regime_transition,
    phase15_edge_decay,
    phase16_clustering,
    phase17_portfolio_timing,
    phase18_recommendations,
    phase_data,
)

TRADE_DATA_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"

PHASE_REGISTRY = {
    "1": ("Phase 1 — Enhanced Lifecycle", phase1_lifecycle.run),
    "2": ("Phase 2 — Path Dependency", phase2_path_dependency.run),
    "4": ("Phase 4–5 — Time + Concentration", phase4_time_profitability.run),
    "6": ("Phase 6 — Holding Period", phase6_holding_period.run),
    "7": ("Phase 7 — Exit Strategies", phase7_exit_strategies.run),
    "8": ("Phase 8 — Entry Quality", phase8_entry_quality.run),
    "9": ("Phase 9 — Opportunity Cost", phase9_opportunity_cost.run),
    "11": ("Phase 11 — Overlap & Correlation", phase11_overlap.run),
    "12": ("Phase 12 — Risk of Ruin", phase12_risk_of_ruin.run),
    "13": ("Phase 13 — Sensitivity", phase13_sensitivity.run),
    "14": ("Phase 14 — Regime Transition", phase14_regime_transition.run),
    "15": ("Phase 15 — Edge Decay", phase15_edge_decay.run),
    "16": ("Phase 16 — Clustering", phase16_clustering.run),
    "17": ("Phase 17 — Portfolio Timing", phase17_portfolio_timing.run),
    "18": ("Phase 18 — Recommendations", phase18_recommendations.run),
}

ALL_PHASES = sorted(PHASE_REGISTRY.keys(), key=int)


def load_ohlcv_map() -> dict:
    """Load OHLCV data for all portfolio assets."""
    from features.data_fetch import fetch_asset_ohlcv
    from scripts.analysis.audit_phases.phase_data import PORTFOLIO_ASSETS

    ohlcv_map = {}
    for asset, ticker in PORTFOLIO_ASSETS.items():
        try:
            ohlcv = fetch_asset_ohlcv(ticker)
            if not ohlcv.empty:
                ohlcv_map[asset] = ohlcv
                logger.info("  Loaded OHLCV for %s (%s)", asset, ticker)
        except Exception:
            logger.warning("  Failed to load OHLCV for %s", asset)
    return ohlcv_map


def print_verdict(recs_result: dict):
    """Print a concise terminal verdict."""
    recs = recs_result.get("recommendations", [])[:10]
    print("\n" + "=" * 72)
    print("  TOP RECOMMENDATIONS")
    print("=" * 72)
    for r in recs:
        pct = r.get("priority_score", 0)
        rtype = r.get("type", "INFO")
        title = r.get("title", "?")
        print(f"  [{rtype:5s}] (score={pct:.3f}) {title}")
        print(f"         {r.get('description', '')[:100]}")
    print("\n" + "=" * 72)
    print(
        f"  Total: {recs_result.get('n_recommendations', 0)} | "
        f"{recs_result.get('n_alpha', 0)} Alpha | "
        f"{recs_result.get('n_sigma', 0)} Sigma | "
        f"{recs_result.get('n_info', 0)} Info"
    )
    print("=" * 72)


def print_runtime(phase_times: dict[str, float]):
    print(f"\n{'─' * 50}")
    print("  RUNTIME")
    print(f"{'─' * 50}")
    for phase_id, elapsed in sorted(phase_times.items(), key=lambda x: x[1], reverse=True):
        name = PHASE_REGISTRY.get(phase_id, [phase_id])[0]
        print(f"  {name:<40s} {elapsed:>6.1f}s")
    print(f"{'─' * 50}")


def main():
    parser = argparse.ArgumentParser(description="Production Trade Lifecycle Audit")
    parser.add_argument("--phases", default=None, help="Comma-separated phase numbers (e.g. '4,5,7')")
    parser.add_argument("--output", default=None, help="JSON output path")
    parser.add_argument("--skip-data-load", action="store_true", help="Skip loading trade data (use cached)")
    args = parser.parse_args()

    if args.phases:
        phase_ids = [p.strip() for p in args.phases.split(",") if p.strip() in PHASE_REGISTRY]
    else:
        phase_ids = list(ALL_PHASES)

    logger.info("Production Audit — %d phases selected: %s", len(phase_ids), ", ".join(phase_ids))

    # ── Phase 0: Data loading + augmentation ──
    if not args.skip_data_load:
        logger.info("Loading trade data from %s", TRADE_DATA_PATH)
        trades_map, phases = phase_data.load_and_augment(str(TRADE_DATA_PATH))
        logger.info("Loaded %d assets, %d trades", len(trades_map), sum(len(ts) for ts in trades_map.values()))
    else:
        trades_map, phases = {}, {}
        logger.warning("Data load skipped — trades_map will be empty")

    if not trades_map:
        logger.error("No trade data loaded — aborting")
        sys.exit(1)

    # Load OHLCV for phases that need it
    needs_ohlcv = {"8", "14"}
    ohlcv_map = {}
    if needs_ohlcv & set(phase_ids):
        logger.info("Loading OHLCV data...")
        ohlcv_map = load_ohlcv_map()

    # ── Run phases ──
    phase_times: dict[str, float] = {}
    all_results: dict[str, object] = {
        "metadata": {
            "n_assets": len(trades_map),
            "n_trades": sum(len(ts) for ts in trades_map.values()),
            "data_source": str(TRADE_DATA_PATH),
            "phases_run": phase_ids,
        }
    }

    for phase_id in phase_ids:
        name, fn = PHASE_REGISTRY[phase_id]
        logger.info("─" * 50)
        logger.info("Running %s", name)

        t0 = time.time()
        try:
            if phase_id == "8":
                result = fn(trades_map, ohlcv_map)
            elif phase_id == "14":
                result = fn(trades_map, ohlcv_map)
            elif phase_id == "6":
                result = fn(trades_map, ohlcv_map)
            elif phase_id == "18":
                result = fn(all_results)
            else:
                result = fn(trades_map)

            elapsed = time.time() - t0
            phase_times[phase_id] = elapsed
            all_results[f"phase{phase_id.replace('-', '_')}"] = result
            logger.info("  → Completed in %.1fs", elapsed)

            # Sanity check
            if isinstance(result, dict) and "error" in result:
                logger.warning("  ⚠ Phase returned error: %s", result["error"])

        except Exception as e:
            elapsed = time.time() - t0
            phase_times[phase_id] = elapsed
            all_results[f"phase{phase_id}"] = {"error": str(e)}
            logger.exception("  ✗ Phase failed after %.1fs: %s", elapsed, e)

    # ── Output ──
    print_runtime(phase_times)

    verdict = all_results.get("phase18", {})
    if verdict and "error" not in verdict:
        print_verdict(verdict)

    if args.output:
        output_path = args.output if Path(args.output) else str(ROOT / args.output)
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2, cls=EigenCapitalJSONEncoder)
        logger.info("Results saved to %s", output_path)

    logger.info("Audit complete — %d phases, %d recommendations", len(phase_ids), verdict.get("n_recommendations", 0))


if __name__ == "__main__":
    main()
