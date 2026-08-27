"""Forward Paper Campaign.

Runs the frozen R4 configuration against live MT5 market data in paper mode.
Tests operational fidelity: missing bars, stale data, spread changes, timing,
session boundaries, instrument availability, position state, order lifecycle,
reconciliation, and operational failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
)
from eigencapital.fidelity.r4_manifest import R4ConfigManifest


class ForwardStatus(str, Enum):
    """Forward campaign status."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class OperationalEvent(str, Enum):
    """Operational events detected during forward campaign."""

    NORMAL = "normal"
    MISSING_BAR = "missing_bar"
    STALE_DATA = "stale_data"
    SPREAD_WIDENING = "spread_widening"
    SESSION_BOUNDARY = "session_boundary"
    INSTRUMENT_UNAVAILABLE = "instrument_unavailable"
    MARKET_CLOSED = "market_closed"
    DATA_GAP = "data_gap"
    RECONCILIATION_CHECK = "reconciliation_check"
    KILL_SWITCH_TEST = "kill_switch_test"


@dataclass(frozen=True)
class ForwardTick:
    """A single tick/bar in the forward campaign."""

    tick_id: str
    timestamp: str
    instrument_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float
    is_stale: bool = False
    is_missing: bool = False
    operational_event: OperationalEvent = OperationalEvent.NORMAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "spread": self.spread,
            "is_stale": self.is_stale,
            "is_missing": self.is_missing,
            "operational_event": self.operational_event.value,
        }


@dataclass(frozen=True)
class ForwardDecision:
    """A decision made during the forward campaign."""

    decision_id: str
    timestamp: str
    instrument_id: str
    signal: float
    weight: float
    position: float
    order_intent: str  # "BUY", "SELL", "HOLD"
    risk_approved: bool
    execution_price: float
    spread_at_decision: float
    operational_event: OperationalEvent = OperationalEvent.NORMAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "signal": self.signal,
            "weight": self.weight,
            "position": self.position,
            "order_intent": self.order_intent,
            "risk_approved": self.risk_approved,
            "execution_price": self.execution_price,
            "spread_at_decision": self.spread_at_decision,
            "operational_event": self.operational_event.value,
        }


@dataclass(frozen=True)
class ForwardResult:
    """Complete result of a forward paper campaign."""

    campaign_id: str
    manifest_identity: str
    total_ticks: int
    total_decisions: int
    operational_events: Dict[str, int]
    missing_bars: int
    stale_data_events: int
    spread_widening_events: int
    reconciliation_checks: int
    status: str
    decisions: List[ForwardDecision] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "manifest_identity": self.manifest_identity,
            "total_ticks": self.total_ticks,
            "total_decisions": self.total_decisions,
            "operational_events": self.operational_events,
            "missing_bars": self.missing_bars,
            "stale_data_events": self.stale_data_events,
            "spread_widening_events": self.spread_widening_events,
            "reconciliation_checks": self.reconciliation_checks,
            "status": self.status,
        }


