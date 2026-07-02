import logging
import os

import pandas as pd

logger = logging.getLogger("eigencapital.state_store")


class _DataCache:
    """Parquet file cache for downloaded OHLCV data."""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        os.makedirs(self._cache_dir, exist_ok=True)

    def path_for(self, ticker: str) -> str:
        safe_name = ticker.replace("=", "_").replace("-", "_")
        return os.path.join(self._cache_dir, f"{safe_name}.parquet")

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        path = self.path_for(ticker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path)

    def load(self, ticker: str) -> pd.DataFrame | None:
        path = self.path_for(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning("Cache read error for %s: %s", ticker, e)
        return None
