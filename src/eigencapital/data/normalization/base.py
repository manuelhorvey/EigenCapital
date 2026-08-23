"""Base data normalizer interface.

The normalizer converts RawRecord dicts into canonical Bar models.
It handles type coercion, timezone conversion, and field mapping
but does NOT silently repair suspicious data.

Usage:
    normalizer = BarNormalizer(instrument_id="ES", bar_interval="1d")
    bars = normalizer.normalize(raw_records)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from eigencapital.data.loaders.base import RawRecord


class BaseNormalizer(ABC):
    """Abstract base class for data normalizers."""

    @abstractmethod
    def normalize(self, records: List[RawRecord]) -> list:
        """Normalize raw records into domain models.

        Args:
            records: Raw records from a loader

        Returns:
            List of normalized domain models (e.g., Bar)
        """
        ...
