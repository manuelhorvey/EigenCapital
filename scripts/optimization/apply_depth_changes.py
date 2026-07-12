#!/usr/bin/env python3
"""
Apply per-asset max_depth changes from the depth optimization sweep.

Reads asset YAML configs from configs/domains/assets/, updates max_depth
for assets listed in ASSET_CHANGES, and writes back. Supports --dry-run.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/optimization/apply_depth_changes.py
    PYTHONPATH=$PYTHONPATH:. python scripts/optimization/apply_depth_changes.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apply_depth_changes")

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "domains" / "assets"

ASSET_CHANGES: dict[str, dict] = {
    "GC": {"max_depth": 4},         # R +150.5 (+145%), IC 0.016->0.063
    "GBPUSD": {"max_depth": 4},     # R +12.9 (+5.7%), IC -0.122->-0.003
    "AUDUSD": {"max_depth": 5},     # R +22.7 (+5.2%), IC 0.040->0.104
    "EURNZD": {"max_depth": 5},     # R +13.4 (+5.1%), IC 0.247->0.293
    "USDCAD": {"max_depth": 3},     # R +54.6 (+14.9%), IC 0.015->0.040 (was overfit at 5)
    "CADCHF": {"max_depth": 3},     # R +116.0 (+42.8%), IC -0.180->-0.131
    "^DJI": {"max_depth": 4},       # IC turns positive: -0.027->+0.086
    "EURAUD": {"max_depth": 5},     # R +3.5 (+1.8%), IC 0.071->0.126
    "NZDUSD": {"max_depth": 2},     # R +113.5 (+41%), IC 0.095->0.123 (was overfit at 5)
}


def _insert_max_depth(data: dict, value: int) -> dict:
    """Insert max_depth into dict at a natural position (after tp_mult or after
    ticker+allocation+sl_tp block, maintaining YAML readability)."""
    if "max_depth" in data:
        data["max_depth"] = value
        return data

    preferred_after = {"tp_mult", "allocation", "spread_tier", "ticker"}
    insert_idx = len(data)
    for i, key in enumerate(data):
        if key in preferred_after:
            insert_idx = i + 1

    items = list(data.items())
    items.insert(insert_idx, ("max_depth", value))
    return dict(items)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply per-asset max_depth changes from depth optimization sweep"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without modifying files")
    args = parser.parse_args()

    if not ASSETS_DIR.exists():
        logger.error("Assets directory not found: %s", ASSETS_DIR)
        sys.exit(1)

    changed_count = 0
    error_count = 0

    for asset_name, changes in sorted(ASSET_CHANGES.items()):
        asset_file = ASSETS_DIR / f"{asset_name}.yaml"
        if not asset_file.exists():
            logger.warning("SKIP: %s — no config file at %s", asset_name, asset_file)
            error_count += 1
            continue

        with open(asset_file, "r") as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning("SKIP: %s — empty config file", asset_name)
            error_count += 1
            continue

        new_max_depth = changes["max_depth"]
        old_max_depth = data.get("max_depth", None)

        if old_max_depth == new_max_depth:
            logger.info("UNCHANGED: %s max_depth already %s", asset_name, new_max_depth)
            continue

        if old_max_depth is None:
            logger.info(
                "%s: %s max_depth=%s (was implicit default depth 2)",
                "WOULD ADD" if args.dry_run else "ADD",
                asset_name, new_max_depth,
            )
        else:
            logger.info(
                "%s: %s max_depth=%s (was %s)",
                "WOULD CHANGE" if args.dry_run else "CHANGE",
                asset_name, new_max_depth, old_max_depth,
            )

        if not args.dry_run:
            updated = _insert_max_depth(data, new_max_depth)
            with open(asset_file, "w") as f:
                yaml.dump(updated, f, default_flow_style=False, sort_keys=False)
            changed_count += 1

    if args.dry_run:
        logger.info("Dry-run complete. No files modified.")
    else:
        logger.info("Applied %d changes (%d errors).", changed_count, error_count)


if __name__ == "__main__":
    main()
