"""Domain model: Instrument.

Canonical representation of a tradable instrument with immutable metadata.
All data pipelines look up metadata by instrument_id.

Invariants:
- instrument_id is the primary key, unique and immutable
- tick_size > 0
- tick_value > 0
- price_precision >= 0
- lot_size > 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, ClassVar
import hashlib


INFINITY = float("inf")


@dataclass(frozen=True)
class Instrument:
    """Immutable instrument metadata.

    Attributes:
        instrument_id: Primary key, e.g. "ES", "NQ_2403", "EUR_USD"
        symbol: Human-readable symbol, e.g. "S&P 500 E-mini"
        asset_class: InstrumentAssetClass enum
        venue: Exchange or datafeed venue
        quote_currency: Base currency for pricing, e.g. "USD"
        tick_size: Minimum price movement (> 0)
        tick_value: Monetary value per tick (> 0)
        lot_size: Trading lot size (> 0)
        price_precision: Decimal places for display (>= 0)
        trading_calendar: Optional calendar of trading holidays
        timezone: Instrument trading timezone, IANA format
        expiration_rule: For futures: months/LTD convention
        currency_conversion_rate: Rate to base currency, 1.0 if already USD
        metadata_version: Version for catalogue updates
    """

    instrument_id: str
    symbol: str
    asset_class: str  # Will be validated via InstrumentAssetClass below
    venue: str
    quote_currency: str
    tick_size: float
    tick_value: float
    lot_size: float
    price_precision: int
    trading_calendar: Optional[str] = None
    timezone: Optional[str] = None
    expiration_rule: Optional[str] = None
    currency_conversion_rate: float = 1.0
    metadata_version: str = "v1"

    # Class-level registry for cross-model references

    def __post_init__(self) -> None:
        # Validate invariants
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be > 0, got {self.tick_size}")
        if self.tick_value <= 0:
            raise ValueError(f"tick_value must be > 0, got {self.tick_value}")
        if self.lot_size <= 0:
            raise ValueError(f"lot_size must be > 0, got {self.lot_size}")
        if self.price_precision < 0:
            raise ValueError(f"price_precision must be >= 0, got {self.price_precision}")
        if self.currency_conversion_rate <= 0:
            raise ValueError(
                f"currency_conversion_rate must be > 0, got {self.currency_conversion_rate}"
            )
        if self.instrument_id in self._registry:
            raise ValueError(
                f"Duplicate instrument_id: {self.instrument_id}. "
                "instrument_id must be unique across the system."
            )
        self._registry[self.instrument_id] = self

    def __hash__(self) -> int:
        return hash(self.instrument_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Instrument):
            return NotImplemented
        return self.instrument_id == other.instrument_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "venue": self.venue,
            "quote_currency": self.quote_currency,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "lot_size": self.lot_size,
            "price_precision": self.price_precision,
            "trading_calendar": self.trading_calendar,
            "timezone": self.timezone,
            "expiration_rule": self.expiration_rule,
            "currency_conversion_rate": self.currency_conversion_rate,
            "metadata_version": self.metadata_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Instrument:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Instrument(
            instrument_id=d["instrument_id"],
            symbol=d["symbol"],
            asset_class=d["asset_class"],
            venue=d["venue"],
            quote_currency=d["quote_currency"],
            tick_size=float(d["tick_size"]),
            tick_value=float(d["tick_value"]),
            lot_size=float(d["lot_size"]),
            price_precision=int(d["price_precision"]),
            trading_calendar=d.get("trading_calendar"),
            timezone=d.get("timezone"),
            expiration_rule=d.get("expiration_rule"),
            currency_conversion_rate=float(d.get("currency_conversion_rate", 1.0)),
            metadata_version=d.get("metadata_version", "v1"),
        )

    def config_hash(self) -> str:
        """Hash of instrument configuration (stable across serialization)."""
        data = self.to_dict()
        # Sort keys for deterministic hash
        sorted_data = dict(sorted(data.items()))
        payload = str(sorted_data).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


# Convenience enum-like constants (kept as strings for Pydantic-free simplicity)
INSTRUMENT_ASSET_CLASSES = {
    "EQUITY_FUTURE",
    "FX",
    "EQUITY",
    "CRYPTO",
    "RATES",
}


def validate_asset_class(asset_class: str) -> None:
    """Validate asset class is one of the permitted values."""
    if asset_class not in INSTRUMENT_ASSET_CLASSES:
        raise ValueError(
            f"Invalid asset_class: {asset_class}. "
            f"Must be one of {INSTRUMENT_ASSET_CLASSES}"
        )


Instrument._registry = {}