class ForwardPaperCampaign:
    """Forward paper campaign against live MT5 data.

    Tests operational fidelity by running the frozen R4 configuration
    against real market data, detecting operational events, and verifying
    that the system behaves correctly under real-world conditions.
    """

    # Pre-registered operational thresholds
    MAX_SPREAD_RATIO: float = 3.0  # spread > 3x normal = widening event
    MAX_STALE_AGE_SECONDS: int = 60  # data older than 60s = stale
    RECONCILIATION_INTERVAL: int = 100  # check every 100 ticks

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest
        self._campaign_id = f"FWD-{manifest.compute_identity()[:12]}"
        self._parity = ResearchPaperParityEngine(self._campaign_id)
        self._ticks: List[ForwardTick] = []
        self._decisions: List[ForwardDecision] = []
        self._status = ForwardStatus.CREATED
        self._tick_counter = 0
        self._decision_counter = 0
        self._operational_events: Dict[str, int] = {}
        self._reconciliation_count = 0

    def ingest_tick(self, tick_data: Dict[str, Any]) -> ForwardTick:
        """Ingest a market tick/bar and detect operational events."""
        self._tick_counter += 1
        self._status = ForwardStatus.RUNNING

        event = OperationalEvent.NORMAL

        # Detect missing bar
        if tick_data.get("is_missing", False):
            event = OperationalEvent.MISSING_BAR
            self._operational_events["missing_bar"] = self._operational_events.get("missing_bar", 0) + 1

        # Detect stale data
        if tick_data.get("is_stale", False):
            event = OperationalEvent.STALE_DATA
            self._operational_events["stale_data"] = self._operational_events.get("stale_data", 0) + 1

        # Detect spread widening
        spread = tick_data.get("spread", 0.0)
        avg_spread = tick_data.get("avg_spread", spread)
        if avg_spread > 0 and spread > avg_spread * self.MAX_SPREAD_RATIO:
            event = OperationalEvent.SPREAD_WIDENING
            self._operational_events["spread_widening"] = self._operational_events.get("spread_widening", 0) + 1

        # Detect session boundary
        if tick_data.get("is_session_boundary", False):
            event = OperationalEvent.SESSION_BOUNDARY
            self._operational_events["session_boundary"] = self._operational_events.get("session_boundary", 0) + 1

        # Detect instrument unavailable
        if tick_data.get("is_unavailable", False):
            event = OperationalEvent.INSTRUMENT_UNAVAILABLE
            self._operational_events["instrument_unavailable"] = (
                self._operational_events.get("instrument_unavailable", 0) + 1
            )

        # Periodic reconciliation
        if self._tick_counter % self.RECONCILIATION_INTERVAL == 0:
            self._reconciliation_count += 1
            self._operational_events["reconciliation_check"] = (
                self._operational_events.get("reconciliation_check", 0) + 1
            )

        tick = ForwardTick(
            tick_id=f"TICK-{self._tick_counter:06d}",
            timestamp=tick_data.get("timestamp", ""),
            instrument_id=tick_data.get("instrument_id", ""),
            open=tick_data.get("open", 0.0),
            high=tick_data.get("high", 0.0),
            low=tick_data.get("low", 0.0),
            close=tick_data.get("close", 0.0),
            volume=tick_data.get("volume", 0.0),
            spread=spread,
            is_stale=tick_data.get("is_stale", False),
            is_missing=tick_data.get("is_missing", False),
            operational_event=event,
        )
        self._ticks.append(tick)
        return tick

    def make_decision(
        self,
        timestamp: str,
        instrument_id: str,
        signal: float,
        weight: float,
        position: float,
        order_intent: str,
        risk_approved: bool,
        execution_price: float,
        spread_at_decision: float,
        operational_event: OperationalEvent = OperationalEvent.NORMAL,
    ) -> ForwardDecision:
        """Record a paper decision."""
        self._decision_counter += 1

        decision = ForwardDecision(
            decision_id=f"FDEC-{self._decision_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument_id,
            signal=signal,
            weight=weight,
            position=position,
            order_intent=order_intent,
            risk_approved=risk_approved,
            execution_price=execution_price,
            spread_at_decision=spread_at_decision,
            operational_event=operational_event,
        )
        self._decisions.append(decision)
        return decision

    def get_result(self) -> ForwardResult:
        """Compute forward campaign result."""
        event_counts = dict(self._operational_events)
        missing = event_counts.get("missing_bar", 0)
        stale = event_counts.get("stale_data", 0)
        spread_wide = event_counts.get("spread_widening", 0)

        status = "PASS"
        if missing > 0 or stale > 0:
            status = "WARNING"
        if spread_wide > 10:
            status = "CRITICAL"

        return ForwardResult(
            campaign_id=self._campaign_id,
            manifest_identity=self._manifest.compute_identity(),
            total_ticks=len(self._ticks),
            total_decisions=len(self._decisions),
            operational_events=event_counts,
            missing_bars=missing,
            stale_data_events=stale,
            spread_widening_events=spread_wide,
            reconciliation_checks=self._reconciliation_count,
            status=status,
            decisions=list(self._decisions),
        )

    @property
    def status(self) -> ForwardStatus:
        return self._status

    @property
    def parity_engine(self) -> ResearchPaperParityEngine:
        return self._parity
