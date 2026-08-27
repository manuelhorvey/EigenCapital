#!/usr/bin/env python3
"""Run Campaign 2 — Microstructure / Volume-Based Intraday Research.

Uses the same M5 data from Campaign 1 but tests fundamentally different
information sources: volume, spread, range patterns, and session mechanics.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from eigencapital.research.intraday.campaign2 import MicroCampaignExecutor
from eigencapital.research.intraday.data_puller import IntradayDataPuller

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("CAMPAIGN 2: Microstructure / Volume-Based Research")
    logger.info("=" * 60)

    # Load existing data (same as Campaign 1)
    puller = IntradayDataPuller(max_bars=50000)
    data, manifest = puller.pull_data(data_dir="data/intraday")

    logger.info(f"Broker: {manifest.broker}")
    logger.info(f"Symbols: {len(manifest.symbols)}")
    logger.info(f"Total bars: {manifest.total_bars}")
    logger.info(f"Snapshot: {manifest.snapshot_hash}")

    # Run Campaign 2
    logger.info("")
    logger.info("Running 20 microstructure hypotheses...")
    executor = MicroCampaignExecutor(data, manifest)
    results = executor.run()

    # Produce map
    research_map = executor.produce_map(results)

    output_dir = "docs/research"
    os.makedirs(output_dir, exist_ok=True)
    output_path = f"{output_dir}/INTRADAY_CAMPAIGN2_MICROSTRUCTURE_MAP.md"
    with open(output_path, "w") as f:
        f.write(research_map)

    logger.info(f"Research map saved to {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("CAMPAIGN 2 — MICROSTRUCTURE RESEARCH MAP — SUMMARY")
    print("=" * 60)

    verdict_counts = {}
    for r in results:
        v = r["verdict"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    for verdict in [
        "supported",
        "incremental",
        "fragile",
        "regime_dependent",
        "cost_sensitive",
        "inconclusive",
        "rejected",
    ]:
        count = verdict_counts.get(verdict, 0)
        if count > 0:
            bar = "█" * count * 3
            print(f"  {verdict.upper():30s} {count:3d}  {bar}")

    total = len(results)
    survivors = verdict_counts.get("supported", 0) + verdict_counts.get("incremental", 0)
    print(f"\n  Total hypotheses: {total}")
    print(f"  Survivors: {survivors} ({survivors / total * 100:.1f}%)" if total else "  No results")

    # By signal source
    print("\n  By Signal Source:")
    source_counts = {}
    source_survivors = {}
    for r in results:
        src = r["signal_source"]
        source_counts[src] = source_counts.get(src, 0) + 1
        if r["verdict"] in ("supported", "incremental"):
            source_survivors[src] = source_survivors.get(src, 0) + 1
    for src in sorted(source_counts.keys()):
        s = source_survivors.get(src, 0)
        t = source_counts[src]
        print(f"    {src:15s}: {s}/{t} survived")

    # Failure modes
    mode_counts = {}
    for r in results:
        for fm in r["failure_modes"]:
            mode_counts[fm] = mode_counts.get(fm, 0) + 1
    if mode_counts:
        print("\n  Failure Modes:")
        for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
            print(f"    {mode:30s} {count:3d}")

    # Top results
    print("\n  Top Results by Net Sharpe:")
    for r in sorted(results, key=lambda x: -x["net_sharpe"])[:5]:
        print(
            f"    {r['hypothesis_id']:15s} {r['verdict']:20s} Sharpe={r['net_sharpe']:.3f}  DD={r['max_dd']:.1f}%  src={r['signal_source']}"
        )


if __name__ == "__main__":
    main()
