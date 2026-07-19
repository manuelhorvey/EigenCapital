from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("eigencapital.state_store")


class _DataCache:
    """Parquet file cache for downloaded OHLCV data."""

    def __init__(self, cache_dir: str):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, ticker: str) -> Path:
        safe_name = ticker.replace("=", "_").replace("-", "_")
        return self._cache_dir / f"{safe_name}.parquet"

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        path = self.path_for(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

    def load(self, ticker: str) -> pd.DataFrame | None:
        path = self.path_for(ticker)
        if path.exists():
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except (OSError, ValueError, TypeError, KeyError) as _ce:
                logger.warning("Cache read error for %s: %s", ticker, _ce)
        return None
