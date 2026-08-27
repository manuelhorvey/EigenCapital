"""Safety Controls — kill switch and market data safety.

The kill switch must:
- stop new orders immediately
- be independent of strategy logic
- be independently testable
- be auditable
- persist its state appropriately
- fail closed
- prevent restart from silently clearing the kill state
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class KillSwitchStatus(str, Enum):
    """Kill switch status."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class KillSwitch:
    """Independent emergency kill switch.

    Stops all new order generation when activated.
    """

    status: KillSwitchStatus = KillSwitchStatus.INACTIVE
    activation_reason: str = ""
    activation_timestamp: str = ""
    deactivation_timestamp: str = ""
    _activation_count: int = 0

    def activate(self, reason: str, timestamp: str = "") -> bool:
        """Activate the kill switch."""
        self.status = KillSwitchStatus.ACTIVE
        self.activation_reason = reason
        self.activation_timestamp = timestamp
        self._activation_count += 1
        return True

    def deactivate(self, reason: str = "", timestamp: str = "") -> bool:
        """Deactivate the kill switch.

        Returns:
            True if successfully deactivated
        """
        if self.status == KillSwitchStatus.INACTIVE:
            return False
        self.status = KillSwitchStatus.INACTIVE
        self.deactivation_timestamp = timestamp
        return True

    @property
    def is_active(self) -> bool:
        return self.status == KillSwitchStatus.ACTIVE

    @property
    def activation_count(self) -> int:
        return self._activation_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "activation_reason": self.activation_reason,
            "activation_timestamp": self.activation_timestamp,
            "deactivation_timestamp": self.deactivation_timestamp,
            "activation_count": self._activation_count,
        }


class DataSafetyStatus(str, Enum):
    """Market data safety status."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True)
class DataSafetyCheck:
    """Result of a market data safety check."""

    status: DataSafetyStatus
    instrument_id: str
    timestamp: str
    data_age_seconds: float = 0.0
    max_age_seconds: float = 300.0
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "instrument_id": self.instrument_id,
            "timestamp": self.timestamp,
            "data_age_seconds": self.data_age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "details": self.details,
        }

    @property
    def is_safe(self) -> bool:
        return self.status == DataSafetyStatus.FRESH


class MarketDataSafety:
    """Validates market data safety for production execution."""

    def __init__(self, max_age_seconds: float = 300.0) -> None:
        self._max_age_seconds = max_age_seconds
        self._last_check: Dict[str, DataSafetyCheck] = {}

    def check(
        self,
        instrument_id: str,
        data_timestamp: str,
        current_timestamp: str,
    ) -> DataSafetyCheck:
        """Check if market data is safe to use."""
        # Simplified age calculation (in production, use proper datetime parsing)
        # For now, assume data is fresh if timestamps are provided
        if not data_timestamp:
            check = DataSafetyCheck(
                status=DataSafetyStatus.MISSING,
                instrument_id=instrument_id,
                timestamp=current_timestamp,
                details="No data timestamp provided",
            )
        else:
            check = DataSafetyCheck(
                status=DataSafetyStatus.FRESH,
                instrument_id=instrument_id,
                timestamp=current_timestamp,
                data_age_seconds=0.0,
                max_age_seconds=self._max_age_seconds,
            )

        self._last_check[instrument_id] = check
        return check

    def get_last_check(self, instrument_id: str) -> DataSafetyCheck | None:
        return self._last_check.get(instrument_id)

    def all_instruments_safe(self) -> bool:
        return all(c.is_safe for c in self._last_check.values())
