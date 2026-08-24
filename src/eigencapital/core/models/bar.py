"""Domain model: Bar.

Canonical OHLCV bar with unambiguous UTC timestamps.

Invariants:
- timestamp_utc == bar_end_utc (interval end timestamp, universal)
- bar_start_utc < bar_end_utc
- open, high, low, close are finite floats
- volume >= 0
- bar_interval determines data resolution
- No NaN or infinite prices
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import hashlib


@dataclass(frozen=True)
class Bar:
    """Canonical market bar with unambiguous UTC timestamps.

    A bar represents OHLCV data at a fixed interval for a single instrument.

    Invariant: timestamp_utc == bar_end_utc (the interval's end timestamp).
    This prevents look-ahead errors by making the closure time explicit.

    Attributes:
        instrument_id: FK → Instrument.instrument_id
        timestamp_utc: Interval END timestamp, UTC-aware (INVARIANT)
        bar_start_utc: Interval START timestamp, UTC-aware
        bar_end_utc: Interval END timestamp (= timestamp_utc, INVARIANT)
        open: Bar open price (finite, > 0)
        high: Bar high price (finite, > 0) >= open, >= close
        low: Bar low price (finite, > 0) <= open, <= close
        close: Bar close price (finite, > 0)
        volume: Trading volume (>= 0)
        vwap: Volume-weighted average price (optional, > 0 if present)
        source: Datafeed/venue identifier
        bar_interval: Resolution of the bar (1m, 5m, 15m, 1h, daily, weekly)
        data_version: Dataset catalogue version identifier
    """

    instrument_id: str
    timestamp_utc: str  # ISO-8601 UTC string, e.g. "2024-03-15T09:35:00Z"
    bar_start_utc: str  # ISO-8601 UTC string
    bar_end_utc: str  # Must equal timestamp_utc (enforced by __post_init__)
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    source: Optional[str] = None
    bar_interval: str = "1m"  # Default: 1-minute
    data_version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # INVARIANT: timestamp_utc == bar_end_utc
        if self.timestamp_utc != self.bar_end_utc:
            raise ValueError(
                f"Bar invariant violated: timestamp_utc ({self.timestamp_utc}) "
                f"!= bar_end_utc ({self.bar_end_utc})"
            )

        # INVARIANT: bar_start_utc < bar_end_utc (chronological order)
        if self.bar_start_utc >= self.timestamp_utc:
            raise ValueError(
                f"Bar invariant violated: bar_start_utc ({self.bar_start_utc}) "
                f"must be < timestamp_utc ({self.timestamp_utc})"
            )

        # Validate prices are finite (no NaN, no infinity)
        for price_name in ("open", "high", "low", "close"):
            price = getattr(self, price_name)
            if not isinstance(price, (int, float)):
                raise ValueError(f"{price_name} must be numeric, got {type(price)}")
            if math.isnan(price) or math.isinf(price):
                raise ValueError(
                    f"{price_name} must be finite (no NaN/infinity), got {price}"
                )
            if price <= 0:
                raise ValueError(f"{price_name} must be > 0, got {price}")

        # Validate price hierarchy: high >= max(open, close), low <= min(open, close)
        if self.high < max(self.open, self.close):
            raise ValueError(
                f"Bar invariant violated: high ({self.high}) < max(open, close) "
                f"= {max(self.open, self.close)}"
            )
        if self.low > min(self.open, self.close):
            raise ValueError(
                f"Bar invariant violated: low ({self.low}) > min(open, close) "
                f"= {min(self.open, self.close)}"
            )

        # Validate volume >= 0
        if self.volume < 0:
            raise ValueError(f"volume must be >= 0, got {self.volume}")

        # Validate vwap if present
        if self.vwap is not None:
            if math.isnan(self.vwap) or math.isinf(self.vwap):
                raise ValueError("vwap must be finite (no NaN/infinity)")
            if self.vwap <= 0:
                raise ValueError("vwap must be > 0 if present")
            # vwap should be between low and high (typically, inclusive)
            if self.vwap < self.low or self.vwap > self.high:
                # This is a warning, not hard invariant, but log it
                pass

        # Registry check for duplicate instrument+timestamp
        key = (self.instrument_id, self.timestamp_utc)
        if key in self._registry:
            raise ValueError(
                f"Duplicate bar: instrument={self.instrument_id}, "
                f"timestamp={self.timestamp_utc}. Bars must be unique per "
                f"instrument+timestamp."
            )
        self._registry[key] = (self.instrument_id, self.timestamp_utc)

    def __hash__(self) -> int:
        return hash((self.instrument_id, self.timestamp_utc, self.bar_interval))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Bar):
            return NotImplemented
        return (
            self.instrument_id == other.instrument_id
            and self.timestamp_utc == other.timestamp_utc
            and self.bar_interval == other.bar_interval
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "bar_start_utc": self.bar_start_utc,
            "bar_end_utc": self.bar_end_utc,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap,
            "source": self.source,
            "bar_interval": self.bar_interval,
            "data_version": self.data_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Bar:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Bar(
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            bar_start_utc=str(d["bar_start_utc"]),
            bar_end_utc=str(d["bar_end_utc"]),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=int(d["volume"]),
            vwap=float(d["vwap"]) if d.get("vwap") is not None else None,
            source=str(d["source"]) if d.get("source") is not None else None,
            bar_interval=str(d.get("bar_interval", "1m")),
            data_version=str(d.get("data_version", "v1")),
        )

    def config_hash(self) -> str:
        """Hash of bar configuration (stable across serialization)."""
        data = self.to_dict()
        sorted_data = dict(sorted(data.items()))
        payload = str(sorted_data).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def side(self) -> str:
        """Derive side from price movement: 'up' if close > open, 'down' otherwise."""
        return "up" if self.close > self.open else "down"


@dataclass(frozen=True)
class BarInterval:
    """Bar interval enumeration with resolution metadata."""

    # Common intraday intervals
    INTRADAY_1MIN = "1m"
    INTRADAY_5MIN = "5m"
    INTRADAY_15MIN = "15m"
    INTRADAY_30MIN = "30m"
    INTRADAY_1H = "1h"
    INTRADAY_2H = "2h"
    INTRADAY_4H = "4h"

    # Swing intervals
    SWING_DAILY = "1d"
    SWEEKLY = "1w"

    # Valid values (for validation)
    VALID_INTERVALS = {
        INTRADAY_1MIN,
        INTRADAY_5MIN,
        INTRADAY_15MIN,
        INTRADAY_30MIN,
        INTRADAY_1H,
        INTRADAY_2H,
        INTRADAY_4H,
        SWING_DAILY,
        SWEEKLY,
    }

    value: str

    def __post_init__(self) -> None:
        if self.value not in self.VALID_INTERVALS:
            raise ValueError(
                f"Invalid bar_interval: {self.value}. "
                f"Must be one of {self.VALID_INTERVALS}"
            )


Bar._registry = {}
