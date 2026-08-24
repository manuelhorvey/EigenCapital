#!/usr/bin/env python3
"""Run the full Intraday Research Campaign.

Phase I-A through I-L:
1. Pull M5 data from MT5
2. Run integrity checks
3. Add features
4. Evaluate all hypotheses
5. Produce Intraday Alpha Research Map
"""

import sys
import os
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from eigencapital.research.intraday.data_puller import IntradayDataPuller
from eigencapital.research.intraday.campaign import IntradayCampaignExecutor

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Phase I-A: Pull data from MT5
    logger.info("=" * 60)
    logger.info("PHASE I-A: Data Acquisition")
    logger.info("=" * 60)

    puller = IntradayDataPuller(max_bars=50000)
    data, manifest = puller.pull_data(data_dir="data/intraday")

    logger.info(f"Broker: {manifest.broker}")
    logger.info(f"Terminal: {manifest.terminal_id}")
    logger.info(f"Symbols: {len(manifest.symbols)}")
    logger.info(f"Total bars: {manifest.total_bars}")
    logger.info(f"Date range: {manifest.first_timestamp} to {manifest.last_timestamp}")
    logger.info(f"Missing bars: {manifest.missing_bars}")
    logger.info(f"Duplicate bars: {manifest.duplicate_bars}")
    logger.info(f"OHLC violations: {manifest.ohlc_violations}")
    logger.info(f"Snapshot hash: {manifest.snapshot_hash}")

    for sym in manifest.symbols:
        bars = manifest.bars_per_symbol.get(sym, 0)
        logger.info(f"  {sym}: {bars} bars")

    # Phase I-B through I-K: Run campaign
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE I-B through I-K: Running Campaign")
    logger.info("=" * 60)

    executor = IntradayCampaignExecutor(data, manifest)
    results = executor.run_full_campaign()

    # Phase I-L: Produce Research Map
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE I-L: Intraday Alpha Research Map")
    logger.info("=" * 60)

    research_map = executor.produce_research_map(results)

    # Save to docs
    output_dir = "docs/research"
    os.makedirs(output_dir, exist_ok=True)
    output_path = f"{output_dir}/INTRADAY_ALPHA_RESEARCH_MAP.md"
    with open(output_path, "w") as f:
        f.write(research_map)

    logger.info(f"Research map saved to {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("INTRADAY ALPHA RESEARCH MAP — SUMMARY")
    print("=" * 60)

    from eigencapital.research.intraday.hypotheses import Verdict

    verdict_counts = {}
    for r in results:
        v = r.verdict.value
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    for verdict in ["supported", "incremental", "fragile", "regime_dependent",
                     "cost_sensitive", "inconclusive", "rejected"]:
        count = verdict_counts.get(verdict, 0)
        if count > 0:
            bar = "█" * count * 3
            print(f"  {verdict.upper():30s} {count:3d}  {bar}")

    total = len(results)
    survivors = verdict_counts.get("supported", 0) + verdict_counts.get("incremental", 0)
    print(f"\n  Total hypotheses: {total}")
    print(f"  Survivors: {survivors} ({survivors/total*100:.1f}%)" if total > 0 else "  No results")

    # Failure mode summary
    mode_counts = {}
    for r in results:
        for fm in r.failure_modes:
            mode_counts[fm] = mode_counts.get(fm, 0) + 1

    if mode_counts:
        print("\n  Failure Modes:")
        for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
            print(f"    {mode:30s} {count:3d}")

    # Top results
    print("\n  Top Results by Net Sharpe:")
    for r in sorted(results, key=lambda x: -x.net_sharpe)[:5]:
        print(f"    {r.hypothesis_id:15s} {r.verdict.value:20s} Sharpe={r.net_sharpe:.3f}  DD={r.max_dd_pct:.1f}%")

    print(f"\n  Campaign: {executor.freeze.campaign_id}")
    print(f"  Data: {manifest.total_bars} bars across {len(manifest.symbols)} symbols")
    print(f"  Snapshot: {manifest.snapshot_hash}")


if __name__ == "__main__":
    main()
