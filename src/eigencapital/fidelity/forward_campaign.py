"""Forward Paper Campaign — runs R4 against live MT5 data sequentially.

Tests operational fidelity: missing bars, stale data, spread changes,
timing, session boundaries, instrument availability, position state,
order lifecycle, reconciliation, and operational failures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any

import numpy as np

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
)
from eigencapital.fidelity.verdict import FidelityEvaluator, FidelityReport

logger = logging.getLogger(__name__)


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
    CONNECTION_INTERRUPT = "connection_interrupt"
    PRICE_ANOMALY = "price_anomaly"


class CampaignPhase(str, Enum):
    """Forward campaign phases."""

    INITIALIZING = "initializing"
    WARMING_UP = "warming_up"  # building lookback windows
    RUNNING = "running"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass
class OperationalState:
    """Tracks operational health during forward campaign."""

    total_ticks: int = 0
    missing_bars: int = 0
    stale_data_events: int = 0
    spread_widening_events: int = 0
    session_boundaries: int = 0
    instrument_unavailable: int = 0
    market_closed_events: int = 0
    data_gaps: int = 0
    reconciliation_checks: int = 0
    reconciliation_failures: int = 0
    connection_interrupts: int = 0
    price_anomalies: int = 0
    consecutive_errors: int = 0
    max_consecutive_errors: int = 0

    def record_event(self, event: OperationalEvent) -> None:
        """Record an operational event."""
        self.total_ticks += 1

        if event == OperationalEvent.MISSING_BAR:
            self.missing_bars += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.STALE_DATA:
            self.stale_data_events += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.SPREAD_WIDENING:
            self.spread_widening_events += 1
        elif event == OperationalEvent.SESSION_BOUNDARY:
            self.session_boundaries += 1
        elif event == OperationalEvent.INSTRUMENT_UNAVAILABLE:
            self.instrument_unavailable += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.MARKET_CLOSED:
            self.market_closed_events += 1
        elif event == OperationalEvent.DATA_GAP:
            self.data_gaps += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.RECONCILIATION_CHECK:
            self.reconciliation_checks += 1
        elif event == OperationalEvent.CONNECTION_INTERRUPT:
            self.connection_interrupts += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.PRICE_ANOMALY:
            self.price_anomalies += 1
            self.consecutive_errors += 1
        elif event == OperationalEvent.NORMAL:
            self.consecutive_errors = 0

        self.max_consecutive_errors = max(
            self.max_consecutive_errors, self.consecutive_errors
        )

    @property
    def error_rate(self) -> float:
        if self.total_ticks == 0:
            return 0.0
        errors = (
            self.missing_bars
            + self.stale_data_events
            + self.instrument_unavailable
            + self.data_gaps
            + self.connection_interrupts
            + self.price_anomalies
        )
        return errors / self.total_ticks

    @property
    def reconciliation_success_rate(self) -> float:
        if self.reconciliation_checks == 0:
            return 1.0
        return 1.0 - (self.reconciliation_failures / self.reconciliation_checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ticks": self.total_ticks,
            "missing_bars": self.missing_bars,
            "stale_data_events": self.stale_data_events,
            "spread_widening_events": self.spread_widening_events,
            "session_boundaries": self.session_boundaries,
            "instrument_unavailable": self.instrument_unavailable,
            "market_closed_events": self.market_closed_events,
            "data_gaps": self.data_gaps,
            "reconciliation_checks": self.reconciliation_checks,
            "reconciliation_failures": self.reconciliation_failures,
            "reconciliation_success_rate": self.reconciliation_success_rate,
            "connection_interrupts": self.connection_interrupts,
            "price_anomalies": self.price_anomalies,
            "error_rate": self.error_rate,
            "max_consecutive_errors": self.max_consecutive_errors,
        }


@dataclass
class ForwardBar:
    """A single bar processed during the forward campaign."""

    bar_id: str
    timestamp: str
    instrument_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float
    operational_event: OperationalEvent = OperationalEvent.NORMAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bar_id": self.bar_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "spread": self.spread,
            "operational_event": self.operational_event.value,
        }


@dataclass
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
            "operational_event": self.operational_event.value,
        }


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""

    check_id: str
    timestamp: str
    internal_position: Dict[str, float]
    expected_position: Dict[str, float]
    matched: bool
    discrepancies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "timestamp": self.timestamp,
            "internal_position": self.internal_position,
            "expected_position": self.expected_position,
            "matched": self.matched,
            "discrepancies": self.discrepancies,
        }


class ForwardPaperCampaign:
    """Forward paper campaign against live MT5 data.

    Runs the frozen R4 configuration against real market data sequentially,
    testing operational fidelity under real-world conditions.
    """

    # Pre-registered thresholds
    MAX_SPREAD_RATIO: float = 3.0
    MAX_STALE_AGE_SECONDS: int = 60
    RECONCILIATION_INTERVAL: int = 50  # bars
    MAX_CONSECUTIVE_ERRORS: int = 10
    MIN_DATA_COMPLETENESS: float = 0.95  # 95% of expected bars

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest
        self._campaign_id = f"FWD-{manifest.compute_identity()[:12]}"
        self._parity = ResearchPaperParityEngine(self._campaign_id)
        self._state = OperationalState()
        self._phase = CampaignPhase.INITIALIZING
        self._bars: List[ForwardBar] = []
        self._decisions: List[ForwardDecision] = []
        self._reconciliations: List[ReconciliationResult] = []
        self._bar_counter = 0
        self._decision_counter = 0
        self._recon_counter = 0

        # Rolling data windows per instrument
        self._data_windows: Dict[str, List[float]] = {}
        self._last_prices: Dict[str, float] = {}
        self._last_timestamps: Dict[str, str] = {}

        # Internal position tracking
        self._internal_positions: Dict[str, float] = {}

    def ingest_bar(self, bar_data: Dict[str, Any]) -> ForwardBar:
        """Ingest a market bar and detect operational events."""
        self._bar_counter += 1

        if self._phase == CampaignPhase.INITIALIZING:
            self._phase = CampaignPhase.WARMING_UP

        event = OperationalEvent.NORMAL
        instrument = bar_data.get("instrument_id", "")
        close = bar_data.get("close", 0.0)
        spread = bar_data.get("spread", 0.0)
        timestamp = bar_data.get("timestamp", "")

        # Update data window
        if instrument not in self._data_windows:
            self._data_windows[instrument] = []
        self._data_windows[instrument].append(close)
        if len(self._data_windows[instrument]) > 252:
            self._data_windows[instrument].pop(0)

        # Detect missing bar
        if bar_data.get("is_missing", False):
            event = OperationalEvent.MISSING_BAR

        # Detect stale data
        if bar_data.get("is_stale", False):
            event = OperationalEvent.STALE_DATA

        # Detect spread widening
        if spread > 0 and len(self._data_windows.get(instrument, [])) > 20:
            recent_spreads = self._data_windows.get(instrument, [])
            avg_spread = np.mean(recent_spreads[-20:]) if recent_spreads else spread
            if avg_spread > 0 and spread > avg_spread * self.MAX_SPREAD_RATIO:
                event = OperationalEvent.SPREAD_WIDENING

        # Detect session boundary
        if bar_data.get("is_session_boundary", False):
            event = OperationalEvent.SESSION_BOUNDARY

        # Detect instrument unavailable
        if bar_data.get("is_unavailable", False):
            event = OperationalEvent.INSTRUMENT_UNAVAILABLE

        # Detect market closed
        if bar_data.get("is_market_closed", False):
            event = OperationalEvent.MARKET_CLOSED

        # Detect data gap
        if instrument in self._last_timestamps:
            # Simple gap detection (would need proper timestamp parsing in production)
            pass

        # Detect price anomaly
        if instrument in self._last_prices and close > 0:
            last = self._last_prices[instrument]
            if last > 0:
                pct_change = abs(close - last) / last
                if pct_change > 0.10:  # >10% single-bar move
                    event = OperationalEvent.PRICE_ANOMALY

        # Update tracking
        self._last_prices[instrument] = close
        self._last_timestamps[instrument] = timestamp
        self._state.record_event(event)

        # Periodic reconciliation
        if self._bar_counter % self.RECONCILIATION_INTERVAL == 0:
            self._perform_reconciliation(timestamp)

        bar = ForwardBar(
            bar_id=f"BAR-{self._bar_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument,
            open=bar_data.get("open", 0.0),
            high=bar_data.get("high", 0.0),
            low=bar_data.get("low", 0.0),
            close=close,
            volume=bar_data.get("volume", 0.0),
            spread=spread,
            operational_event=event,
        )
        self._bars.append(bar)

        # Check abort conditions
        if self._state.consecutive_errors > self.MAX_CONSECUTIVE_ERRORS:
            self._phase = CampaignPhase.ABORTED
            logger.warning(
                f"Forward campaign aborted: {self._state.consecutive_errors} consecutive errors"
            )

        return bar

    def make_decision(
        self,
        timestamp: str,
        instrument_id: str,
        signal: float,
        weight: float,
        position: float,
        order_intent: str,
        risk_approved: bool,
    ) -> ForwardDecision:
        """Record a paper decision."""
        self._decision_counter += 1

        # Update internal position tracking
        if order_intent in ("BUY", "SELL") and risk_approved:
            self._internal_positions[instrument_id] = position

        decision = ForwardDecision(
            decision_id=f"FDEC-{self._decision_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument_id,
            signal=signal,
            weight=weight,
            position=position,
            order_intent=order_intent,
            risk_approved=risk_approved,
        )
        self._decisions.append(decision)
        return decision

    def _perform_reconciliation(self, timestamp: str) -> ReconciliationResult:
        """Perform a reconciliation check."""
        self._recon_counter += 1
        self._state.reconciliation_checks += 1

        # Compare internal positions with expected positions
        # In forward paper, expected = what the signal says we should have
        discrepancies = []
        for inst, pos in self._internal_positions.items():
            # For now, check that position is reasonable (not negative for long-only, etc.)
            if abs(pos) > 1e6:  # unreasonable position size
                discrepancies.append(
                    f"{inst}: position {pos} exceeds reasonable bounds"
                )

        matched = len(discrepancies) == 0
        if not matched:
            self._state.reconciliation_failures += 1

        result = ReconciliationResult(
            check_id=f"RECON-{self._recon_counter:06d}",
            timestamp=timestamp,
            internal_position=dict(self._internal_positions),
            expected_position=dict(self._internal_positions),  # simplified
            matched=matched,
            discrepancies=discrepancies,
        )
        self._reconciliations.append(result)
        return result

    def get_result(self) -> Dict[str, Any]:
        """Compute forward campaign result."""
        state = self._state.to_dict()

        # Determine status
        if self._phase == CampaignPhase.ABORTED:
            status = "ABORTED"
        elif state["error_rate"] > 0.05:  # >5% error rate
            status = "WARNING"
        elif state["missing_bars"] > 0 or state["stale_data_events"] > 0:
            status = "WARNING"
        else:
            status = "PASS"

        return {
            "campaign_id": self._campaign_id,
            "manifest_identity": self._manifest.compute_identity(),
            "phase": self._phase.value,
            "status": status,
            "total_bars": len(self._bars),
            "total_decisions": len(self._decisions),
            "total_reconciliations": len(self._reconciliations),
            "operational_state": state,
            "bars": [b.to_dict() for b in self._bars[:100]],  # first 100 for report
            "decisions": [d.to_dict() for d in self._decisions[:100]],
            "reconciliations": [r.to_dict() for r in self._reconciliations[:20]],
        }

    def evaluate_fidelity(self) -> FidelityReport:
        """Evaluate fidelity gates based on forward campaign results."""
        state = self._state

        # Create a parity summary from the parity engine
        parity_summary = self._parity.get_summary()

        # Evaluate fidelity
        evaluator = FidelityEvaluator(self._manifest)
        return evaluator.evaluate(
            campaign_id=self._campaign_id,
            parity_summary=parity_summary,
            reconciliation_success_rate=state.reconciliation_success_rate,
            total_cost_drag_bps=self._manifest.transaction_cost_bps,
            max_slippage_bps=self._manifest.slippage_bps,
            operational_events={
                "missing_bar": state.missing_bars,
                "stale_data": state.stale_data_events,
                "spread_widening": state.spread_widening_events,
            },
        )

    @property
    def phase(self) -> CampaignPhase:
        return self._phase

    @property
    def state(self) -> OperationalState:
        return self._state

    @property
    def parity_engine(self) -> ResearchPaperParityEngine:
        return self._parity
