import logging
import os

import pandas as pd
import yfinance as yf

from features.registry import FEATURE_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backfill_to_2000")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "historical_extended")


def backfill():
    os.makedirs(OUT_DIR, exist_ok=True)

    tickers = list(FEATURE_REGISTRY.keys())
    # Add SPY for vs_spy features
    if "SPY" not in tickers:
        tickers.append("SPY")

    start_date = "2000-01-01"

    for ticker in tickers:
        logger.info("Downloading %s from %s...", ticker, start_date)
        try:
            df = yf.download(ticker, start=start_date, auto_adjust=True, progress=False)
            if df.empty:
                logger.warning("No data for %s", ticker)
                continue

            # Flatten columns if MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]

            df.columns = [c.lower() for c in df.columns]

            out_path = os.path.join(OUT_DIR, f"{ticker.replace('^', '').replace('=', '')}_2000.parquet")
            df.to_parquet(out_path)
            logger.info("Saved %d rows to %s", len(df), out_path)

        except (ValueError, OSError, TypeError) as e:
            logger.error("Failed to download %s: %s", ticker, e)


if __name__ == "__main__":
    backfill()
