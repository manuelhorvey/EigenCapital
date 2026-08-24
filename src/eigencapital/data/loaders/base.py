"""Base data loader interface.

All loaders produce RawRecord dicts that are later normalized into Bars.
The loader is responsible for reading the raw source; the normalizer
handles column mapping, type conversion, and validation.

Usage:
    loader = CSVLoader(path="data/raw/es_daily.csv")
    records = loader.load()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RawRecord:
    """A single raw data record from a source file.

    This is an unvalidated, un-normalized row. Field names and types
    depend on the source provider.

    Attributes:
        source: Provider or file identifier
        instrument_id: Provider-specific symbol (not yet canonical)
        timestamp: Raw timestamp (may not be UTC)
        data: Provider-specific field dict
    """

    source: str
    instrument_id: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)


class BaseLoader(ABC):
    """Abstract base class for data loaders.

    Subclasses implement load() to produce a list of RawRecord dicts.
    """

    @abstractmethod
    def load(self) -> List[RawRecord]:
        """Load raw records from the source.

        Returns:
            List of RawRecord instances
        """
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier (e.g., file path, provider name)."""
        ...
