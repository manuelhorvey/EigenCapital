#!/usr/bin/env python3
"""Download extended OHLCV and emit neutral extended_predictions for survival_sim."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, PROJECT_ROOT)

from data.loaders.backfill_to_2000 import backfill  # noqa: E402
from paper_trading.config_manager import get_config  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("extended_history_pipeline")

SANDBOX_BASE = str(Path(PROJECT_ROOT) / "data" / "sandbox")
EXT_RAW = str(Path(PROJECT_ROOT) / "data" / "raw" / "historical_extended")


def _clean_ticker(ticker: str) -> str:
    return ticker.replace("^", "").replace("=", "")


def build_neutral_predictions(name: str, ticker: str) -> pd.DataFrame | None:
    path = str(Path(EXT_RAW) / "{_clean_ticker(ticker)}_2000.parquet")
    if not Path(path).exists():
        logger.warning("%s: missing %s", name, path)
        return None
    df = pd.read_parquet(path)
    if "close" not in df.columns:
        return None
    out = df[["close"]].copy()
    out["signal"] = 1
    out["confidence"] = 100.0
    out["prob_long"] = 0.33
    out["prob_short"] = 0.33
    out["prob_neutral"] = 0.34
    return out


def write_extended_predictions(skip_download: bool = False) -> int:
    if not skip_download:
        backfill()

    cfg = get_config()
    written = 0
    for name, spec in cfg.assets.items():
        ticker = spec.get("ticker", name)
        pred = build_neutral_predictions(name, ticker)
        if pred is None:
            continue
        out_dir = os.path.join(SANDBOX_BASE, name)
        os.makedirs(out_dir, exist_ok=True)
        out_path = str(Path(out_dir) / "extended_predictions.parquet")
        pred.to_parquet(out_path)
        logger.info("%s: wrote %d rows to %s", name, len(pred), out_path)
        written += 1
    return written


def main():
    parser = argparse.ArgumentParser(description="Extended history data pipeline")
    parser.add_argument("--skip-download", action="store_true", help="Only build prediction stubs")
    args = parser.parse_args()
    n = write_extended_predictions(skip_download=args.skip_download)
    logger.info("Wrote extended_predictions for %d assets", n)
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
