"""Data — raw data ingestion, normalization, validation, and catalogue.

Canonical entry points:
- MT5DataProvider: pull real historical data from MT5 or yfinance
- DataManifest: data snapshot identity for reproducibility
"""

from eigencapital.data.mt5_provider import DataManifest, MT5DataProvider

__all__ = [
    "DataManifest",
    "MT5DataProvider",
]
