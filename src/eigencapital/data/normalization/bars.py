"""Bar normalizer — raw data → canonical Bar.

Handles:
- Column mapping (open, high, low, close, volume, vwap)
- Timestamp parsing (ISO-8601 UTC)
- Numeric conversion (prices, volume)
- Bar interval assignment
- Source attribution

Does NOT:
- Repair high < low (returns NormalizationError instead)
- Impute missing prices
- Fill volume gaps

Usage:
    normalizer = BarNormalizer(
        instrument_id="ES",
        bar_interval="1d",
        source="provider_x",
    )
    bars = normalizer.normalize(raw_records)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from eigencapital.core.models.bar import Bar
from eigencapital.data.loaders.base import RawRecord
from eigencapital.data.normalization.base import BaseNormalizer


class NormalizationError(ValueError):
    """Raised when a raw record cannot be normalized into a Bar."""

    def __init__(self, message: str, record: RawRecord | None = None) -> None:
        super().__init__(message)
        self.record = record


@dataclass
class BarNormalizer(BaseNormalizer):
    """Normalizes raw OHLCV records into canonical Bar models.

    Attributes:
        instrument_id: Canonical instrument ID
        bar_interval: Bar interval (e.g., "1d", "5m")
        source: Data source identifier
        dataset_version: Dataset version for attribution
    """

    instrument_id: str
    bar_interval: str = "1d"
    source: str = ""
    dataset_version: str = "v1"

    # Default field mapping from common CSV column names
    DEFAULT_FIELD_MAP: Dict[str, str] = field(
        default_factory=lambda: {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "vwap": "vwap",
            "date": "timestamp",
            "datetime": "timestamp",
            "time": "timestamp",
            "Date": "timestamp",
            "DateTime": "timestamp",
        }
    )

    def normalize(self, records: List[RawRecord]) -> List[Bar]:
        """Normalize raw records into Bar instances.

        Args:
            records: Raw records from a loader

        Returns:
            List of Bar instances (one per valid record)

        Raises:
            NormalizationError: if a record cannot be normalized
        """
        bars: List[Bar] = []
        for record in records:
            bar = self._normalize_single(record)
            bars.append(bar)
        return bars

    def _normalize_single(self, record: RawRecord) -> Bar:
        """Normalize a single raw record into a Bar."""
        data = record.data

        # Extract and parse prices
        open_price = self._parse_float(data, "open", record)
        high_price = self._parse_float(data, "high", record)
        low_price = self._parse_float(data, "low", record)
        close_price = self._parse_float(data, "close", record)
        volume = self._parse_int(data, "volume", record, required=False) or 0

        # VWAP (optional)
        vwap_str = data.get("vwap")
        vwap = float(vwap_str) if vwap_str not in (None, "", "null") else None

        # Parse timestamp
        timestamp = self._parse_timestamp(record.timestamp, record)

        # For bar_start_utc, we approximate from bar_interval
        bar_start = self._infer_bar_start(timestamp)

        return Bar(
            instrument_id=self.instrument_id,
            timestamp_utc=timestamp,
            bar_start_utc=bar_start,
            bar_end_utc=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            vwap=vwap,
            source=record.source or self.source,
            bar_interval=self.bar_interval,
            data_version=self.dataset_version,
        )

    def _parse_float(self, data: Dict[str, Any], field_name: str, record: RawRecord) -> float:
        """Parse a float value from raw data."""
        value = data.get(field_name)
        if value is None or value == "":
            raise NormalizationError(
                f"Missing required field '{field_name}'",
                record=record,
            )
        try:
            return float(value)
        except (ValueError, TypeError) as e:
            raise NormalizationError(
                f"Cannot parse '{field_name}' as float: {value}",
                record=record,
            ) from e

    def _parse_int(
        self,
        data: Dict[str, Any],
        field_name: str,
        record: RawRecord,
        required: bool = True,
    ) -> int | None:
        """Parse an int value from raw data."""
        value = data.get(field_name)
        if value is None or value == "":
            if required:
                raise NormalizationError(
                    f"Missing required field '{field_name}'",
                    record=record,
                )
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError) as e:
            raise NormalizationError(
                f"Cannot parse '{field_name}' as int: {value}",
                record=record,
            ) from e

    def _parse_timestamp(self, raw_ts: str, record: RawRecord) -> str:
        """Parse and validate a timestamp string.

        Currently accepts ISO-8601 format.
        Full timezone normalization is handled by the validator.
        """
        if not raw_ts:
            raise NormalizationError("Empty timestamp", record=record)
        if "T" not in raw_ts and " " not in raw_ts:
            raise NormalizationError(
                f"Timestamp not ISO-8601: {raw_ts}",
                record=record,
            )
        # Normalize space separator to T
        normalized = raw_ts.replace(" ", "T")
        # Ensure Z suffix (assume UTC if no timezone info)
        if not normalized.endswith("Z") and "+" not in normalized and normalized.count("-") <= 2:
            normalized = normalized + "Z"
        return normalized

    def _infer_bar_start(self, bar_end_utc: str) -> str:
        """Infer bar_start_utc from bar_end_utc and bar_interval.

        Uses the bar_interval to compute the start time.
        Falls back to subtracting 1 minute if parsing fails.
        """
        from datetime import datetime, timedelta

        try:
            # Parse the end timestamp
            ts = bar_end_utc.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)

            # Map interval to timedelta
            interval_map = {
                "1m": timedelta(minutes=1),
                "5m": timedelta(minutes=5),
                "15m": timedelta(minutes=15),
                "30m": timedelta(minutes=30),
                "1h": timedelta(hours=1),
                "1d": timedelta(days=1),
                "1w": timedelta(weeks=1),
            }
            delta = interval_map.get(self.bar_interval, timedelta(minutes=1))
            start_dt = dt - delta
            return start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, KeyError):
            # Fallback: just use the end time minus 1 minute
            return bar_end_utc
