"""Market Schedule — asset-agnostic trading calendar abstraction.

Provides:
- Session type classification (WEEKDAY, EXTENDED, CONTINUOUS_24_7, CUSTOM)
- Market open/close/maintenance detection
- Next open/close/maintenance queries
- Trading day computation
- 4 independent availability states (Market, Data, Broker, Strategy)

Design rules:
- Every instrument declares an authoritative trading schedule
- Risk monitoring continues even when market is closed
- No implicit weekday/weekend assumptions
- Asset-agnostic: FX, equities, futures, crypto, metals, commodities
- Configuration-driven, not hardcoded
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════


class SessionType(str, Enum):
    """Trading session type."""

    WEEKDAY = "WEEKDAY"  # Mon-Fri, fixed hours (FX, equities)
    EXTENDED = "EXTENDED"  # Extended hours (some futures)
    CONTINUOUS_24_7 = "CONTINUOUS_24_7"  # 24/7 with maintenance windows (crypto)
    CUSTOM = "CUSTOM"  # Custom schedule


class MarketAvailability(str, Enum):
    """Can the instrument trade right now?"""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MAINTENANCE = "MAINTENANCE"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


class DataAvailability(str, Enum):
    """Do we have sufficiently fresh prices?"""

    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class BrokerAvailability(str, Enum):
    """Can we communicate with the execution venue?"""

    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


class StrategyEligibility(str, Enum):
    """Does the strategy permit trading right now?"""

    ELIGIBLE = "ELIGIBLE"
    SUPPRESSED = "SUPPRESSED"


# ═══════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════


@dataclass
class MaintenanceWindow:
    """A scheduled maintenance period."""

    day_of_week: int | None = None  # 0=Mon..6=Sun, None = any day
    start_time: dt_time = dt_time(0, 0)
    end_time: dt_time = dt_time(0, 30)
    description: str = ""

    def contains(self, dt: datetime) -> bool:
        """Check if a datetime falls within this maintenance window."""
        if self.day_of_week is not None and dt.weekday() != self.day_of_week:
            return False
        t = dt.time()
        if self.start_time <= self.end_time:
            return self.start_time <= t < self.end_time
        else:
            # Spans midnight (e.g., 23:00 → 01:00)
            return t >= self.start_time or t < self.end_time


@dataclass
class TradingSession:
    """A trading session within a day."""

    open_time: dt_time
    close_time: dt_time
    timezone: str = "UTC"

    def contains(self, dt: datetime) -> bool:
        """Check if a datetime falls within this session."""
        t = dt.time()
        # open == close means 24h session (always open)
        if self.open_time == self.close_time:
            return True
        if self.open_time <= self.close_time:
            return self.open_time <= t < self.close_time
        else:
            # Spans midnight
            return t >= self.open_time or t < self.close_time


@dataclass
class MarketSchedule:
    """Authoritative trading schedule for an instrument.

    Every instrument gets one of these from configuration.
    All components (signal, risk, execution, reconciliation,
    watchdog, evidence) consume this schedule.
    """

    instrument: str
    session_type: SessionType
    timezone: str = "UTC"
    trading_sessions: List[TradingSession] = field(default_factory=list)
    maintenance_windows: List[MaintenanceWindow] = field(default_factory=list)
    trading_days_per_year: int = 252
    bars_per_trading_day: int = 24
    details: Dict[str, Any] = field(default_factory=dict)

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Is the market open at the given time?

        Checks:
        1. Is it a trading day? (for WEEKDAY: Mon-Fri)
        2. Is it within a trading session?
        3. Is it NOT in a maintenance window?
        4. Is the instrument not HALTED?
        """
        dt = dt or datetime.now(UTC)

        if self.session_type == SessionType.CONTINUOUS_24_7:
            # 24/7: always open unless in maintenance
            return not self._in_maintenance(dt)

        if self.session_type == SessionType.WEEKDAY:
            # Weekday: Mon-Fri, within session hours
            if dt.weekday() >= 5:  # Saturday=5, Sunday=6
                return False

        if self.session_type == SessionType.EXTENDED:
            # Extended: Mon-Fri (or more), within session hours
            if dt.weekday() >= 5:
                return False

        # Check trading sessions
        if self.trading_sessions:
            in_session = any(s.contains(dt) for s in self.trading_sessions)
            if not in_session:
                return False

        # Check maintenance
        if self._in_maintenance(dt):
            return False

        return True

    def is_tradable(self, dt: datetime | None = None) -> bool:
        """Is the instrument tradable right now?

        Same as is_market_open but can be extended for
        additional strategy-level suppression.
        """
        return self.is_market_open(dt)

    def next_open(self, dt: datetime | None = None) -> datetime:
        """Find the next market open time after the given datetime."""
        dt = dt or datetime.now(UTC)

        if self.session_type == SessionType.CONTINUOUS_24_7:
            # If currently in maintenance, return end of maintenance
            if self._in_maintenance(dt):
                return self._next_maintenance_end(dt)
            return dt  # Always open

        # Search forward day by day (max 14 days)
        for day_offset in range(15):
            check_date = dt + timedelta(days=day_offset)
            if day_offset == 0:
                # Check if there's an open session later today
                if self.is_market_open(check_date):
                    return dt
                continue

            if self.session_type == SessionType.WEEKDAY and check_date.weekday() >= 5:
                continue

            if self.trading_sessions:
                for session in self.trading_sessions:
                    candidate = check_date.replace(
                        hour=session.open_time.hour,
                        minute=session.open_time.minute,
                        second=0,
                        microsecond=0,
                    )
                    if candidate > dt and not self._in_maintenance(candidate):
                        return candidate
            else:
                # No specific sessions — assume market opens at 00:00
                candidate = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
                if candidate > dt and not self._in_maintenance(candidate):
                    return candidate

        # Fallback: 1 hour from now
        return dt + timedelta(hours=1)

    def next_close(self, dt: datetime | None = None) -> datetime:
        """Find the next market close time after the given datetime."""
        dt = dt or datetime.now(UTC)

        if self.session_type == SessionType.CONTINUOUS_24_7:
            # Next maintenance window
            return self._next_maintenance_start(dt)

        if self.trading_sessions:
            for session in self.trading_sessions:
                close_today = dt.replace(
                    hour=session.close_time.hour,
                    minute=session.close_time.minute,
                    second=0,
                    microsecond=0,
                )
                if close_today > dt:
                    return close_today

        # Fallback: end of day
        return dt.replace(hour=23, minute=59, second=59)

    def next_maintenance(self, dt: datetime | None = None) -> datetime | None:
        """Find the next maintenance window start after the given datetime."""
        dt = dt or datetime.now(UTC)
        return self._next_maintenance_start(dt)

    def session_id(self, dt: datetime | None = None) -> str:
        """Return a session identifier for the given datetime."""
        dt = dt or datetime.now(UTC)
        return f"{self.instrument}:{self.session_type.value}:{dt.strftime('%Y-%m-%d:%H')}"

    def trading_day(self, dt: datetime | None = None) -> str:
        """Return the trading day identifier (YYYY-MM-DD)."""
        dt = dt or datetime.now(UTC)
        return dt.strftime("%Y-%m-%d")

    def _in_maintenance(self, dt: datetime) -> bool:
        """Check if the datetime falls in any maintenance window."""
        return any(mw.contains(dt) for mw in self.maintenance_windows)

    def _next_maintenance_start(self, dt: datetime) -> datetime:
        """Find the next maintenance window start."""
        for day_offset in range(8):
            check_date = dt + timedelta(days=day_offset)
            for mw in self.maintenance_windows:
                if mw.day_of_week is not None and check_date.weekday() != mw.day_of_week:
                    continue
                candidate = check_date.replace(
                    hour=mw.start_time.hour,
                    minute=mw.start_time.minute,
                    second=0,
                    microsecond=0,
                )
                if candidate > dt:
                    return candidate
        return dt + timedelta(days=7)

    def _next_maintenance_end(self, dt: datetime) -> datetime:
        """Find when the current/next maintenance window ends."""
        for mw in self.maintenance_windows:
            if mw.contains(dt):
                return dt.replace(
                    hour=mw.end_time.hour,
                    minute=mw.end_time.minute,
                    second=0,
                    microsecond=0,
                )
        return self._next_maintenance_start(dt)


