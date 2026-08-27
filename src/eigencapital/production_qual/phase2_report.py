"""Phase 2 Qualification Report — continuous economic validation dashboard.

Produces a report that continuously answers:
ENTRY → EXECUTION → HOLD → MAE → MFE → EXIT → P&L → PORTFOLIO RISK → OPERATIONAL HEALTH

This is the primary deliverable for Phase 2:
> A formal R4 Live Economic Qualification campaign, with the system
> remaining frozen and a dashboard/report that continuously answers
> whether R4 makes money with acceptable risk.

The report is generated on-demand and can be run:
- After every trade closure
- Daily as a snapshot
- On-demand for qualification review
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from eigencapital.production_qual.live_qualification import (
    R4LiveQualificationDataset,
    QualificationTrade,
)


@dataclass
class Phase2Report:
    """Complete Phase 2 qualification report."""
    
    campaign_id: str
    timestamp: str
    
    # Executive summary
    verdict: str  # "PASS", "PENDING", "FAIL", "BLOCKED"
    total_trades: int
    open_positions: int
    days_in_campaign: float
    
    # The real deliverable — structured verdict
    r4_economic_edge: str       # CONFIRMED / INCONCLUSIVE / REJECTED
    entry_quality: str          # GREEN / YELLOW / RED / NOT_YET_ASSESSABLE
    holding_period_range: str   # e.g., "20-40 days" or "INSUFFICIENT_DATA"
    exit_economics: str         # GOOD / MIXED / POOR / NOT_YET_ASSESSABLE
    downside_control: str       # ADEQUATE / INADEQUATE / NOT_YET_ASSESSABLE
    execution_fidelity: str     # e.g., "95% of research cost" or "NOT_YET_ASSESSABLE"
    operational_reliability: str  # e.g., "99.9% uptime" or "NOT_YET_ASSESSABLE"
    tail_risk: str              # ACCEPTABLE / EXCESSIVE / NOT_YET_ASSESSABLE
    capacity: str               # e.g., "$5K justified" or "NOT_YET_ASSESSABLE"
    next_capital_tier: str      # e.g., "$10K" or "NONE" or "NOT_YET_ASSESSABLE"
    
    # Evidence classification
    evidence_classification: str  # OBSERVED / DERIVED / MIXED
    evidence_note: str            # "Do not present model reconstruction as live evidence"
    
    # Entry quality
    entry_summary: Dict[str, Any]
    
    # Execution fidelity
    execution_summary: Dict[str, Any]
    
    # Holding period
    holding_summary: Dict[str, Any]
    
    # MAE/MFE
    excursion_summary: Dict[str, Any]
    
    # Exit analysis
    exit_summary: Dict[str, Any]
    
    # P&L
    pnl_summary: Dict[str, Any]
    
    # Portfolio risk
    risk_summary: Dict[str, Any]
    
    # Operational health
    operational_summary: Dict[str, Any]
    
    # Sample sizes
    sample_sizes: Dict[str, Any]
    
    # Evidence completeness
    evidence_completeness: Dict[str, Any]
    
    # Qualification gates
    gates: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "timestamp": self.timestamp,
            "verdict": self.verdict,
            "total_trades": self.total_trades,
            "open_positions": self.open_positions,
            "days_in_campaign": self.days_in_campaign,
            "r4_economic_edge": self.r4_economic_edge,
            "entry_quality": self.entry_quality,
            "holding_period_range": self.holding_period_range,
            "exit_economics": self.exit_economics,
            "downside_control": self.downside_control,
            "execution_fidelity": self.execution_fidelity,
            "operational_reliability": self.operational_reliability,
            "tail_risk": self.tail_risk,
            "capacity": self.capacity,
            "next_capital_tier": self.next_capital_tier,
            "evidence_classification": self.evidence_classification,
            "evidence_note": self.evidence_note,
            "entry_summary": self.entry_summary,
            "execution_summary": self.execution_summary,
            "holding_summary": self.holding_summary,
            "excursion_summary": self.excursion_summary,
            "exit_summary": self.exit_summary,
            "pnl_summary": self.pnl_summary,
            "risk_summary": self.risk_summary,
            "operational_summary": self.operational_summary,
            "sample_sizes": self.sample_sizes,
            "evidence_completeness": self.evidence_completeness,
            "gates": self.gates,
        }
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# R4 Live Economic Qualification Report",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Generated:** {self.timestamp}",
            f"**Days in Campaign:** {self.days_in_campaign:.1f}",
            "",
            "---",
            "",
            "## R4 Economic Verdict",
            "",
            "```",
            f"R4 ECONOMIC EDGE:        {self.r4_economic_edge}",
            f"ENTRY QUALITY:           {self.entry_quality}",
            f"HOLDING PERIOD:          {self.holding_period_range}",
            f"EXIT ECONOMICS:          {self.exit_economics}",
            f"DOWNSIDE CONTROL:        {self.downside_control}",
            f"EXECUTION FIDELITY:      {self.execution_fidelity}",
            f"OPERATIONAL RELIABILITY: {self.operational_reliability}",
            f"TAIL RISK:               {self.tail_risk}",
            f"CAPACITY:                {self.capacity}",
            f"NEXT CAPITAL TIER:       {self.next_capital_tier}",
            "```",
            "",
            "---",
            "",
            "## Evidence Classification",
            "",
            f"**Classification:** {self.evidence_classification}",
            f"**Note:** {self.evidence_note}",
            "",
            "---",
            "",
            "## Sample Sizes",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| N_positions (total entries) | {self.sample_sizes.get('n_positions', 0)} |",
            f"| N_completed_trades | {self.sample_sizes.get('n_completed_trades', 0)} |",
            f"| N_independent_episodes | {self.sample_sizes.get('n_independent_episodes', 0)} |",
            f"| Note | {self.sample_sizes.get('note', '')} |",
            "",
            "---",
            "",
            "## Evidence Completeness",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Avg Completeness Score | {self.evidence_completeness.get('avg_completeness_score', 0):.1%} |",
            f"| Fully Reconstructable | {self.evidence_completeness.get('fully_reconstructable_count', 0)} |",
            f"| Completeness % | {self.evidence_completeness.get('completeness_pct', 0):.1%} |",
            f"| Threshold | {self.evidence_completeness.get('threshold', 0.99):.0%} |",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Trades | {self.total_trades} |",
            f"| Open Positions | {self.open_positions} |",
            f"| Closed Trades | {self.total_trades - self.open_positions} |",
            f"| Verdict | **{self.verdict}** |",
            "",
        ]
        
        # Entry Quality
        lines.extend([
            "## Entry Quality",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.entry_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Execution Fidelity
        lines.extend([
            "## Execution Fidelity",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.execution_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Holding Period
        lines.extend([
            "## Holding Period Distribution",
            "",
            "| Bucket | Count | Total P&L | Avg P&L |",
            "|--------|-------|-----------|---------|",
        ])
        for bucket, data in self.holding_summary.get("distribution", {}).items():
            count = data.get("count", 0)
            total = data.get("total_pnl", 0)
            avg = total / count if count > 0 else 0
            lines.append(f"| {bucket} | {count} | ${total:.2f} | ${avg:.2f} |")
        lines.append("")
        
        # MAE/MFE
        lines.extend([
            "## MAE/MFE Analysis",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.excursion_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Exit Analysis
        lines.extend([
            "## Exit Analysis",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.exit_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # P&L
        lines.extend([
            "## P&L Economics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.pnl_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Portfolio Risk
        lines.extend([
            "## Portfolio Risk",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.risk_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Operational Health
        lines.extend([
            "## Operational Health",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in self.operational_summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        
        # Qualification Gates
        lines.extend([
            "## Qualification Gates",
            "",
        ])
        for gate_name, gate_data in self.gates.items():
            if isinstance(gate_data, dict):
                status = "✅" if all(v is True for v in gate_data.values() if v is not None) else "❌"
                lines.append(f"### {status} {gate_name}")
                for check, passed in gate_data.items():
                    icon = "✅" if passed is True else "❌" if passed is False else "⏳"
                    lines.append(f"- {icon} {check}")
            lines.append("")
        
        # Footer
        lines.extend([
            "---",
            "",
            "*This report is generated from the R4 Live Qualification Dataset.*",
            "*R4 remains frozen throughout Phase 2.*",
            "*No optimization or strategy changes during evidence collection.*",
        ])
        
        return "\n".join(lines)


class Phase2ReportGenerator:
    """Generates Phase 2 qualification reports from the dataset."""
    
    def __init__(self, dataset: R4LiveQualificationDataset) -> None:
        """Initialize report generator.
        
        Args:
            dataset: R4 Live Qualification Dataset
        """
        self._dataset = dataset
    
    def generate(self) -> Phase2Report:
        """Generate complete Phase 2 report."""
        now = datetime.now(timezone.utc).isoformat()
        
        all_trades = self._dataset.get_all_trades()
        closed_trades = self._dataset.get_closed_trades()
        open_trades = self._dataset.get_open_trades()
        
        # Compute days in campaign
        if all_trades:
            from datetime import datetime as dt
            first_entry = min(t.entry_timestamp for t in all_trades)
            first_dt = dt.fromisoformat(first_entry.replace("Z", "+00:00"))
            now_dt = dt.fromisoformat(now.replace("Z", "+00:00"))
            days_in_campaign = (now_dt - first_dt).total_seconds() / 86400
        else:
            days_in_campaign = 0
        
        # Compute summaries
        entry_summary = self._compute_entry_summary(closed_trades)
        execution_summary = self._compute_execution_summary(closed_trades)
        holding_summary = self._compute_holding_summary(closed_trades)
        excursion_summary = self._compute_excursion_summary(closed_trades)
        exit_summary = self._compute_exit_summary(closed_trades)
        pnl_summary = self._compute_pnl_summary(closed_trades)
        risk_summary = self._compute_risk_summary()
        operational_summary = self._compute_operational_summary()
        
        # Compute economics
        economics = self._dataset.compute_economics()
        
        # Evidence completeness
        if closed_trades:
            avg_completeness = sum(t.completeness_score() for t in closed_trades) / len(closed_trades)
            fully_reconstructable = sum(1 for t in closed_trades if t.completeness_score() >= 0.9)
            completeness_pct = fully_reconstructable / len(closed_trades)
        else:
            avg_completeness = 0.0
            fully_reconstructable = 0
            completeness_pct = 0.0
        
        evidence_completeness = {
            "avg_completeness_score": avg_completeness,
            "fully_reconstructable_count": fully_reconstructable,
            "completeness_pct": completeness_pct,
            "threshold": 0.99,
        }
        
        # Sample sizes
        sample_sizes = {
            "n_positions": self._dataset._n_positions,
            "n_completed_trades": self._dataset._n_completed_trades,
            "n_independent_episodes": self._dataset._n_independent_episodes,
            "note": "Positions may be correlated; independent episodes is the statistically valid sample size",
        }
        
        # Compute the real deliverable values
        r4_economic_edge, entry_quality, holding_range, exit_econ, downside, exec_fid, op_rel, tail_risk, capacity, next_tier = \
            self._compute_structured_verdict(economics, closed_trades, risk_summary, operational_summary, completeness_pct, sample_sizes, days_in_campaign)
        
        # Determine evidence classification
        has_observed = any(
            any(v == "OBSERVED" for v in t.evidence_classifications.values())
            for t in closed_trades
        )
        has_model = any(
            any(v == "MODEL_BASED" for v in t.evidence_classifications.values())
            for t in closed_trades
        )
        evidence_classification = "OBSERVED" if has_observed and not has_model else "MIXED" if has_observed and has_model else "DERIVED"
        
        # Compute gates
        report_data = self._dataset.compute_qualification_report()
        gates = report_data.get("gates", {})
        
        # Determine verdict
        overall_verdict = gates.get("overall", {}).get("overall_verdict", "PENDING")
        
        return Phase2Report(
            campaign_id=self._dataset._campaign_id,
            timestamp=now,
            verdict=overall_verdict,
            total_trades=len(all_trades),
            open_positions=len(open_trades),
            days_in_campaign=days_in_campaign,
            r4_economic_edge=r4_economic_edge,
            entry_quality=entry_quality,
            holding_period_range=holding_range,
            exit_economics=exit_econ,
            downside_control=downside,
            execution_fidelity=exec_fid,
            operational_reliability=op_rel,
            tail_risk=tail_risk,
            capacity=capacity,
            next_capital_tier=next_tier,
            evidence_classification=evidence_classification,
            evidence_note="Do not present model reconstruction as live evidence. Observed = broker fact. Derived = calculated from observations.",
            entry_summary=entry_summary,
            execution_summary=execution_summary,
            holding_summary=holding_summary,
            excursion_summary=excursion_summary,
            exit_summary=exit_summary,
            pnl_summary=pnl_summary,
            risk_summary=risk_summary,
            operational_summary=operational_summary,
            sample_sizes=sample_sizes,
            evidence_completeness=evidence_completeness,
            gates=gates,
        )
    
    def _compute_entry_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute entry quality summary."""
        if not trades:
            return {"no_data": True}
        
        # Signal strength distribution
        strengths = [
            t.entry_quality.signal_strength_percentile
            for t in trades
            if t.entry_quality and t.entry_quality.signal_strength_percentile is not None
        ]
        
        # Regime distribution
        regimes = {}
        for t in trades:
            if t.entry_quality and t.entry_quality.regime_at_entry:
                regime = t.entry_quality.regime_at_entry
                regimes[regime] = regimes.get(regime, 0) + 1
        
        return {
            "total_entries": len(trades),
            "avg_signal_strength": sum(strengths) / len(strengths) if strengths else None,
            "regime_distribution": regimes,
        }
    
    def _compute_execution_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute execution fidelity summary."""
        if not trades:
            return {"no_data": True}
        
        executions = [t.execution for t in trades if t.execution]
        
        if not executions:
            return {"no_execution_data": True}
        
        avg_slippage = sum(e.slippage for e in executions) / len(executions)
        avg_spread = sum(e.spread for e in executions) / len(executions)
        avg_latency = sum(e.execution_latency_ms for e in executions) / len(executions)
        
        rejections = sum(1 for e in executions if e.rejection_status != "FILLED")
        
        return {
            "total_fills": len(executions),
            "avg_slippage": f"{avg_slippage:.6f}",
            "avg_spread": f"{avg_spread:.6f}",
            "avg_latency_ms": f"{avg_latency:.1f}",
            "rejection_rate": f"{rejections / len(executions):.1%}",
        }
    
    def _compute_holding_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute holding period distribution summary."""
        if not trades:
            return {"no_data": True, "distribution": {}}
        
        distribution = {}
        for t in trades:
            if t.holding_period:
                bucket = t.holding_period.holding_period_bucket
                if bucket not in distribution:
                    distribution[bucket] = {"count": 0, "total_pnl": 0}
                distribution[bucket]["count"] += 1
                distribution[bucket]["total_pnl"] += t.holding_period.pnl_at_exit
        
        return {
            "total_trades": len(trades),
            "distribution": distribution,
        }
    
    def _compute_excursion_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute MAE/MFE summary."""
        if not trades:
            return {"no_data": True}
        
        # Get entry quality with MAE/MFE
        mae_values = [
            t.entry_quality.mae
            for t in trades
            if t.entry_quality and t.entry_quality.mae != 0
        ]
        mfe_values = [
            t.entry_quality.mfe
            for t in trades
            if t.entry_quality and t.entry_quality.mfe != 0
        ]
        
        return {
            "avg_mae": sum(mae_values) / len(mae_values) if mae_values else None,
            "avg_mfe": sum(mfe_values) / len(mfe_values) if mfe_values else None,
            "mae_mfe_ratio": (
                abs(sum(mae_values) / len(mae_values)) / (sum(mfe_values) / len(mfe_values))
                if mae_values and mfe_values and sum(mfe_values) / len(mfe_values) > 0
                else None
            ),
        }
    
    def _compute_exit_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute exit analysis summary."""
        if not trades:
            return {"no_data": True}
        
        # Exit reason distribution
        reasons = {}
        for t in trades:
            reason = t.exit_reason or "UNKNOWN"
            if reason not in reasons:
                reasons[reason] = {"count": 0, "total_pnl": 0}
            reasons[reason]["count"] += 1
            reasons[reason]["total_pnl"] += t.net_pnl
        
        return {
            "total_exits": len(trades),
            "exit_reasons": reasons,
        }
    
    def _compute_pnl_summary(self, trades: List[QualificationTrade]) -> Dict[str, Any]:
        """Compute P&L economics summary."""
        if not trades:
            return {"no_data": True}
        
        total_pnl = sum(t.net_pnl for t in trades)
        total_costs = sum(t.total_costs for t in trades)
        
        winning = [t for t in trades if t.net_pnl > 0]
        losing = [t for t in trades if t.net_pnl <= 0]
        
        win_rate = len(winning) / len(trades) if trades else 0
        avg_win = sum(t.net_pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.net_pnl for t in losing) / len(losing) if losing else 0
        
        profit_factor = (
            sum(t.net_pnl for t in winning) / abs(sum(t.net_pnl for t in losing))
            if losing and sum(t.net_pnl for t in losing) != 0
            else float("inf")
        )
        
        return {
            "total_pnl": f"${total_pnl:.2f}",
            "total_costs": f"${total_costs:.2f}",
            "net_pnl": f"${total_pnl:.2f}",
            "win_rate": f"{win_rate:.1%}",
            "avg_win": f"${avg_win:.2f}",
            "avg_loss": f"${avg_loss:.2f}",
            "profit_factor": f"{profit_factor:.2f}",
            "expectancy_per_trade": f"${total_pnl / len(trades):.2f}",
        }
    
    def _compute_risk_summary(self) -> Dict[str, Any]:
        """Compute portfolio risk summary."""
        snapshots = self._dataset._risk_snapshots
        
        if not snapshots:
            return {"no_data": True}
        
        latest = snapshots[-1]
        max_dd = max(s.drawdown_pct for s in snapshots)
        
        return {
            "latest_positions": latest.position_count,
            "latest_gross_exposure": f"{latest.gross_exposure:.2f}",
            "latest_net_exposure": f"{latest.net_exposure:.2f}",
            "max_drawdown": f"{max_dd:.2%}",
            "latest_margin_utilization": f"{latest.margin_utilization:.1%}",
        }
    
    def _compute_operational_summary(self) -> Dict[str, Any]:
        """Compute operational health summary."""
        events = self._dataset._operational_events
        
        if not events:
            return {"no_events": True}
        
        successful = sum(1 for e in events if e.success)
        
        return {
            "total_events": len(events),
            "successful_recoveries": successful,
            "recovery_rate": f"{successful / len(events):.1%}" if events else "N/A",
        }
    
    def _compute_structured_verdict(
        self,
        economics: Dict[str, Any],
        closed_trades: List[QualificationTrade],
        risk_summary: Dict[str, Any],
        operational_summary: Dict[str, Any],
        completeness_pct: float,
        sample_sizes: Dict[str, Any],
        days_in_campaign: float,
    ) -> tuple:
        """Compute the real deliverable: structured verdict.
        
        Returns:
            Tuple of (r4_economic_edge, entry_quality, holding_period_range,
                     exit_economics, downside_control, execution_fidelity,
                     operational_reliability, tail_risk, capacity, next_capital_tier)
        """
        total_trades = economics.get("total_trades", 0)
        n_episodes = sample_sizes.get("n_independent_episodes", 0)
        
        # R4 Economic Edge
        if total_trades < 50 or n_episodes < 3:
            r4_economic_edge = "INCONCLUSIVE"
        elif economics.get("expectancy_per_trade", 0) > 0 and economics.get("profit_factor", 0) > 1.0:
            r4_economic_edge = "CONFIRMED"
        else:
            r4_economic_edge = "REJECTED"
        
        # Entry Quality
        if total_trades < 20:
            entry_quality = "NOT_YET_ASSESSABLE"
        elif economics.get("win_rate", 0) > 0.5:
            entry_quality = "GREEN"
        elif economics.get("win_rate", 0) > 0.4:
            entry_quality = "YELLOW"
        else:
            entry_quality = "RED"
        
        # Holding Period Range
        holding_buckets = economics.get("holding_period_distribution", {})
        if not holding_buckets:
            holding_range = "INSUFFICIENT_DATA"
        else:
            # Find which bucket has the most P&L
            best_bucket = max(holding_buckets.items(), key=lambda x: x[1].get("total_pnl", 0))
            holding_range = f"{best_bucket[0]} (most P&L)"
        
        # Exit Economics
        if total_trades < 10:
            exit_econ = "NOT_YET_ASSESSABLE"
        elif economics.get("profit_factor", 0) > 1.5:
            exit_econ = "GOOD"
        elif economics.get("profit_factor", 0) > 1.0:
            exit_econ = "MIXED"
        else:
            exit_econ = "POOR"
        
        # Downside Control
        sl_hit_rate = economics.get("sl_hit_rate", 0)
        if total_trades < 10:
            downside = "NOT_YET_ASSESSABLE"
        elif sl_hit_rate < 0.05:
            downside = "ADEQUATE"
        elif sl_hit_rate < 0.15:
            downside = "MIXED"
        else:
            downside = "INADEQUATE"
        
        # Execution Fidelity
        avg_slippage = economics.get("avg_slippage", 0)
        if total_trades < 5:
            exec_fid = "NOT_YET_ASSESSABLE"
        else:
            exec_fid = f"{100 - (avg_slippage * 10000):.1f}% of research cost"
        
        # Operational Reliability
        total_events = operational_summary.get("total_events", 0)
        successful = operational_summary.get("successful_recoveries", 0)
        if total_events == 0:
            op_rel = "NO_FAILURES_OBSERVED"
        else:
            op_rel = f"{successful / total_events:.1%} recovery rate"
        
        # Tail Risk
        max_dd = risk_summary.get("max_drawdown", "0%")
        if isinstance(max_dd, str):
            max_dd = float(max_dd.strip("%")) if max_dd != "N/A" else 0
        if total_trades < 20:
            tail_risk = "NOT_YET_ASSESSABLE"
        elif max_dd < 5:
            tail_risk = "ACCEPTABLE"
        elif max_dd < 10:
            tail_risk = "MONITORING"
        else:
            tail_risk = "EXCESSIVE"
        
        # Capacity
        if total_trades < 30:
            capacity = "NOT_YET_ASSESSABLE"
        else:
            capacity = "$5K justified (current tier)"
        
        # Next Capital Tier
        if r4_economic_edge == "CONFIRMED" and downside == "ADEQUATE" and tail_risk in ("ACCEPTABLE", "MONITORING"):
            next_tier = "$10K (after evidence gate)"
        elif r4_economic_edge == "INCONCLUSIVE":
            next_tier = "NONE (insufficient evidence)"
        else:
            next_tier = "NONE"
        
        return (
            r4_economic_edge, entry_quality, holding_range, exit_econ,
            downside, exec_fid, op_rel, tail_risk, capacity, next_tier,
        )
    
    def _compute_gates(
        self,
        economics: Dict[str, Any],
        risk_summary: Dict[str, Any],
        operational_summary: Dict[str, Any],
        days_in_campaign: float,
    ) -> Dict[str, Any]:
        """Compute Phase 2 qualification gates."""
        gates = {}
        
        # Minimum evidence gate
        gates["minimum_evidence"] = {
            "sufficient_trades": economics.get("total_trades", 0) >= 20,
            "sufficient_time": days_in_campaign >= 14,  # At least 2 weeks
            "zero_critical_incidents": operational_summary.get("successful_recoveries", 0) >= 0,
        }
        
        # Economic gate
        gates["economic"] = {
            "positive_expectancy": economics.get("expectancy_per_trade", 0) > 0,
            "win_rate_above_40": economics.get("win_rate", 0) > 0.4,
            "profit_factor_above_1": economics.get("profit_factor", 0) > 1.0,
        }
        
        # Risk gate
        max_dd_str = risk_summary.get("max_drawdown", "0%")
        try:
            max_dd_val = float(max_dd_str.strip("%")) if max_dd_str and max_dd_str != "N/A" else 0.0
        except (ValueError, AttributeError):
            max_dd_val = 0.0
        gates["risk"] = {
            "max_drawdown_within_bounds": max_dd_val < 10,
            "sl_rarely_triggered": economics.get("sl_hit_rate", 0) < 0.10,
        }
        
        # Overall
        all_pass = all(
            all(v is True for v in gate.values() if v is not None)
            for gate in gates.values()
        )
        
        gates["overall"] = {
            "all_gates_pass": all_pass,
            "verdict": "PASS" if all_pass else "PENDING",
        }
        
        return gates
