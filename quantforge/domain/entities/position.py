from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"

    def inverted(self) -> PositionSide:
        return PositionSide.SHORT if self == PositionSide.LONG else PositionSide.LONG

    @classmethod
    def from_signal_type(cls, signal_type: str) -> PositionSide | None:
        mapping = {"BUY": cls.LONG, "SELL": cls.SHORT}
        return mapping.get(signal_type)


class PositionState(Enum):
    PENDING = auto()
    OPEN = auto()
    CLOSED = auto()
    CANCELLED = auto()


@dataclass
class PositionIntent:
    side: PositionSide
    entry_price: float
    entry_date: str
    stop_loss: float
    take_profit: float
    vol: float = 0.01
    confidence: float = 0.0

    @classmethod
    def from_price_and_vol(
        cls,
        side: PositionSide,
        entry_price: float,
        entry_date: str,
        vol: float,
        sl_mult: float = 1.0,
        tp_mult: float = 2.5,
    ) -> PositionIntent:
        if side == PositionSide.LONG:
            sl = entry_price * (1 - vol * sl_mult)
            tp = entry_price * (1 + vol * tp_mult)
        else:
            sl = entry_price * (1 + vol * sl_mult)
            tp = entry_price * (1 - vol * tp_mult)
        return cls(side=side, entry_price=entry_price, entry_date=entry_date, stop_loss=sl, take_profit=tp, vol=vol)

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT
