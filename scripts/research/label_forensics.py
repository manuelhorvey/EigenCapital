#!/usr/bin/env python3
"""Label Forensics CLI — audit triple-barrier label generation.

Usage::

    # Analyze all 17 active assets
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_forensics.py

    # Analyze specific assets
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_forensics.py EURCHF GBPCHF

    # Include counterfactual sweeps (expensive)
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_forensics.py --counterfactual

    # Output to custom path
    PYTHONPATH=$PYTHONPATH:. python scripts/research/label_forensics.py --output reports/label_audit.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from research.label_forensics.engine import (
    ACTIVE_ASSETS_20260723,
    LabelForensicsEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("label_forensics")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Label Generation Forensics")
    p.add_argument("assets", nargs="*", default=None,
                   help="Assets to analyze (default: all 17 active)")
    p.add_argument("--counterfactual", action="store_true",
                   help="Run counterfactual parameter sweeps (expensive)")
    p.add_argument("-o", "--output", default=None,
                   help="Output path for JSON report (default: data/processed/label_forensics.json)")
    p.add_argument("--per-asset", default=None,
                   help="Directory for per-asset JSON reports (default: not saved individually)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    assets = args.assets if args.assets else None
    output = args.output or "data/processed/label_forensics.json"
    per_asset_dir = args.per_asset

    logger.info("Label Forensics Engine — starting")
    logger.info("Assets: %s", assets if assets else "all 17 active")
    logger.info("Counterfactual: %s", args.counterfactual)

    engine = LabelForensicsEngine()
    result = engine.analyze_all(assets=assets, run_counterfactual=args.counterfactual)

    # Write aggregate report
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Aggregate report written to %s", out_path.resolve())

    # Optionally write per-asset reports
    if per_asset_dir:
        pad = Path(per_asset_dir)
        pad.mkdir(parents=True, exist_ok=True)
        for asset_key, report in result.get("per_asset", {}).items():
            asset_path = pad / f"{asset_key}_forensics.json"
            with open(asset_path, "w") as f:
                json.dump(report, f, indent=2, default=str)
        logger.info("Per-asset reports written to %s", pad.resolve())

    # Print portfolio summary
    pf = result.get("portfolio", {})
    dist = pf.get("portfolio_label_distribution", {})
    bias = pf.get("sell_bias_summary", {})
    cons = pf.get("conclusions", [])
    assets_by_bias = pf.get("assets_by_bias", [])

    print()
    print("=" * 60)
    print("PORTFOLIO LABEL FORENSICS SUMMARY")
    print("=" * 60)
    print(f"  Assets analyzed:    {pf.get('n_assets_analyzed', 0)}")
    if pf.get("n_assets_errored", 0):
        print(f"  Errored:            {pf.get('n_assets_errored')}")
    print()
    print("  Portfolio Label Distribution:")
    print(f"    BUY:    {dist.get('buy', 0):>8d} ({dist.get('buy_pct', 0):>5.1f}%)")
    print(f"    SELL:   {dist.get('sell', 0):>8d} ({dist.get('sell_pct', 0):>5.1f}%)")
    print(f"    TIMEOUT:{dist.get('timeout', 0):>8d} ({dist.get('timeout_pct', 0):>5.1f}%)")
    print(f"    Total:  {dist.get('total_labels', 0):>8d}")
    print()
    print("  Sell Bias Summary:")
    print(f"    Mean sell%:         {bias.get('mean_sell_pct', 0):.1f}%")
    print(f"    Assets sell > 55%:  {bias.get('n_assets_with_sell_pct_gt_55', 0)}")
    print(f"    Assets buy > 55%:   {bias.get('n_assets_with_buy_pct_gt_55', 0)}")
    print(f"    Mean asymmetry:     {bias.get('mean_asymmetry_ratio', 0):.2f}x (upper/lower)")
    print()
    print("  Assets by Sell Bias (descending):")
    print(f"    {'Asset':<10} {'Sell%':>7} {'Buy%':>7} {'Ratio':>7}")
    print(f"    {'-'*10} {'-'*7} {'-'*7} {'-'*7}")
    for entry in assets_by_bias[:15]:
        print(f"    {entry['asset']:<10} {entry['sell_pct']:>6.1f}% {entry['buy_pct']:>6.1f}% {entry.get('asymmetry_ratio', 0):>6.2f}x")
    print()
    if cons:
        print("  Conclusions:")
        for c in cons:
            print(f"    [{c['verdict']}] {c['asset']} ({c['sell_pct']:.1f}%)")
            print(f"      {c['suggestion']}")


if __name__ == "__main__":
    main()
