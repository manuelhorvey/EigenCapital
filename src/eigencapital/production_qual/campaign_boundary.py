"""Campaign Boundary — separates R4-owned positions from pre-existing.

Every trade must be linked to an R4 decision/evidence ID.
Every close must be linked to the corresponding opening order.
No manual trades contaminating campaign results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class TradeOrigin(str, Enum):
    """Origin of a trade."""

    R4_CAMPAIGN = "r4_campaign"
    PRE_EXISTING = "pre_existing"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class TradeStatus(str, Enum):
    """Status of a trade."""

    OPEN = "open"
    CLOSED = "closed"
    PARTIAL_CLOSE = "partial_close"


@dataclass
class TradeRecord:
    """Complete record of a single trade, linked to R4 decision."""

    trade_id: str
    decision_id: str  # links to R4 decision
    evidence_id: str  # links to R4 evidence
    instrument_id: str
    side: str  # "BUY" or "SELL"
    volume: float
    entry_price: float
    entry_timestamp: str
    exit_price: float | None = None
    exit_timestamp: str | None = None
    origin: TradeOrigin = TradeOrigin.UNKNOWN
    status: TradeStatus = TradeStatus.OPEN
    pnl: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    slippage_entry: float = 0.0
    slippage_exit: float = 0.0
    broker_ticket: int | None = None

    def close(self, exit_price: float, exit_timestamp: str) -> None:
        """Close the trade."""
        self.exit_price = exit_price
        self.exit_timestamp = exit_timestamp
        self.status = TradeStatus.CLOSED

        # Compute P&L
        if self.side == "BUY":
            self.pnl = (exit_price - self.entry_price) * self.volume * 100000
        else:
            self.pnl = (self.entry_price - exit_price) * self.volume * 100000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "decision_id": self.decision_id,
            "evidence_id": self.evidence_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "entry_timestamp": self.entry_timestamp,
            "exit_price": self.exit_price,
            "exit_timestamp": self.exit_timestamp,
            "origin": self.origin.value,
            "status": self.status.value,
            "pnl": self.pnl,
            "commission": self.commission,
            "swap": self.swap,
            "slippage_entry": self.slippage_entry,
            "slippage_exit": self.slippage_exit,
            "broker_ticket": self.broker_ticket,
        }


@dataclass
class CampaignBoundary:
    """Clean campaign boundary with trade attribution."""

    campaign_id: str
    strategy_fingerprint: str
    start_timestamp: str
    r4_trades: List[TradeRecord] = field(default_factory=list)
    pre_existing_trades: List[TradeRecord] = field(default_factory=list)
    manual_trades: List[TradeRecord] = field(default_factory=list)

    def classify_position(
        self,
        broker_ticket: int,
        symbol: str,
        volume: float,
        entry_price: float,
        entry_time: str,
    ) -> TradeOrigin:
        """Classify a broker position as R4, pre-existing, or manual."""
        # Check if we have an R4 trade with this ticket
        for trade in self.r4_trades:
            if trade.broker_ticket == broker_ticket:
                return TradeOrigin.R4_CAMPAIGN

        # If position existed before campaign start, it's pre-existing
        if entry_time < self.start_timestamp:
            return TradeOrigin.PRE_EXISTING

        # Otherwise, classify as manual (shouldn't happen in automated campaign)
        return TradeOrigin.MANUAL

    def record_r4_trade(self, trade: TradeRecord) -> None:
        """Record an R4-originated trade."""
        trade.origin = TradeOrigin.R4_CAMPAIGN
        self.r4_trades.append(trade)

    def record_pre_existing(self, trade: TradeRecord) -> None:
        """Record a pre-existing position."""
        trade.origin = TradeOrigin.PRE_EXISTING
        self.pre_existing_trades.append(trade)

    def get_r4_positions(self) -> List[TradeRecord]:
        """Get all open R4-originated positions."""
        return [t for t in self.r4_trades if t.status == TradeStatus.OPEN]

    def get_pre_existing_positions(self) -> List[TradeRecord]:
        """Get all open pre-existing positions."""
        return [t for t in self.pre_existing_trades if t.status == TradeStatus.OPEN]

    def get_attribution(self) -> Dict[str, Any]:
        """Get P&L attribution by trade origin."""
        r4_pnl = sum(t.pnl for t in self.r4_trades)
        pre_pnl = sum(t.pnl for t in self.pre_existing_trades)
        manual_pnl = sum(t.pnl for t in self.manual_trades)

        r4_trades_count = len(self.r4_trades)
        pre_trades_count = len(self.pre_existing_trades)
        manual_trades_count = len(self.manual_trades)

        r4_open = len(self.get_r4_positions())
        pre_open = len(self.get_pre_existing_positions())

        return {
            "r4_pnl": r4_pnl,
            "pre_existing_pnl": pre_pnl,
            "manual_pnl": manual_pnl,
            "total_pnl": r4_pnl + pre_pnl + manual_pnl,
            "r4_trades": r4_trades_count,
            "pre_existing_trades": pre_trades_count,
            "manual_trades": manual_trades_count,
            "r4_open_positions": r4_open,
            "pre_existing_open_positions": pre_open,
        }

    def reconcile_with_broker(
        self,
        broker_positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Reconcile campaign boundary with actual broker state."""
        discrepancies = []
        classified = []

        for pos in broker_positions:
            origin = self.classify_position(
                broker_ticket=pos.get("ticket", 0),
                symbol=pos.get("symbol", ""),
                volume=pos.get("volume", 0),
                entry_price=pos.get("price_open", 0),
                entry_time=pos.get("time", ""),
            )
            classified.append(
                {
                    "symbol": pos.get("symbol"),
                    "origin": origin.value,
                    "volume": pos.get("volume"),
                    "pnl": pos.get("profit", 0),
                }
            )

            # Check if R4 position matches
            if origin == TradeOrigin.R4_CAMPAIGN:
                r4_trade = None
                for t in self.r4_trades:
                    if t.broker_ticket == pos.get("ticket"):
                        r4_trade = t
                        break

                if r4_trade:
                    if abs(r4_trade.volume - pos.get("volume", 0)) > 1e-6:
                        discrepancies.append(
                            f"{pos.get('symbol')}: volume mismatch (R4={r4_trade.volume}, broker={pos.get('volume')})"
                        )

        return {
            "classified_positions": classified,
            "discrepancies": discrepancies,
            "all_classified": len(discrepancies) == 0,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "start_timestamp": self.start_timestamp,
            "r4_trades": len(self.r4_trades),
            "pre_existing_trades": len(self.pre_existing_trades),
            "manual_trades": len(self.manual_trades),
            "attribution": self.get_attribution(),
        }