# ═══════════════════════════════════════════════════════════════════
# Market State — 4 independent states
# ═══════════════════════════════════════════════════════════════════


@dataclass
class MarketState:
    """Four independent availability states for an instrument.

    These should NOT be conflated:
    - Market: Can the instrument trade? (schedule-based)
    - Data: Do we have fresh prices? (feed-based)
    - Broker: Can we communicate with the venue? (connection-based)
    - Strategy: Does the strategy permit trading? (logic-based)
    """

    instrument: str
    market: MarketAvailability = MarketAvailability.UNKNOWN
    data: DataAvailability = DataAvailability.UNKNOWN
    broker: BrokerAvailability = BrokerAvailability.DISCONNECTED
    strategy: StrategyEligibility = StrategyEligibility.SUPPRESSED
    authorization: str = "UNKNOWN"
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_tradable(self) -> bool:
        """Can we actually trade right now?"""
        return (
            self.market == MarketAvailability.OPEN
            and self.data == DataAvailability.FRESH
            and self.broker == BrokerAvailability.CONNECTED
            and self.strategy == StrategyEligibility.ELIGIBLE
            and self.authorization == "TRADING_AUTHORIZED"
        )

    @property
    def overall_status(self) -> str:
        """Human-readable overall status."""
        if self.is_tradable:
            return "TRADABLE"
        if self.market == MarketAvailability.CLOSED:
            return "MARKET_CLOSED"
        if self.market == MarketAvailability.MAINTENANCE:
            return "MAINTENANCE"
        if self.data in (DataAvailability.STALE, DataAvailability.MISSING):
            return "DATA_UNAVAILABLE"
        if self.broker != BrokerAvailability.CONNECTED:
            return "BROKER_UNAVAILABLE"
        if self.strategy != StrategyEligibility.ELIGIBLE:
            return "STRATEGY_SUPPRESSED"
        return "BLOCKED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument": self.instrument,
            "market": self.market.value,
            "data": self.data.value,
            "broker": self.broker.value,
            "strategy": self.strategy.value,
            "authorization": self.authorization,
            "is_tradable": self.is_tradable,
            "overall_status": self.overall_status,
            "timestamp": self.timestamp,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════════
