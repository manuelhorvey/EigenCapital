"""Instrument Catalogue — canonical instrument registry.

The catalogue is the single source of truth for instrument metadata.
All data pipelines look up metadata by instrument_id.

Usage:
    catalogue = InstrumentCatalogue()
    catalogue.register(ES_INSTRUMENT)
    es = catalogue.get("ES")
    assert es.tick_size == 0.25
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Iterator

from eigencapital.core.models.instrument import Instrument


class InstrumentNotFoundError(KeyError):
    """Raised when instrument_id is not in the catalogue."""

    def __init__(self, instrument_id: str) -> None:
        super().__init__(f"Instrument '{instrument_id}' not found in catalogue")
        self.instrument_id = instrument_id


class DuplicateInstrumentError(ValueError):
    """Raised when attempting to register an instrument that already exists."""

    def __init__(self, instrument_id: str) -> None:
        super().__init__(f"Instrument '{instrument_id}' already registered in catalogue")
        self.instrument_id = instrument_id


@dataclass
class InstrumentCatalogue:
    """Canonical instrument registry.

    Thread-safety note: This is NOT thread-safe. Use external locking
    if accessed from multiple threads.

    Attributes:
        _instruments: instrument_id → Instrument mapping
    """

    _instruments: Dict[str, Instrument] = field(default_factory=dict)

    def register(self, instrument: Instrument) -> None:
        """Register an instrument in the catalogue.

        Args:
            instrument: Validated Instrument instance

        Raises:
            DuplicateInstrumentError: if instrument_id already registered
        """
        if instrument.instrument_id in self._instruments:
            raise DuplicateInstrumentError(instrument.instrument_id)
        self._instruments[instrument.instrument_id] = instrument

    def get(self, instrument_id: str) -> Instrument:
        """Look up an instrument by ID.

        Args:
            instrument_id: Primary key

        Returns:
            Instrument metadata

        Raises:
            InstrumentNotFoundError: if not found
        """
        if instrument_id not in self._instruments:
            raise InstrumentNotFoundError(instrument_id)
        return self._instruments[instrument_id]

    def contains(self, instrument_id: str) -> bool:
        """Check if instrument is in the catalogue."""
        return instrument_id in self._instruments

    def list_ids(self) -> List[str]:
        """Return sorted list of all registered instrument IDs."""
        return sorted(self._instruments.keys())

    def list_instruments(self) -> List[Instrument]:
        """Return all registered instruments (sorted by instrument_id)."""
        return [self._instruments[iid] for iid in sorted(self._instruments.keys())]

    def __len__(self) -> int:
        return len(self._instruments)

    def __iter__(self) -> Iterator[Instrument]:
        """Iterate over instruments in sorted order."""
        for iid in sorted(self._instruments.keys()):
            yield self._instruments[iid]

    def __contains__(self, instrument_id: str) -> bool:
        return instrument_id in self._instruments
