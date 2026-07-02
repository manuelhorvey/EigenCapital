from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from eigencapital.domain.entities.position import PositionSide


@dataclass
class Trade:
    asset: str
    side: PositionSide
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    reason: str
    return_pct: float
    pnl: float
    total_pnl: float
    realized_r: float
    bars: int
    sl_price: float | None = None
    tp_price: float | None = None
    vol_at_entry: float | None = None
    confidence_at_entry: float | None = None
    archetype_at_entry: str | None = None
    mae: float | None = None
    mfe: float | None = None
    entry_slippage_bps: float | None = None
    exit_slippage_bps: float | None = None
    fill_qty_ratio: float | None = None
    gap_fill: bool | None = None
    partial_fill: bool | None = None
    latency_bars: int | None = None

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> Trade:
        side = PositionSide(data["side"]) if isinstance(data.get("side"), str) else data.get("side")

        def _f(key: str) -> float | None:
            v = data.get(key)
            return float(v) if v is not None else None

        return cls(
            asset=data["asset"],
            side=side,
            entry_price=float(data["entry_price"]),
            exit_price=float(data["exit_price"]),
            entry_date=str(data["entry_date"]),
            exit_date=str(data["exit_date"]),
            reason=str(data["reason"]),
            return_pct=float(data["return_pct"]),
            pnl=float(data["pnl"]),
            total_pnl=float(data["total_pnl"]),
            realized_r=float(data["realized_r"]),
            bars=int(data["bars"]),
            sl_price=_f("sl_price"),
            tp_price=_f("tp_price"),
            vol_at_entry=_f("vol_at_entry"),
            confidence_at_entry=_f("confidence_at_entry"),
            archetype_at_entry=str(data["archetype_at_entry"]) if data.get("archetype_at_entry") else None,
            mae=_f("mae"),
            mfe=_f("mfe"),
            entry_slippage_bps=_f("entry_slippage_bps"),
            exit_slippage_bps=_f("exit_slippage_bps"),
            fill_qty_ratio=_f("fill_qty_ratio"),
            gap_fill=bool(data["gap_fill"]) if data.get("gap_fill") is not None else None,
            partial_fill=bool(data["partial_fill"]) if data.get("partial_fill") is not None else None,
            latency_bars=int(data["latency_bars"]) if data.get("latency_bars") is not None else None,
        )


@dataclass
class TradeLog:
    trades: list[Trade] = field(default_factory=list)

    def add(self, trade: Trade) -> None:
        self.trades.append(trade)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losing_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winning_trades) / len(self.trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def profit_factor(self) -> float:
        gross_wins = sum(t.pnl for t in self.winning_trades)
        gross_losses = abs(sum(t.pnl for t in self.losing_trades))
        if gross_losses == 0:
            return float("inf") if gross_wins > 0 else 0.0
        return gross_wins / gross_losses

    @property
    def avg_return(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.return_pct for t in self.trades) / len(self.trades)

    @property
    def avg_r_multiple(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.realized_r for t in self.trades) / len(self.trades)
