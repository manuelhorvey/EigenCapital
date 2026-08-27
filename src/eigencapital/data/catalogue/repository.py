"""Catalogue Repository — persistence layer for instrument catalogue.

Provides JSON-based storage and retrieval of instrument metadata.
Each instrument is stored as a separate file keyed by instrument_id.

Usage:
    repo = CatalogueRepository(path="data/metadata/instruments")
    repo.save(instrument)
    loaded = repo.load("ES")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from eigencapital.core.models.instrument import Instrument
from eigencapital.data.catalogue.catalogue import (
    InstrumentCatalogue,
    InstrumentNotFoundError,
)


class CatalogueRepository:
    """JSON-based instrument persistence.

    Storage layout:
        base_path/
            ES.json
            NQ.json
            EURUSD.json
            ...
    """

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _instrument_path(self, instrument_id: str) -> Path:
        return self.base_path / f"{instrument_id}.json"

    def save(self, instrument: Instrument) -> None:
        """Save instrument metadata to disk."""
        path = self._instrument_path(instrument.instrument_id)
        data = instrument.to_dict()
        # Deterministic serialization: sorted keys
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2, ensure_ascii=False)

    def load(self, instrument_id: str) -> Instrument:
        """Load instrument metadata from disk.

        Raises:
            InstrumentNotFoundError: if file does not exist
        """
        path = self._instrument_path(instrument_id)
        if not path.exists():
            raise InstrumentNotFoundError(instrument_id)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return Instrument.from_dict(data)

    def exists(self, instrument_id: str) -> bool:
        """Check if instrument file exists on disk."""
        return self._instrument_path(instrument_id).exists()

    def list_ids(self) -> List[str]:
        """List all instrument IDs that have files on disk."""
        return sorted(p.stem for p in self.base_path.glob("*.json"))

    def load_all(self) -> InstrumentCatalogue:
        """Load all instruments from disk into a catalogue."""
        catalogue = InstrumentCatalogue()
        for instrument_id in self.list_ids():
            instrument = self.load(instrument_id)
            catalogue.register(instrument)
        return catalogue

    def save_catalogue(self, catalogue: InstrumentCatalogue) -> None:
        """Save all instruments in a catalogue to disk."""
        for instrument in catalogue:
            self.save(instrument)

    def delete(self, instrument_id: str) -> bool:
        """Delete an instrument file. Returns True if deleted."""
        path = self._instrument_path(instrument_id)
        if path.exists():
            path.unlink()
            return True
        return False
