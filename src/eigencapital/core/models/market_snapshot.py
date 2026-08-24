"""Domain model: MarketSnapshot.

Intraday/live market state for strategy consumption.

Invariants:
- Optional fields are truly None (never fake zeros)
- data_quality tracks availability state
- At least bid_price or ask_price must be present for a valid snapshot
- mid_price = (bid_price + ask_price) / 2 if both available
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math


class DataQualityStatus:
    """Data quality status enum.

    Distinguishes "no signal" from "signal unavailable because data failed validation."
    """

    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    STALE = "STALE"


@dataclass(frozen=True)
class MarketSnapshot:
    """Real-time market state for intraday/live strategy consumption.

    Emitted by data feed handler, consumed by strategies.
    Contains optional fields that may be unavailable for some markets.

    Invariant: bid_price and ask_price are Optional[float] — never fake zeros.
    data_quality explicitly represents availability state.

    At least bid_price or ask_price must be present for a valid snapshot
    (one of them may be None if the market is auction/opening etc.).
    """

    instrument_id: str
    timestamp_utc: str  # ISO-8601 UTC string
    mid_price: Optional[float] = None
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    trade_count: Optional[int] = None
    vwap: Optional[float] = None
    session: str = "OPEN"  # OPEN, CLOSED, AUCTION
    data_quality: str = DataQualityStatus.VALID
    source: Optional[str] = None

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate data_quality is a known status
        if self.data_quality not in {
            DataQualityStatus.VALID,
            DataQualityStatus.WARNING,
            DataQualityStatus.INVALID,
            DataQualityStatus.STALE,
        }:
            raise ValueError(
                f"Invalid data_quality: {self.data_quality}. "
                f"Must be one of: "
                f"{DataQualityStatus.VALID}, "
                f"{DataQualityStatus.WARNING}, "
                f"{DataQualityStatus.INVALID}, "
                f"{DataQualityStatus.STALE}"
            )

        # Validate timestamps are ISO-8601 UTC format (basic check)
        for ts_name in ("timestamp_utc",):
            ts = getattr(self, ts_name, None)
            if ts is not None:
                # Simple format check: should contain 'T' and end with 'Z' or be parseable
                if "T" not in ts:
                    raise ValueError(f"{ts_name} should be ISO-8601 format, got: {ts}")

        # Validate prices are finite if present
        for price_name in ("mid_price", "bid_price", "ask_price", "last", "vwap"):
            price = getattr(self, price_name, None)
            if price is not None:
                if not isinstance(price, (int, float)):
                    raise ValueError(f"{price_name} must be numeric, got {type(price)}")
                if price is not None and (math.isnan(price) or math.isinf(price)):
                    raise ValueError(f"{price_name} must be finite (no NaN/infinity)")

        # Validate bid_size and ask_size are non-negative if present
        for size_name in ("bid_size", "ask_size"):
            size = getattr(self, size_name, None)
            if size is not None:
                if not isinstance(size, (int, float)):
                    raise ValueError(f"{size_name} must be numeric, got {type(size)}")
                if size < 0:
                    raise ValueError(f"{size_name} must be >= 0, got {size}")

        # Validate volume if present
        if self.volume is not None:
            if not isinstance(self.volume, int):
                raise ValueError(f"volume must be int, got {type(self.volume)}")
            if self.volume < 0:
                raise ValueError(f"volume must be >= 0, got {self.volume}")

        # Validate session is known
        valid_sessions = {"OPEN", "CLOSED", "AUCTION"}
        if self.session not in valid_sessions:
            raise ValueError(
                f"Invalid session: {self.session}. Must be one of {valid_sessions}"
            )

        # Registry check for duplicate snapshots
        key = (self.instrument_id, self.timestamp_utc)
        if key in self._registry:
            raise ValueError(
                f"Duplicate MarketSnapshot: instrument={self.instrument_id}, "
                f"timestamp={self.timestamp_utc}"
            )
        self._registry[key] = key

    def __hash__(self) -> int:
        return hash((self.instrument_id, self.timestamp_utc, self.session))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MarketSnapshot):
            return NotImplemented
        return (
            self.instrument_id == other.instrument_id
            and self.timestamp_utc == other.timestamp_utc
            and self.session == other.session
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "mid_price": self.mid_price,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "last": self.last,
            "volume": self.volume,
            "trade_count": self.trade_count,
            "vwap": self.vwap,
            "session": self.session,
            "data_quality": self.data_quality,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MarketSnapshot:
        """Deserialize from dict (deterministic, keys sorted)."""
        return MarketSnapshot(
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            mid_price=float(d["mid_price"]) if d.get("mid_price") is not None else None,
            bid_price=float(d["bid_price"]) if d.get("bid_price") is not None else None,
            ask_price=float(d["ask_price"]) if d.get("ask_price") is not None else None,
            bid_size=float(d["bid_size"]) if d.get("bid_size") is not None else None,
            ask_size=float(d["ask_size"]) if d.get("ask_size") is not None else None,
            last=float(d["last"]) if d.get("last") is not None else None,
            volume=int(d["volume"]) if d.get("volume") is not None else None,
            trade_count=int(d["trade_count"])
            if d.get("trade_count") is not None
            else None,
            vwap=float(d["vwap"]) if d.get("vwap") is not None else None,
            session=str(d.get("session", "OPEN")),
            data_quality=str(d.get("data_quality", DataQualityStatus.VALID)),
            source=str(d["source"]) if d.get("source") is not None else None,
        )

    @property
    def mid_from_bid_ask(self) -> Optional[float]:
        """Compute mid_price from bid_price and ask_price if both available."""
        if self.bid_price is not None and self.ask_price is not None:
            return (self.bid_price + self.ask_price) / 2.0
        return None

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread if both prices available."""
        if self.bid_price is not None and self.ask_price is not None:
            return self.ask_price - self.bid_price
        return None

    @property
    def is_valid(self) -> bool:
        """Check if snapshot has sufficient data for decision-making."""
        return self.data_quality == DataQualityStatus.VALID and (
            self.bid_price is not None or self.ask_price is not None
        )

    @property
    def is_stale(self) -> bool:
        """Check if snapshot is stale (data quality STALE)."""
        return self.data_quality == DataQualityStatus.STALE


MarketSnapshot._registry = {}
