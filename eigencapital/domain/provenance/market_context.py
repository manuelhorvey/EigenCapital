"""MarketContext — frozen snapshot of market data at decision time.

Captured in the pre-phase of each orchestrator cycle, before any
inference or decision logic runs.  Contains the OHLCV bars, spread,
session metadata, and macro state actually used for the cycle.

This context is independent of the feature pipeline: it represents
what the market looked like, not what the model derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketContext:
    asset: str
    ticker: str
    close_price: float
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume: float | None = None
    spread_bps: float | None = None
    spread_tier: str = "fx_cross"
    session_hour_utc: int | None = None
    in_session: bool = False
    n_bars: int = 0
    macro_timestamp: str | None = None
    dxy_level: float | None = None
    vix_level: float | None = None
    spx_level: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "ticker": self.ticker,
            "close_price": self.close_price,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "volume": self.volume,
            "spread_bps": self.spread_bps,
            "spread_tier": self.spread_tier,
            "session_hour_utc": self.session_hour_utc,
            "in_session": self.in_session,
            "n_bars": self.n_bars,
            "macro_timestamp": self.macro_timestamp,
            "dxy_level": self.dxy_level,
            "vix_level": self.vix_level,
            "spx_level": self.spx_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketContext:
        return cls(**data)
