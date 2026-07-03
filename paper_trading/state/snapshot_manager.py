import json
import logging
import os
import time
from dataclasses import asdict

from paper_trading.state import CONTRACT_VERSION, EngineSnapshot, atomic_write_json, sanitize

logger = logging.getLogger("eigencapital.state_store")


class _SnapshotManager:
    """JSON state snapshot save/load with monotonic-time TTL cache."""

    _sequence_counter: int = 0

    def __init__(self, state_path: str, cache_ttl: float = 1.0):
        self._state_path = state_path
        self._cache_ttl = cache_ttl
        self._cache: tuple[EngineSnapshot, float] | None = None

    def save(self, snapshot: EngineSnapshot) -> None:
        _SnapshotManager._sequence_counter += 1
        snapshot.sequence_id = _SnapshotManager._sequence_counter
        snapshot.contract_version = CONTRACT_VERSION
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        data = sanitize(asdict(snapshot))
        atomic_write_json(self._state_path, data)
        self._cache = (snapshot, time.monotonic())

    def load(self) -> EngineSnapshot | None:
        if self._cache is not None:
            cached, expiry = self._cache
            if time.monotonic() < expiry:
                return cached
            self._cache = None
        if not os.path.exists(self._state_path):
            return None
        try:
            with open(self._state_path) as f:
                data = json.load(f)

            # Verify checksum
            stored_checksum = data.pop("_checksum", None)
            if stored_checksum is not None:
                import hashlib
                computed = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
                if computed != stored_checksum:
                    logger.error("State checksum mismatch: computed=%s stored=%s — state may be corrupt", computed, stored_checksum)
                    return None

            snapshot = EngineSnapshot.from_dict(data)
            version = getattr(snapshot, "contract_version", 0)
            if version < CONTRACT_VERSION:
                logger.warning(
                    "Snapshot contract_version=%d < current=%d — fields may be missing",
                    version,
                    CONTRACT_VERSION,
                )
            elif version > CONTRACT_VERSION:
                logger.error(
                    "Snapshot contract_version=%d > current=%d — possibly incompatible",
                    version,
                    CONTRACT_VERSION,
                )
                return None
            self._cache = (snapshot, time.monotonic() + self._cache_ttl)
            return snapshot
        except Exception as e:
            logger.warning("Failed to load state snapshot: %s", e)
            return None
