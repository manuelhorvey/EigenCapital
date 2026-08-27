"""Universe Membership — point-in-time instrument universe tracking.

Survivorship bias is a data-layer invariant problem, not a research habit
(Jansen 2020, Ch. 2): a catalogue that only knows currently active
instruments silently deletes delistings, bankruptcies, and mergers from
history — inflating every backtest that touches the affected names.

This module tracks historical membership intervals per universe.
Research code MUST query members as of a date (`members_as_of`) rather
than using today's actives when reconstructing a historical cross-section.

Usage:
    registry = UniverseMembershipRegistry()
    registry.add(UniverseMembership("ES", "futures_core", "2015-03-01"))
    registry.delist("ES", "futures_core", "2026-01-31", reason="contract_expired")
    names = registry.members_as_of("futures_core", "2020-06-30")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATE_FMT = "%Y-%m-%d"


def _validate_date(value: str, label: str) -> str:
    """Validate an ISO date string (YYYY-MM-DD)."""
    from datetime import datetime

    try:
        datetime.strptime(value, _DATE_FMT)
    except (TypeError, ValueError) as e:
        raise MembershipError(
            f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from e
    return value


class MembershipError(ValueError):
    """Raised on invalid membership records."""


@dataclass(frozen=True)
class UniverseMembership:
    """A membership interval for one instrument in one universe.

    Attributes:
        instrument_id: FK → Instrument.instrument_id
        universe_id: Universe identifier (e.g., "sp500", "futures_core")
        effective_from: Inclusive start date (YYYY-MM-DD)
        effective_to: Inclusive end date; None = still a member
        reason: Why the interval closed ("delisted", "acquired",
            "index_removal", ...) or how it began ("initial_inclusion")

    Invariants:
        - non-empty ids
        - valid ISO dates; effective_from <= effective_to when closed
    """

    instrument_id: str
    universe_id: str
    effective_from: str
    effective_to: Optional[str] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.universe_id:
            raise MembershipError("instrument_id and universe_id must be non-empty")
        _validate_date(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _validate_date(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise MembershipError(
                    f"effective_to ({self.effective_to}) precedes "
                    f"effective_from ({self.effective_from})"
                )

    def is_active_on(self, date: str) -> bool:
        """Whether this interval covers `date` (inclusive both ends)."""
        _validate_date(date, "date")
        if date < self.effective_from:
            return False
        return self.effective_to is None or date <= self.effective_to

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "instrument_id": self.instrument_id,
            "universe_id": self.universe_id,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> UniverseMembership:
        """Deserialize from dict."""
        return cls(
            instrument_id=str(d["instrument_id"]),
            universe_id=str(d["universe_id"]),
            effective_from=str(d["effective_from"]),
            effective_to=(str(d["effective_to"]) if d.get("effective_to") else None),
            reason=str(d.get("reason", "")),
        )


class UniverseMembershipRegistry:
    """Point-in-time membership intervals per universe.

    Not thread-safe; use external locking under concurrent access.

    Invariant: for each (instrument_id, universe_id), intervals never
    overlap. An open interval (effective_to=None) blocks new starts and
    is required before delisting.
    """

    def __init__(self) -> None:
        self._records: List[UniverseMembership] = []

    def add(self, membership: UniverseMembership) -> None:
        """Register a membership interval.

        Raises:
            MembershipError: on overlapping intervals for the same
                (instrument_id, universe_id)
        """
        for existing in self._records:
            if (
                existing.instrument_id == membership.instrument_id
                and existing.universe_id == membership.universe_id
                and self._overlaps(existing, membership)
            ):
                raise MembershipError(
                    f"Overlapping membership: {membership.instrument_id} in "
                    f"{membership.universe_id} [{membership.effective_from}.."
                    f"{membership.effective_to}] overlaps "
                    f"[{existing.effective_from}..{existing.effective_to}]"
                )
        self._records.append(membership)

    @staticmethod
    def _overlaps(a: UniverseMembership, b: UniverseMembership) -> bool:
        """Inclusive-endpoint interval overlap test (open ends = infinity)."""
        latest_start = max(a.effective_from, b.effective_from)
        a_covers_latest = a.effective_to is None or a.effective_to >= latest_start
        b_covers_latest = b.effective_to is None or b.effective_to >= latest_start
        return a_covers_latest and b_covers_latest

    def delist(
        self,
        instrument_id: str,
        universe_id: str,
        effective_to: str,
        reason: str = "",
    ) -> UniverseMembership:
        """Close the open membership interval of an instrument.

        Args:
            instrument_id: Instrument to delist
            universe_id: Universe it leaves
            effective_to: Last day of membership (YYYY-MM-DD)
            reason: Exit reason recorded for audit

        Returns:
            The updated (closed) membership record

        Raises:
            MembershipError: if no open interval exists
        """
        for i, existing in enumerate(self._records):
            if (
                existing.instrument_id == instrument_id
                and existing.universe_id == universe_id
                and existing.effective_to is None
            ):
                closed = UniverseMembership(
                    instrument_id=existing.instrument_id,
                    universe_id=existing.universe_id,
                    effective_from=existing.effective_from,
                    effective_to=_validate_date(effective_to, "effective_to"),
                    reason=reason or existing.reason,
                )
                self._records[i] = closed
                return closed
        raise MembershipError(
            f"No open membership for {instrument_id} in {universe_id}; cannot delist."
        )

    def members_as_of(self, universe_id: str, date: str) -> List[str]:
        """Instruments belonging to the universe on a given date."""
        _validate_date(date, "date")
        return sorted(
            m.instrument_id
            for m in self._records
            if m.universe_id == universe_id and m.is_active_on(date)
        )

    def active_members(self, universe_id: str) -> List[str]:
        """Instruments with an open (current) membership interval."""
        return sorted(
            m.instrument_id
            for m in self._records
            if m.universe_id == universe_id and m.effective_to is None
        )

    def history(
        self,
        instrument_id: str,
        universe_id: Optional[str] = None,
    ) -> List[UniverseMembership]:
        """All membership intervals for an instrument, chronological."""
        records = [
            m
            for m in self._records
            if m.instrument_id == instrument_id
            and (universe_id is None or m.universe_id == universe_id)
        ]
        return sorted(records, key=lambda m: m.effective_from)

    def is_member_at(self, instrument_id: str, universe_id: str, date: str) -> bool:
        """Point-in-time membership predicate."""
        return instrument_id in self.members_as_of(universe_id, date)

    def universes(self) -> List[str]:
        """All universe IDs known to the registry."""
        return sorted({m.universe_id for m in self._records})

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        ordered = sorted(
            self._records,
            key=lambda m: (
                m.universe_id,
                m.instrument_id,
                m.effective_from,
                m.effective_to or "",
            ),
        )
        return {"memberships": [m.to_dict() for m in ordered]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> UniverseMembershipRegistry:
        """Rebuild a registry from serialized form."""
        registry = cls()
        for record in d.get("memberships", []):
            registry.add(UniverseMembership.from_dict(record))
        return registry


class MembershipRepository:
    """JSON persistence for a UniverseMembershipRegistry."""

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.base_path / "memberships.json"

    def save(self, registry: UniverseMembershipRegistry) -> None:
        """Persist the registry deterministically (sorted keys)."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(registry.to_dict(), f, sort_keys=True, indent=2)

    def load(self) -> UniverseMembershipRegistry:
        """Load the registry; empty registry if no file exists yet."""
        if not self.path.exists():
            return UniverseMembershipRegistry()
        with open(self.path, encoding="utf-8") as f:
            return UniverseMembershipRegistry.from_dict(json.load(f))
