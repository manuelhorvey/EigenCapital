#!/usr/bin/env python3
"""
Walk-forward backtest on candidate assets not in the live config.
Runs the same alpha feature pipeline as walk_forward_backtest.py.

Output:
  walkforward/{name}_wf_summary.csv  — per-window metrics
  walkforward/ticker_map.json        — name->ticker mapping for promotion report

Usage:
  PYTHONPATH=$PYTHONPATH:. python scripts/research_walkforward_candidates.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd

from features.registry import ASSET_LABEL_PARAMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("research_walkforward")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "walkforward")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CANDIDATES: dict[str, str] = {
    "BTC": "BTC-USD",
    "CADJPY": "CADJPY=X",
    "NZDJPY": "NZDJPY=X",
    "EURAUD": "EURAUD=X",
    "AUDJPY": "AUDJPY=X",
    "GBPJPY": "GBPJPY=X",
    "USDJPY": "USDJPY=X",
    "GBPUSD": "GBPUSD=X",
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "CHFJPY": "CHFJPY=X",
    "AUDCAD": "AUDCAD=X",
    "CL": "CL=F",
    "IWM": "IWM",
    "VIX": "^VIX",
}


def _get_pt_sl(name: str) -> tuple[float, float]:
    """Look up pt_sl from ASSET_LABEL_PARAMS, fallback to (2.0, 2.0)."""
    params = ASSET_LABEL_PARAMS.get(name)
    if params:
        return (params.get("pt", 2.0), params.get("sl", 2.0))
    return (2.0, 2.0)


def main():
    from scripts.backtest.walk_forward_backtest import run_walk_forward

    all_summaries = []
    for name, ticker in CANDIDATES.items():
        pt_sl = _get_pt_sl(name)
        logger.info("=== %s (%s) pt_sl=%s ===", name, ticker, pt_sl)
        try:
            result = run_walk_forward(
                name,
                ticker,
                window_years=3,
                step_years=1,
                ensemble_weight=0.6,
                ensemble_threshold=0.15,
                pt_sl=pt_sl,
            )
            if result is not None:
                all_summaries.append(result)
        except Exception as e:  # noqa: BLE001
            logger.error("  ✗ %s: %s", name, e)
            import traceback

            traceback.print_exc()

    # Save ticker map for promotion report
    ticker_map_path = os.path.join(OUTPUT_DIR, "ticker_map.json")
    with open(ticker_map_path, "w") as f:
        json.dump(CANDIDATES, f, indent=2)
    logger.info("ticker map -> %s", ticker_map_path)

    if all_summaries:
        combined = pd.concat(all_summaries)
        combined_path = os.path.join(OUTPUT_DIR, "all_assets_wf_summary.csv")
        combined.to_csv(combined_path, index=False)
        logger.info("combined summary -> %s", combined_path)

        print("\n=== Candidate Walk-Forward Summary ===")
        avg = combined.groupby("asset")[["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]].mean()
        print(avg.to_string(float_format="%.3f"))


if __name__ == "__main__":
    main()
