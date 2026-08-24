"""Execution Evidence Collector — gathers live execution reality data.

Records every live order against what the research stack expected.
Produces distributions, not just averages.

Metrics tracked:
- intended price vs fill price
- spread at decision vs execution
- expected slippage vs realized slippage
- latency
- rejection rate
- partial-fill rate
- fill completion time
- order modification/cancellation behavior
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass(frozen=True)
class OrderEvidence:
    """Evidence from a single live order execution."""

    order_id: str
    instrument_id: str
    side: str
    intended_price: float
    fill_price: Optional[float]
    spread_at_decision: float
    spread_at_execution: float
    expected_slippage: float
    realized_slippage: float
    latency_seconds: float
    filled_quantity: float
    requested_quantity: float
    status: str  # FILLED, PARTIAL, REJECTED, CANCELLED
    rejection_reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "intended_price": self.intended_price,
            "fill_price": self.fill_price,
            "spread_at_decision": self.spread_at_decision,
            "spread_at_execution": self.spread_at_execution,
            "expected_slippage": self.expected_slippage,
            "realized_slippage": self.realized_slippage,
            "latency_seconds": self.latency_seconds,
            "filled_quantity": self.filled_quantity,
            "requested_quantity": self.requested_quantity,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "timestamp": self.timestamp,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class SlippageDistribution:
    """Distribution statistics for slippage."""

    median: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "median": self.median,
            "p75": self.p75,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
            "count": self.count,
        }


@dataclass(frozen=True)
class LatencyDistribution:
    """Distribution statistics for latency."""

    median: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "median": self.median,
            "p75": self.p75,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
            "count": self.count,
        }


@dataclass(frozen=True)
class ExecutionSummary:
    """Summary of execution evidence across all orders."""

    total_orders: int
    filled_orders: int
    partial_orders: int
    rejected_orders: int
    cancelled_orders: int
    fill_rate: float
    rejection_rate: float
    partial_fill_rate: float
    slippage_distribution: SlippageDistribution
    latency_distribution: LatencyDistribution
    total_realized_slippage: float
    total_latency: float
    average_fill_price_deviation: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_orders": self.total_orders,
            "filled_orders": self.filled_orders,
            "partial_orders": self.partial_orders,
            "rejected_orders": self.rejected_orders,
            "cancelled_orders": self.cancelled_orders,
            "fill_rate": self.fill_rate,
            "rejection_rate": self.rejection_rate,
            "partial_fill_rate": self.partial_fill_rate,
            "slippage_distribution": self.slippage_distribution.to_dict(),
            "latency_distribution": self.latency_distribution.to_dict(),
            "total_realized_slippage": self.total_realized_slippage,
            "total_latency": self.total_latency,
            "average_fill_price_deviation": self.average_fill_price_deviation,
        }


def _percentile(values: List[float], pct: float) -> float:
    """Calculate percentile of a list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100.0)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


class ExecutionEvidenceCollector:
    """Collects and analyzes execution evidence from live orders."""

    def __init__(self) -> None:
        self._evidence: List[OrderEvidence] = []

    def record_order(self, evidence: OrderEvidence) -> None:
        """Record evidence from a single order."""
        self._evidence.append(evidence)

    def get_all_evidence(self) -> List[OrderEvidence]:
        return list(self._evidence)

    def get_summary(self) -> ExecutionSummary:
        """Compute execution summary with distributions."""
        if not self._evidence:
            return ExecutionSummary(
                total_orders=0,
                filled_orders=0,
                partial_orders=0,
                rejected_orders=0,
                cancelled_orders=0,
                fill_rate=0.0,
                rejection_rate=0.0,
                partial_fill_rate=0.0,
                slippage_distribution=SlippageDistribution(),
                latency_distribution=LatencyDistribution(),
                total_realized_slippage=0.0,
                total_latency=0.0,
                average_fill_price_deviation=0.0,
            )

        filled = [e for e in self._evidence if e.status == "FILLED"]
        partial = [e for e in self._evidence if e.status == "PARTIAL"]
        rejected = [e for e in self._evidence if e.status == "REJECTED"]
        cancelled = [e for e in self._evidence if e.status == "CANCELLED"]

        total = len(self._evidence)
        slippages = [e.realized_slippage for e in self._evidence]
        latencies = [e.latency_seconds for e in self._evidence]
        price_devs = [
            abs(e.fill_price - e.intended_price) / max(abs(e.intended_price), 1e-10)
            for e in filled
            if e.fill_price is not None
        ]

        slippage_dist = SlippageDistribution(
            median=_percentile(slippages, 50),
            p75=_percentile(slippages, 75),
            p90=_percentile(slippages, 90),
            p95=_percentile(slippages, 95),
            p99=_percentile(slippages, 99),
            max=max(slippages) if slippages else 0.0,
            count=len(slippages),
        )

        latency_dist = LatencyDistribution(
            median=_percentile(latencies, 50),
            p75=_percentile(latencies, 75),
            p90=_percentile(latencies, 90),
            p95=_percentile(latencies, 95),
            p99=_percentile(latencies, 99),
            max=max(latencies) if latencies else 0.0,
            count=len(latencies),
        )

        return ExecutionSummary(
            total_orders=total,
            filled_orders=len(filled),
            partial_orders=len(partial),
            rejected_orders=len(rejected),
            cancelled_orders=len(cancelled),
            fill_rate=len(filled) / total if total > 0 else 0.0,
            rejection_rate=len(rejected) / total if total > 0 else 0.0,
            partial_fill_rate=len(partial) / total if total > 0 else 0.0,
            slippage_distribution=slippage_dist,
            latency_distribution=latency_dist,
            total_realized_slippage=sum(slippages),
            total_latency=sum(latencies),
            average_fill_price_deviation=sum(price_devs) / len(price_devs)
            if price_devs
            else 0.0,
        )