# Configuration Loading
# ═══════════════════════════════════════════════════════════════════


def _parse_time(time_str: str) -> dt_time:
    """Parse a time string like '04:00' or '23:30'."""
    parts = time_str.split(":")
    return dt_time(int(parts[0]), int(parts[1]))


def load_market_schedule(config: Dict[str, Any], instrument: str) -> MarketSchedule:
    """Load a MarketSchedule from a configuration dict.

    Supports both TOML and dict input. TOML format:
    [instruments.BTCUSD]
    session_type = "CONTINUOUS_24_7"
    timezone = "UTC"
    trading_days_per_year = 365
    bars_per_trading_day = 288
    asset_class = "crypto"

    [instruments.BTCUSD.sessions]
    open = "00:00"
    close = "00:00"

    [[instruments.BTCUSD.maintenance]]
    day = 5
    start = "04:00"
    end = "04:30"
    """
    session_type_str = config.get("session_type", "WEEKDAY")
    try:
        session_type = SessionType(session_type_str)
    except ValueError:
        session_type = SessionType.CUSTOM

    # Parse trading sessions — TOML uses a single table, legacy uses list
    sessions = []
    sessions_raw = config.get("sessions") or config.get("trading_sessions", [])
    if isinstance(sessions_raw, dict):
        # TOML single session: {open: "00:00", close: "00:00"}
        if sessions_raw.get("open") and sessions_raw.get("close"):
            sessions.append(
                TradingSession(
                    open_time=_parse_time(sessions_raw["open"]),
                    close_time=_parse_time(sessions_raw["close"]),
                    timezone=config.get("timezone", "UTC"),
                )
            )
    elif isinstance(sessions_raw, list):
        for s in sessions_raw:
            sessions.append(
                TradingSession(
                    open_time=_parse_time(s["open"]),
                    close_time=_parse_time(s["close"]),
                    timezone=config.get("timezone", "UTC"),
                )
            )

    # Parse maintenance windows — TOML uses [[array of tables]], legacy uses list
    maintenance = []
    maintenance_raw = config.get("maintenance") or config.get("maintenance_windows", [])
    if isinstance(maintenance_raw, list):
        for mw in maintenance_raw:
            maintenance.append(
                MaintenanceWindow(
                    day_of_week=mw.get("day"),
                    start_time=_parse_time(mw["start"]),
                    end_time=_parse_time(mw["end"]),
                    description=mw.get("description", ""),
                )
            )

    # Build details dict from flat keys
    details: Dict[str, Any] = {}
    for key in ("asset_class", "description"):
        if key in config:
            details[key] = config[key]
    details.update(config.get("details", {}))

    return MarketSchedule(
        instrument=instrument,
        session_type=session_type,
        timezone=config.get("timezone", "UTC"),
        trading_sessions=sessions,
        maintenance_windows=maintenance,
        trading_days_per_year=config.get("trading_days_per_year", 252),
        bars_per_trading_day=config.get("bars_per_trading_day", 24),
        details=details,
    )


