"""Information-driven bars — volume and notional bar aggregation.

Time bars sample the market on a clock; information bars sample it by
activity. Volume bars close after a fixed amount of traded volume;
notional bars (the asset-agnostic generalization of dollar bars) close
after a fixed traded value. Both carry VWAP and transaction count, and
exhibit statistical properties closer to IID returns than time bars
(Jansen 2020, Ch. 2 "From ticks to bars").

Design rules (fail-closed):
- Ticks with non-positive price or volume, or regressing timestamps,
  raise InformationBarError — never silently repaired.
- The threshold is checked AFTER each tick: the closing tick belongs to
  the bar it completes.
- A trailing partial bar is emitted with complete=False.

Usage:
    aggregator = NotionalBarAggregator(instrument_id="ES", threshold=50_000_000)
    bars = aggregator.aggregate(ticks)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from eigencapital.data.loaders.base import RawRecord


class InformationBarError(ValueError):
    """Raised when ticks cannot be aggregated into information bars."""

    def __init__(self, message: str, tick_index: Optional[int] = None) -> None:
        suffix = f" (tick index {tick_index})" if tick_index is not None else ""
        super().__init__(f"{message}{suffix}")
        self.tick_index = tick_index


@dataclass(frozen=True)
class TradeTick:
    """A single trade print in UTC.

    Invariants:
        - price > 0 and finite
        - volume > 0
        - timestamp_utc is a non-empty ISO-8601 string
    """

    timestamp_utc: str
    price: float
    volume: int

    def __post_init__(self) -> None:
        import math

        if not self.timestamp_utc:
            raise InformationBarError("timestamp_utc must be non-empty")
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float)):
            raise InformationBarError(f"price must be numeric, got {type(self.price)}")
        if math.isnan(self.price) or math.isinf(self.price) or self.price <= 0:
            raise InformationBarError(f"price must be finite and > 0, got {self.price}")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise InformationBarError(
                f"volume must be an int, got {type(self.volume)}"
            )
        if self.volume <= 0:
            raise InformationBarError(f"volume must be > 0, got {self.volume}")

    @classmethod
    def from_raw_record(cls, record: RawRecord) -> TradeTick:
        """Build a TradeTick from a loader RawRecord."""
        price = record.data.get("price")
        volume = record.data.get("volume", record.data.get("size"))
        if price is None or volume is None:
            raise InformationBarError(
                f"Tick record missing price/volume fields: {sorted(record.data)}"
            )
        try:
            return cls(
                timestamp_utc=record.timestamp,
                price=float(price),
                volume=int(float(volume)),
            )
        except (TypeError, ValueError) as e:
            raise InformationBarError(
                f"Cannot parse tick from raw record: price={price!r}, "
                f"volume={volume!r}"
            ) from e


@dataclass(frozen=True)
class InformationBar:
    """A volume- or notional-threshold bar with VWAP and trade count.

    Invariants:
        - open/high/low/close finite and > 0
        - high >= max(open, close); low <= min(open, close)
        - low <= vwap <= high
        - volume >= 0; trade_count >= 1
        - notional == sum(price * volume) over constituent ticks
        - timestamp_close_utc >= timestamp_open_utc
    """

    instrument_id: str
    bar_type: str  # "volume" | "notional"
    threshold: float
    timestamp_open_utc: str
    timestamp_close_utc: str
    open: float
    high: float
    low: float
    close: float
    vwap: float
    volume: int
    trade_count: int
    notional: float
    complete: bool

    def __post_init__(self) -> None:
        import math

        if self.bar_type not in ("volume", "notional"):
            raise InformationBarError(
                f"bar_type must be 'volume' or 'notional', got '{self.bar_type}'"
            )
        for name in ("open", "high", "low", "close", "vwap"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or math.isnan(value)
                or math.isinf(value)
                or value <= 0
            ):
                raise InformationBarError(
                    f"{name} must be finite and > 0, got {value}"
                )
        if self.high < max(self.open, self.close):
            raise InformationBarError(
                f"high ({self.high}) < max(open, close)"
            )
        if self.low > min(self.open, self.close):
            raise InformationBarError(f"low ({self.low}) > min(open, close)")
        if not (self.low - 1e-9 <= self.vwap <= self.high + 1e-9):
            raise InformationBarError(
                f"vwap ({self.vwap}) outside [low, high] = "
                f"[{self.low}, {self.high}]"
            )
        if self.volume < 0:
            raise InformationBarError(f"volume must be >= 0, got {self.volume}")
        if self.trade_count < 1:
            raise InformationBarError(
                f"trade_count must be >= 1, got {self.trade_count}"
            )
        if self.timestamp_close_utc < self.timestamp_open_utc:
            raise InformationBarError(
                f"timestamp_close_utc ({self.timestamp_close_utc}) precedes "
                f"timestamp_open_utc ({self.timestamp_open_utc})"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "instrument_id": self.instrument_id,
            "bar_type": self.bar_type,
            "threshold": round(float(self.threshold), 6),
            "timestamp_open_utc": self.timestamp_open_utc,
            "timestamp_close_utc": self.timestamp_close_utc,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "vwap": round(self.vwap, 10),
            "volume": self.volume,
            "trade_count": self.trade_count,
            "notional": round(self.notional, 6),
            "complete": self.complete,
        }


def _iso_key(timestamp: str) -> str:
    """Normalize an ISO-8601 timestamp for lexicographic ordering."""
    normalized = timestamp.strip().replace(" ", "T")
    return normalized


class BaseInformationBarAggregator(ABC):
    """Shared aggregation machinery for threshold-based bars.

    Subclasses define the accumulation metric (cumulative volume or
    cumulative notional). Aggregation is streaming: memory holds only
    the current partial bar.
    """

    def __init__(
        self,
        instrument_id: str,
        source: str = "",
        dataset_version: str = "v1",
    ) -> None:
        if not instrument_id:
            raise InformationBarError("instrument_id must be non-empty")
        self.instrument_id = instrument_id
        self.source = source
        self.dataset_version = dataset_version

    @property
    @abstractmethod
    def bar_type(self) -> str:
        ...

    @abstractmethod
    def _metric(self, tick: TradeTick) -> float:
        """Activity contributed by a single tick toward the threshold."""
        ...

    @abstractmethod
    def _threshold(self) -> float:
        ...

    def aggregate(self, ticks: Sequence[TradeTick]) -> List[InformationBar]:
        """Aggregate ticks into information bars.

        Args:
            ticks: Trades in chronological order (enforced)

        Returns:
            InformationBars; the final bar has complete=False unless the
            stream ends exactly on a threshold boundary

        Raises:
            InformationBarError: on invalid or out-of-order ticks
        """
        bars: List[InformationBar] = []
        current_ticks: List[TradeTick] = []
        accumulated = 0.0

        for index, tick in enumerate(ticks):
            if current_ticks:
                prev = _iso_key(current_ticks[-1].timestamp_utc)
                if _iso_key(tick.timestamp_utc) < prev:
                    raise InformationBarError(
                        f"Out-of-order tick: {tick.timestamp_utc} precedes "
                        f"{current_ticks[-1].timestamp_utc}",
                        tick_index=index,
                    )
            current_ticks.append(tick)
            accumulated += self._metric(tick)

            if accumulated >= self._threshold():
                bars.append(self._emit(current_ticks, accumulated, True))
                current_ticks = []
                accumulated = 0.0

        if current_ticks:
            bars.append(self._emit(current_ticks, accumulated, False))
        return bars

    def aggregate_records(self, records: Sequence[RawRecord]) -> List[InformationBar]:
        """Aggregate loader RawRecords (price/volume fields) into bars."""
        ticks = [TradeTick.from_raw_record(r) for r in records]
        return self.aggregate(ticks)

    def _emit(
        self, ticks: List[TradeTick], accumulated: float, complete: bool
    ) -> InformationBar:
        prices = [t.price for t in ticks]
        volume = sum(t.volume for t in ticks)
        notional = sum(t.price * t.volume for t in ticks)
        vwap = notional / volume if volume > 0 else prices[0]
        return InformationBar(
            instrument_id=self.instrument_id,
            bar_type=self.bar_type,
            threshold=self._threshold(),
            timestamp_open_utc=ticks[0].timestamp_utc,
            timestamp_close_utc=ticks[-1].timestamp_utc,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            vwap=vwap,
            volume=volume,
            trade_count=len(ticks),
            notional=notional,
            complete=complete,
        )


class VolumeBarAggregator(BaseInformationBarAggregator):
    """Bars that close once cumulative traded volume reaches a threshold."""

    def __init__(
        self,
        instrument_id: str,
        threshold_volume: int,
        source: str = "",
        dataset_version: str = "v1",
    ) -> None:
        super().__init__(instrument_id, source, dataset_version)
        if threshold_volume <= 0:
            raise InformationBarError("threshold_volume must be > 0")
        self.threshold_volume = int(threshold_volume)

    @property
    def bar_type(self) -> str:
        return "volume"

    def _metric(self, tick: TradeTick) -> float:
        return float(tick.volume)

    def _threshold(self) -> float:
        return float(self.threshold_volume)


class NotionalBarAggregator(BaseInformationBarAggregator):
    """Bars that close once cumulative traded value reaches a threshold.

    Asset-agnostic replacement for dollar bars: the quote currency is
    whatever the instrument trades in.
    """

    def __init__(
        self,
        instrument_id: str,
        threshold_notional: float,
        source: str = "",
        dataset_version: str = "v1",
    ) -> None:
        super().__init__(instrument_id, source, dataset_version)
        if threshold_notional <= 0:
            raise InformationBarError("threshold_notional must be > 0")
        self.threshold_notional = float(threshold_notional)

    @property
    def bar_type(self) -> str:
        return "notional"

    def _metric(self, tick: TradeTick) -> float:
        return tick.price * tick.volume

    def _threshold(self) -> float:
        return self.threshold_notional
