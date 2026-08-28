"""Evidence Orchestrator — central hub for Phase 2 evidence collection.

Wires together:
- R4LiveQualificationDataset (per-trade evidence)
- EvidenceMaturityTracker (E0-E6 levels)
- Phase2ReportGenerator (qualification reports)
- Event ledger correlation

Designed to be called from the live rebalance loop:
1. After each cycle: capture position snapshot
2. On trade closure: record exit details
3. Periodically: generate Phase 2 report
4. Track evidence maturity level

Usage:
    orchestrator = EvidenceOrchestrator(campaign_id="R4-5K-20260827")

    # After each rebalance cycle
    orchestrator.capture_cycle_snapshot(mt5, account, positions, equity)

    # When a trade closes
    orchestrator.record_trade_closure(
        ticket=3140147169,
        symbol="BTCUSD",
        exit_price=78500.0,
        exit_reason="ROTATION",
        realized_pnl=-4.98,
    )

    # Generate qualification report (daily or on-demand)
    report = orchestrator.generate_report()

    # Check evidence maturity
    maturity = orchestrator.assess_maturity()
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

from eigencapital.production_qual.evidence_maturity import (
    EvidenceMaturityTracker,
    EvidenceState,
)
from eigencapital.production_qual.live_qualification import (
    ExecutionFidelity,
    OperationalEvent,
    PortfolioRiskSnapshot,
    QualificationTrade,
    R4LiveQualificationDataset,
)
from eigencapital.production_qual.phase2_report import Phase2Report, Phase2ReportGenerator


class EvidenceOrchestrator:
    """Central hub for Phase 2 evidence collection.

    Integrates all evidence collection into a single interface
    for the live rebalance loop.
    """

    def __init__(
        self,
        campaign_id: str,
        evidence_dir: str = "reports/r4_qualification/evidence",
        reports_dir: str = "reports/r4_qualification",
        snapshot_interval_seconds: float = 3600.0,
        report_interval_hours: float = 24.0,
    ) -> None:
        """Initialize the evidence orchestrator.

        Args:
            campaign_id: Campaign identifier (e.g., "R4-5K-20260827")
            evidence_dir: Directory for evidence JSONL files
            reports_dir: Directory for qualification reports
            snapshot_interval_seconds: Minimum time between snapshots
            report_interval_hours: Minimum time between report generation
        """
        self._campaign_id = campaign_id
        self._evidence_dir = Path(evidence_dir)
        self._reports_dir = Path(reports_dir)
        self._snapshot_interval = snapshot_interval_seconds
        self._report_interval_hours = report_interval_hours

        # Ensure directories exist
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Core components
        self._dataset = R4LiveQualificationDataset(campaign_id=campaign_id)
        self._maturity_tracker = EvidenceMaturityTracker()
        self._report_generator = Phase2ReportGenerator(self._dataset)

        # State tracking
        self._last_snapshot_time: float = 0.0
        self._last_report_time: float = 0.0
        self._last_positions: Dict[int, Dict[str, Any]] = {}  # ticket -> position info
        self._position_entry_prices: Dict[int, float] = {}  # ticket -> entry price
        self._position_entry_times: Dict[int, str] = {}  # ticket -> entry timestamp
        self._cycle_counter: int = 0  # P2-017: explicit cycle counter for correlation
        self._consecutive_snapshot_failures: int = 0  # P1-008: escalation counter
        self._escalation_threshold: int = 3  # P1-008: escalate after N failures

        # Evidence files
        self._snapshot_file = self._evidence_dir / "position_snapshots.jsonl"
        self._closure_file = self._evidence_dir / "trade_closures.jsonl"
        self._maturity_file = self._evidence_dir / "evidence_maturity.json"
        self._report_file = self._reports_dir / "phase2_report_latest.json"

    def capture_cycle_snapshot(
        self,
        positions: List[Dict[str, Any]],
        account_equity: float,
        account_balance: float,
        free_margin: float,
        force: bool = False,
    ) -> Dict[str, Any] | None:
        """Capture a position snapshot for evidence collection.

        Called after each rebalance cycle. Respects snapshot interval
        unless force=True.

        Args:
            positions: Current broker positions (from mt5.positions_get())
            account_equity: Current account equity
            account_balance: Current account balance
            free_margin: Current free margin
            force: Force snapshot even if interval hasn't elapsed

        Returns:
            Snapshot data if captured, None if skipped
        """
        now = time.time()

        # Rate limiting
        if not force and (now - self._last_snapshot_time) < self._snapshot_interval:
            return None

        self._last_snapshot_time = now

        # Detect new positions (entries)
        current_tickets = {p.get("ticket") for p in positions}
        new_tickets = current_tickets - set(self._last_positions.keys())

        for ticket in new_tickets:
            pos = next((p for p in positions if p.get("ticket") == ticket), None)
            if pos:
                self._record_entry(pos)

        # Detect closed positions
        closed_tickets = set(self._last_positions.keys()) - current_tickets
        for ticket in closed_tickets:
            old_pos = self._last_positions.get(ticket)
            if old_pos:
                self._record_closure_from_snapshot(old_pos, account_equity)

        # Build portfolio risk snapshot
        risk_snapshot = self._build_risk_snapshot(positions, account_equity, account_balance, free_margin)
        self._dataset.record_risk_snapshot(risk_snapshot)

        # Update position tracking
        self._last_positions = {int(p.get("ticket", 0)): p for p in positions if p.get("ticket") is not None}

        # P2-017: Increment cycle counter for explicit correlation
        self._cycle_counter += 1

        # Save snapshot with explicit correlation IDs
        snapshot = {
            "timestamp": datetime.now(UTC).isoformat(),
            "campaign_id": self._campaign_id,
            "cycle_counter": self._cycle_counter,
            "correlation_id": f"{self._campaign_id}-c{self._cycle_counter}",
            "equity": account_equity,
            "balance": account_balance,
            "free_margin": free_margin,
            "position_count": len(positions),
            "r4_count": sum(1 for p in positions if p.get("magic") == 20260825),
            "foreign_count": sum(1 for p in positions if p.get("magic") != 20260825),
            "tickets": list(current_tickets),
        }

        self._append_jsonl(self._snapshot_file, snapshot)

        return snapshot

    def record_trade_closure(
        self,
        ticket: int,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        realized_pnl: float,
        commission: float = 0.0,
        swap: float = 0.0,
    ) -> QualificationTrade | None:
        """Record a trade closure with full lifecycle data.

        Args:
            ticket: Position ticket number
            symbol: Instrument symbol
            exit_price: Exit price
            exit_reason: Reason for exit (ROTATION, SIGN_FLIP, REGIME, CATASTROPHIC_SL, etc.)
            realized_pnl: Gross realized P&L
            commission: Commission paid
            swap: Swap/financing costs

        Returns:
            Updated trade record if found, None if ticket not tracked
        """
        # Find the trade in our dataset
        trade_id = self._find_trade_by_ticket(ticket)
        if not trade_id:
            return None

        trade = self._dataset.get_trade(trade_id)
        if not trade:
            return None

        # Compute total costs
        entry_price = self._position_entry_prices.get(ticket, 0)
        slippage = abs(exit_price - entry_price) if entry_price > 0 else 0
        total_costs = commission + swap + slippage

        # Update the trade record
        updated = self._dataset.record_exit(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            realized_pnl=realized_pnl,
            net_pnl=realized_pnl - total_costs,
            total_costs=total_costs,
        )

        if updated:
            # Record closure event
            closure_event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "trade_id": trade_id,
                "ticket": ticket,
                "symbol": symbol,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "realized_pnl": realized_pnl,
                "commission": commission,
                "swap": swap,
                "slippage": slippage,
                "total_costs": total_costs,
                "holding_days": updated.holding_period.holding_period_days if updated.holding_period else 0,
            }
            self._append_jsonl(self._closure_file, closure_event)

            # Clean up tracking
            self._position_entry_prices.pop(ticket, None)
            self._position_entry_times.pop(ticket, None)

        return updated

    def record_operational_event(
        self,
        event_type: str,
        detection_time_ms: float,
        containment_time_ms: float | None = None,
        recovery_time_ms: float | None = None,
        success: bool = True,
        details: Dict[str, Any] | None = None,
    ) -> None:
        """Record an operational event (disconnect, restart, etc.).

        Args:
            event_type: Type of event (disconnect, reconnect, restart, etc.)
            detection_time_ms: Time to detect the event
            containment_time_ms: Time to contain the event
            recovery_time_ms: Time to recover
            success: Whether recovery was successful
            details: Additional event details
        """
        event = OperationalEvent(
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            detection_time_ms=detection_time_ms,
            containment_time_ms=containment_time_ms,
            recovery_time_ms=recovery_time_ms,
            success=success,
            details=details or {},
        )
        self._dataset.record_operational_event(event)

    def assess_maturity(self) -> EvidenceState:
        """Assess current evidence maturity level.

        Returns:
            Current evidence state with level and requirements
        """
        # Compute current metrics
        all_trades = self._dataset.get_all_trades()
        closed_trades = self._dataset.get_closed_trades()

        # Count operational days (from first trade)
        operational_days = 0.0
        if all_trades:
            first_entry = min(t.entry_timestamp for t in all_trades)
            first_dt = datetime.fromisoformat(first_entry.replace("Z", "+00:00"))
            now_dt = datetime.now(UTC)
            operational_days = (now_dt - first_dt).total_seconds() / 86400

        # Count independent episodes (distinct portfolio rebalancing events)
        # For now, count unique entry dates as episodes
        entry_dates = set()
        for t in all_trades:
            entry_date = t.entry_timestamp[:10]  # YYYY-MM-DD
            entry_dates.add(entry_date)
        independent_episodes = len(entry_dates)

        # Max holding period
        max_holding = 0.0
        for t in closed_trades:
            if t.holding_period:
                max_holding = max(max_holding, t.holding_period.holding_period_days)

        # Assess maturity
        state = self._maturity_tracker.assess(
            operational_days=operational_days,
            completed_trades=len(closed_trades),
            independent_episodes=independent_episodes,
            max_holding_period_days=max_holding,
        )

        # Persist maturity state
        self._save_maturity(state)

        return state

    def generate_report(self, force: bool = False) -> Phase2Report | None:
        """Generate Phase 2 qualification report.

        Args:
            force: Force report generation even if interval hasn't elapsed

        Returns:
            Phase2Report if generated, None if skipped
        """
        now = time.time()

        # Rate limiting
        if not force and (now - self._last_report_time) < (self._report_interval_hours * 3600):
            return None

        self._last_report_time = now

        # Generate report
        report = self._report_generator.generate()

        # Save report
        report_data = report.to_dict()
        with open(self._report_file, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        # Also save timestamped version
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        ts_file = self._reports_dir / f"phase2_report_{ts}.json"
        with open(ts_file, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        # Generate markdown report
        md_file = self._reports_dir / f"phase2_report_{ts}.md"
        with open(md_file, "w") as f:
            f.write(report.to_markdown())

        return report

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics.

        Returns:
            Dictionary of statistics
        """
        maturity = self.assess_maturity()
        economics = self._dataset.compute_economics()

        return {
            "campaign_id": self._campaign_id,
            "maturity_level": maturity.level,
            "maturity_assessment": maturity.assessment,
            "next_requirements": maturity.next_level_requirements,
            "total_trades": economics.get("total_trades", 0),
            "winning_trades": economics.get("winning_trades", 0),
            "losing_trades": economics.get("losing_trades", 0),
            "win_rate": economics.get("win_rate", 0),
            "expectancy": economics.get("expectancy_per_trade", 0),
            "profit_factor": economics.get("profit_factor", 0),
            "open_positions": len(self._dataset.get_open_trades()),
            "risk_snapshots": len(self._dataset._risk_snapshots),
            "operational_events": len(self._dataset._operational_events),
        }

    # ── Private helpers ──────────────────────────────────────────────

    def _record_entry(self, position: Dict[str, Any]) -> None:
        """Record a new position entry."""
        ticket = int(position.get("ticket", 0))
        symbol = position.get("symbol", "")
        magic = position.get("magic", 0)

        # Only track R4 positions
        if magic != 20260825:
            return

        # Determine side
        pos_type = position.get("type", 0)
        side = "BUY" if pos_type == 0 else "SELL"
        volume = position.get("volume", 0.0)
        entry_price = position.get("price_open", 0.0)

        # Store entry data
        self._position_entry_prices[ticket] = entry_price
        self._position_entry_times[ticket] = datetime.now(UTC).isoformat()

        # Create execution fidelity record
        execution = ExecutionFidelity(
            signal_timestamp=datetime.now(UTC).isoformat(),
            intended_symbol=symbol,
            intended_direction=1.0 if side == "BUY" else -1.0,
            intended_weight=0.0,  # Will be computed from signal
            requested_price=entry_price,
            fill_price=entry_price,
            spread=0.0,  # Would need tick data at entry time
            slippage=0.0,  # Would need signal price vs fill price
            execution_latency_ms=0.0,  # Would need signal timestamp
            rejection_status="FILLED",
            partial_fill_qty=volume,
            swap_daily=0.0,
            commission=0.0,
        )

        # Record in dataset
        trade = self._dataset.record_entry(
            symbol=symbol,
            side=side,
            volume=volume,
            execution=execution,
            correlation_id=f"ticket-{ticket}",
        )

        # Store ticket -> trade_id mapping
        if trade:
            self._store_ticket_mapping(ticket, trade.trade_id)

    def _record_closure_from_snapshot(self, old_position: Dict[str, Any], current_equity: float) -> None:
        """Record a closure detected from position snapshot difference."""
        ticket = int(old_position.get("ticket", 0))
        entry_price = old_position.get("price_open", 0)

        # Find the trade
        trade_id = self._find_trade_by_ticket(ticket)
        if not trade_id:
            return

        # Estimate exit price from entry and current P&L
        # This is approximate — real closure tracking needs deal history
        profit = old_position.get("profit", 0)

        # For now, mark as closed with estimated data
        # The real closure should be recorded via record_trade_closure()
        self._dataset.record_exit(
            trade_id=trade_id,
            exit_price=entry_price,  # Placeholder
            exit_reason="UNKNOWN",
            realized_pnl=profit,
            net_pnl=profit,
            total_costs=0.0,
        )

    def _build_risk_snapshot(
        self,
        positions: List[Dict[str, Any]],
        equity: float,
        balance: float,
        free_margin: float,
    ) -> PortfolioRiskSnapshot:
        """Build a portfolio risk snapshot from current positions."""
        # Compute exposure
        long_exposure = 0.0
        short_exposure = 0.0
        fx_exposure = 0.0
        commodity_exposure = 0.0
        index_exposure = 0.0

        for pos in positions:
            volume = pos.get("volume", 0)
            price = pos.get("price_open", 0)
            notional = volume * price * 100000  # Approximate

            if pos.get("type") == 0:  # BUY
                long_exposure += notional
            else:
                short_exposure += notional

            # Asset class exposure (simplified)
            symbol = pos.get("symbol", "")
            if "USD" in symbol or "EUR" in symbol or "GBP" in symbol:
                fx_exposure += notional
            elif "XAU" in symbol or "XAG" in symbol:
                commodity_exposure += notional
            elif "US30" in symbol or "SPX" in symbol:
                index_exposure += notional

        gross_exposure = long_exposure + short_exposure
        net_exposure = long_exposure - short_exposure

        # Compute drawdown
        drawdown_pct = 0.0
        if equity > 0 and balance > equity:
            drawdown_pct = (balance - equity) / balance

        return PortfolioRiskSnapshot(
            timestamp=datetime.now(UTC).isoformat(),
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            fx_exposure=fx_exposure,
            commodity_exposure=commodity_exposure,
            index_exposure=index_exposure,
            drawdown_pct=drawdown_pct,
            daily_loss=0.0,  # Would need daily start equity
            margin_utilization=(balance - free_margin) / balance if balance > 0 else 0,
            position_count=len(positions),
        )

    def _find_trade_by_ticket(self, ticket: int) -> str | None:
        """Find trade ID by position ticket."""
        # Search in dataset trades
        for trade in self._dataset.get_all_trades():
            if trade.correlation_id == f"ticket-{ticket}":
                return trade.trade_id
        return None

    def _store_ticket_mapping(self, ticket: int, trade_id: str) -> None:
        """Store ticket -> trade_id mapping."""
        mapping_file = self._evidence_dir / "ticket_mapping.json"
        mapping = {}
        if mapping_file.exists():
            try:
                with open(mapping_file) as f:
                    mapping = json.load(f)
            except (json.JSONDecodeError, OSError):
                mapping = {}

        mapping[str(ticket)] = trade_id

        with open(mapping_file, "w") as f:
            json.dump(mapping, f, indent=2)

    def _load_ticket_mapping(self) -> Dict[str, str]:
        """Load ticket -> trade_id mapping."""
        mapping_file = self._evidence_dir / "ticket_mapping.json"
        if mapping_file.exists():
            try:
                with open(mapping_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_maturity(self, state: EvidenceState) -> None:
        """Save evidence maturity state."""
        with open(self._maturity_file, "w") as f:
            json.dump(state.to_dict(), f, indent=2)

    def _append_jsonl(self, filepath: Path, record: Dict[str, Any]) -> None:
        """Append a record to a JSONL file."""
        with open(filepath, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def record_snapshot_success(self) -> None:
        """P1-008: Reset consecutive failure counter on success."""
        self._consecutive_snapshot_failures = 0

    def record_snapshot_failure(self) -> str:
        """P1-008: Track consecutive failures and escalate.

        Returns escalation level:
        - "NORMAL": < threshold, continue
        - "WARNING": threshold reached, log warning
        - "CRITICAL": 2x threshold, recommend halt
        """
        self._consecutive_snapshot_failures += 1
        if self._consecutive_snapshot_failures >= self._escalation_threshold * 2:
            return "CRITICAL"
        elif self._consecutive_snapshot_failures >= self._escalation_threshold:
            return "WARNING"
        return "NORMAL"


# ── Convenience function for live loop integration ────────────────

_orchestrator: EvidenceOrchestrator | None = None


def get_orchestrator(
    campaign_id: str = "R4-5K-20260827",
    force: bool = False,
) -> EvidenceOrchestrator:
    """Get or create the global evidence orchestrator.

    Args:
        campaign_id: Campaign identifier
        force: Force creation even if already exists

    Returns:
        EvidenceOrchestrator instance
    """
    global _orchestrator
    if _orchestrator is None or force:
        _orchestrator = EvidenceOrchestrator(campaign_id=campaign_id)
    return _orchestrator


def capture_evidence_snapshot(
    positions: List[Dict[str, Any]],
    equity: float,
    balance: float,
    free_margin: float,
    campaign_id: str = "R4-5K-20260827",
) -> Dict[str, Any] | None:
    """Capture an evidence snapshot (convenience function).

    Called from the live rebalance loop after each cycle.
    P1-008: Tracks consecutive failures and escalates.
    """
    orchestrator = get_orchestrator(campaign_id)
    try:
        result = orchestrator.capture_cycle_snapshot(
            positions=positions,
            account_equity=equity,
            account_balance=balance,
            free_margin=free_margin,
        )
        orchestrator.record_snapshot_success()
        return result
    except Exception:
        orchestrator.record_snapshot_failure()
        raise  # re-raise so caller can handle


def record_closure(
    ticket: int,
    symbol: str,
    exit_price: float,
    exit_reason: str,
    realized_pnl: float,
    campaign_id: str = "R4-5K-20260827",
) -> QualificationTrade | None:
    """Record a trade closure (convenience function).

    Called when a position is closed.
    """
    orchestrator = get_orchestrator(campaign_id)
    return orchestrator.record_trade_closure(
        ticket=ticket,
        symbol=symbol,
        exit_price=exit_price,
        exit_reason=exit_reason,
        realized_pnl=realized_pnl,
    )


def record_operational_event(
    event_type: str,
    detection_time_ms: float,
    recovery_time_ms: float | None = None,
    success: bool = True,
    campaign_id: str = "R4-5K-20260827",
) -> None:
    """Record an operational event (convenience function).

    Called on disconnect, reconnect, restart, etc.
    """
    orchestrator = get_orchestrator(campaign_id)
    orchestrator.record_operational_event(
        event_type=event_type,
        detection_time_ms=detection_time_ms,
        recovery_time_ms=recovery_time_ms,
        success=success,
    )