def load_schedules_from_file(path: Path) -> Dict[str, MarketSchedule]:
    """Load all market schedules from a TOML config file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    instruments = data.get("instruments", data)
    schedules: Dict[str, MarketSchedule] = {}
    for instrument, config in instruments.items():
        schedules[instrument] = load_market_schedule(config, instrument)
    return schedules


def load_schedules_from_directory(directory: Path) -> Dict[str, MarketSchedule]:
    """Load all market schedules from a directory of JSON files."""
    schedules: Dict[str, MarketSchedule] = {}
    if not directory.exists():
        return schedules
    for path in sorted(directory.glob("*.json")):
        schedules.update(load_schedules_from_file(path))
    return schedules


# ═══════════════════════════════════════════════════════════════════
# Predefined Schedules
# ═══════════════════════════════════════════════════════════════════


def fx_weekday_schedule(instrument: str) -> MarketSchedule:
    """Standard FX weekday schedule (Mon-Fri, 24h sessions)."""
    return MarketSchedule(
        instrument=instrument,
        session_type=SessionType.WEEKDAY,
        timezone="UTC",
        trading_sessions=[
            TradingSession(open_time=dt_time(0, 0), close_time=dt_time(0, 0)),  # 24h
        ],
        trading_days_per_year=252,
        bars_per_trading_day=24,
    )


def crypto_24_7_schedule(instrument: str) -> MarketSchedule:
    """24/7 crypto schedule with Saturday maintenance."""
    return MarketSchedule(
        instrument=instrument,
        session_type=SessionType.CONTINUOUS_24_7,
        timezone="UTC",
        maintenance_windows=[
            MaintenanceWindow(
                day_of_week=5,  # Saturday
                start_time=dt_time(4, 0),
                end_time=dt_time(4, 30),
                description="Saturday maintenance",
            ),
        ],
        trading_days_per_year=365,
        bars_per_trading_day=288,
    )


def metals_weekday_schedule(instrument: str) -> MarketSchedule:
    """Standard metals schedule (Sun evening - Fri evening)."""
    return MarketSchedule(
        instrument=instrument,
        session_type=SessionType.WEEKDAY,
        timezone="UTC",
        trading_sessions=[
            TradingSession(open_time=dt_time(22, 0), close_time=dt_time(22, 0)),  # ~24h
        ],
        trading_days_per_year=252,
        bars_per_trading_day=24,
    )


# Default schedule registry
DEFAULT_SCHEDULES: Dict[str, SessionType] = {
    "forex": SessionType.WEEKDAY,
    "forex_excluded": SessionType.WEEKDAY,
    "metals": SessionType.WEEKDAY,
    "indices": SessionType.WEEKDAY,
    "energy": SessionType.WEEKDAY,
    "crypto": SessionType.CONTINUOUS_24_7,
}


def get_default_schedule(instrument: str, asset_class: str) -> MarketSchedule:
    """Get a default schedule for an instrument based on its asset class."""
    session_type = DEFAULT_SCHEDULES.get(asset_class, SessionType.WEEKDAY)

    if session_type == SessionType.CONTINUOUS_24_7:
        return crypto_24_7_schedule(instrument)
    elif asset_class == "metals":
        return metals_weekday_schedule(instrument)
    else:
        return fx_weekday_schedule(instrument)
