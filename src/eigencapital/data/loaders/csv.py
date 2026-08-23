"""CSV data loader.

Reads CSV files with OHLCV data and produces RawRecord instances.

Expected CSV columns (flexible mapping via column_map):
    timestamp, open, high, low, close, volume

Usage:
    loader = CSVLoader(
        path="data/raw/es_daily.csv",
        instrument_id="ES",
        column_map={"date": "timestamp", "vol": "volume"},
    )
    records = loader.load()
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from eigencapital.data.loaders.base import BaseLoader, RawRecord


@dataclass
class CSVLoader(BaseLoader):
    """CSV file loader for OHLCV data.

    Attributes:
        path: Path to CSV file
        instrument_id: Canonical instrument ID for these records
        column_map: Provider-specific → canonical column name mapping
        timestamp_column: Name of the timestamp column
        source_name_: Override source name (defaults to file path)
        encoding: File encoding (default: utf-8)
    """

    path: str | Path
    instrument_id: str
    column_map: Dict[str, str] = field(default_factory=dict)
    timestamp_column: str = "timestamp"
    source_name_: str = ""
    encoding: str = "utf-8"

    def source_name(self) -> str:
        return self.source_name_ or str(self.path)

    def load(self) -> List[RawRecord]:
        """Load CSV rows as RawRecord instances.

        Column mapping is applied:
        - Columns in column_map are renamed to canonical names
        - Unmapped columns are passed through as-is

        Returns:
            List of RawRecord, one per CSV row
        """
        path = Path(self.path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        records: List[RawRecord] = []
        with open(path, "r", encoding=self.encoding) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Apply column mapping
                mapped_row: Dict[str, Any] = {}
                for key, value in row.items():
                    canonical_key = self.column_map.get(key, key)
                    mapped_row[canonical_key] = value

                # Extract timestamp
                timestamp = mapped_row.pop(self.timestamp_column, "")

                records.append(
                    RawRecord(
                        source=self.source_name(),
                        instrument_id=self.instrument_id,
                        timestamp=timestamp,
                        data=mapped_row,
                    )
                )

        return records
