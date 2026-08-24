"""Shadow Execution Engine — compares paper path against actual broker boundary.

Shadow mode exercises the same decision/risk/order pipeline as live,
but records what WOULD have been sent to the broker without actually
submitting orders.

The key comparison:
- Paper path: what our system decided
- Shadow path: what the broker boundary would execute
- Divergence: where they differ
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
    ParityBoundary,
    ParitySummary,
)
from eigencapital.fidelity.verdict import FidelityEvaluator, FidelityReport

logger = logging.getLogger(__name__)


class ShadowOrderStatus(str, Enum):
    """Shadow order status."""

    WOULD_SUBMIT = "would_submit"
    WOULD_REJECT = "would_reject"
    WOULD_PARTIAL = "would_partial"
    WOULD_CANCEL = "would_cancel"


class DivergenceClass(str, Enum):
    """Classification of paper vs shadow divergence."""

    MATCH = "match"
    EXPECTED = "expected"  # intentional (e.g., spread model difference)
    TOLERABLE = "tolerable"
    UNEXPLAINED = "unexplained"
    CRITICAL = "critical"


@dataclass
class ShadowOrder:
    """A hypothetical order that would be sent to the broker."""

    order_id: str
    timestamp: str
    instrument_id: str
    side: str  # "BUY" or "SELL"
    quantity: float
    order_type: str  # "MARKET", "LIMIT"
    limit_price: float
    stop_loss: float
    take_profit: float
    expected_fill_price: float
    expected_spread: float
    status: ShadowOrderStatus = ShadowOrderStatus.WOULD_SUBMIT
    rejection_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "expected_fill_price": self.expected_fill_price,
            "expected_spread": self.expected_spread,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class ShadowDivergence:
    """A divergence between paper and shadow paths."""

    divergence_id: str
    timestamp: str
    instrument_id: str
    category: str  # "signal", "order", "fill", "position", "risk"
    paper_value: Any
    shadow_value: Any
    classification: DivergenceClass
    magnitude: float
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "divergence_id": self.divergence_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "category": self.category,
            "paper_value": str(self.paper_value),
            "shadow_value": str(self.shadow_value),
            "classification": self.classification.value,
            "magnitude": self.magnitude,
            "explanation": self.explanation,
        }


@dataclass
class ShadowResult:
    """Complete shadow campaign result."""

    campaign_id: str
    manifest_identity: str
    total_signals: int
    total_orders: int
    total_divergences: int
    exact_matches: int
    expected_differences: int
    tolerable_divergences: int
    unexplained_divergences: int
    critical_divergences: int
    match_rate: float
    orders_would_submit: int
    orders_would_reject: int
    status: str
    divergences: List[ShadowDivergence] = field(default_factory=list)
    orders: List[ShadowOrder] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "manifest_identity": self.manifest_identity,
            "total_signals": self.total_signals,
            "total_orders": self.total_orders,
            "total_divergences": self.total_divergences,
            "exact_matches": self.exact_matches,
            "expected_differences": self.expected_differences,
            "tolerable_divergences": self.tolerable_divergences,
            "unexplained_divergences": self.unexplained_divergences,
            "critical_divergences": self.critical_divergences,
            "match_rate": self.match_rate,
            "orders_would_submit": self.orders_would_submit,
            "orders_would_reject": self.orders_would_reject,
            "status": self.status,
        }


class ShadowEngine:
    """Shadow execution engine.

    Runs the same decision pipeline as paper, but records what the broker
    boundary would do at each step. Compares paper vs shadow to detect
    divergences.
    """

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest
        self._campaign_id = f"SHADOW-{manifest.compute_identity()[:12]}"
        self._parity = ResearchPaperParityEngine(self._campaign_id)
        self._divergences: List[ShadowDivergence] = []
        self._orders: List[ShadowOrder] = []
        self._div_counter = 0
        self._order_counter = 0

        # Pre-registered shadow configuration
        self._max_spread = 0.0010  # 10 pips max spread
        self._min_liquidity = 0.01  # minimum liquidity threshold
        self._max_slippage = 0.0005  # 5 pips max slippage

    def compare_signals(
        self,
        timestamp: str,
        instrument_id: str,
        paper_signal: float,
        shadow_signal: float,
    ) -> ShadowDivergence:
        """Compare paper signal vs shadow signal."""
        self._div_counter += 1
        magnitude = abs(paper_signal - shadow_signal)

        if magnitude == 0:
            classification = DivergenceClass.MATCH
        elif magnitude < 1e-6:
            classification = DivergenceClass.TOLERABLE
        else:
            classification = DivergenceClass.UNEXPLAINED

        div = ShadowDivergence(
            divergence_id=f"SDIV-{self._div_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument_id,
            category="signal",
            paper_value=paper_signal,
            shadow_value=shadow_signal,
            classification=classification,
            magnitude=magnitude,
            explanation="Signal comparison",
        )
        self._divergences.append(div)
        return div

    def compare_orders(
        self,
        timestamp: str,
        instrument_id: str,
        paper_order: Dict[str, Any],
        shadow_order: ShadowOrder,
    ) -> ShadowDivergence:
        """Compare paper order vs shadow order."""
        self._div_counter += 1

        # Compare key fields
        paper_side = paper_order.get("side", "")
        paper_qty = paper_order.get("quantity", 0.0)
        paper_price = paper_order.get("price", 0.0)

        diffs = []
        magnitude = 0.0

        if paper_side != shadow_order.side:
            diffs.append(f"side: {paper_side} vs {shadow_order.side}")
            magnitude += 1.0

        if abs(paper_qty - shadow_order.quantity) > 1e-6:
            diffs.append(f"qty: {paper_qty} vs {shadow_order.quantity}")
            magnitude += abs(paper_qty - shadow_order.quantity)

        if abs(paper_price - shadow_order.expected_fill_price) > 0.001:
            diffs.append(f"price: {paper_price} vs {shadow_order.expected_fill_price}")
            magnitude += abs(paper_price - shadow_order.expected_fill_price)

        if not diffs:
            classification = DivergenceClass.MATCH
            explanation = "Order matches exactly"
        else:
            classification = DivergenceClass.TOLERABLE
            explanation = "; ".join(diffs)

        div = ShadowDivergence(
            divergence_id=f"SDIV-{self._div_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument_id,
            category="order",
            paper_value=paper_order,
            shadow_value=shadow_order.to_dict(),
            classification=classification,
            magnitude=magnitude,
            explanation=explanation,
        )
        self._divergences.append(div)
        return div

    def generate_shadow_order(
        self,
        timestamp: str,
        instrument_id: str,
        side: str,
        quantity: float,
        current_price: float,
        spread: float,
    ) -> ShadowOrder:
        """Generate a hypothetical shadow order."""
        self._order_counter += 1

        # Determine if order would be submitted or rejected
        status = ShadowOrderStatus.WOULD_SUBMIT
        rejection_reason = ""

        if spread > self._max_spread:
            status = ShadowOrderStatus.WOULD_REJECT
            rejection_reason = f"Spread {spread:.4f} exceeds max {self._max_spread:.4f}"

        if quantity <= 0:
            status = ShadowOrderStatus.WOULD_REJECT
            rejection_reason = "Zero quantity"

        # Expected fill price with slippage
        slippage = self._max_slippage if side == "BUY" else -self._max_slippage
        expected_fill = current_price + slippage

        order = ShadowOrder(
            order_id=f"SORD-{self._order_counter:06d}",
            timestamp=timestamp,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            order_type="MARKET",
            limit_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            expected_fill_price=expected_fill,
            expected_spread=spread,
            status=status,
            rejection_reason=rejection_reason,
        )
        self._orders.append(order)
        return order

    def get_result(self) -> ShadowResult:
        """Compute shadow campaign result."""
        total = len(self._divergences)
        matches = sum(1 for d in self._divergences if d.classification == DivergenceClass.MATCH)
        expected = sum(1 for d in self._divergences if d.classification == DivergenceClass.EXPECTED)
        tolerable = sum(1 for d in self._divergences if d.classification == DivergenceClass.TOLERABLE)
        unexplained = sum(1 for d in self._divergences if d.classification == DivergenceClass.UNEXPLAINED)
        critical = sum(1 for d in self._divergences if d.classification == DivergenceClass.CRITICAL)

        orders_submit = sum(1 for o in self._orders if o.status == ShadowOrderStatus.WOULD_SUBMIT)
        orders_reject = sum(1 for o in self._orders if o.status == ShadowOrderStatus.WOULD_REJECT)

        match_rate = matches / total if total > 0 else 1.0

        if critical > 0:
            status = "BLOCKED"
        elif unexplained > 0:
            status = "WARNING"
        else:
            status = "PASS"

        return ShadowResult(
            campaign_id=self._campaign_id,
            manifest_identity=self._manifest.compute_identity(),
            total_signals=total,
            total_orders=len(self._orders),
            total_divergences=total,
            exact_matches=matches,
            expected_differences=expected,
            tolerable_divergences=tolerable,
            unexplained_divergences=unexplained,
            critical_divergences=critical,
            match_rate=match_rate,
            orders_would_submit=orders_submit,
            orders_would_reject=orders_reject,
            status=status,
            divergences=list(self._divergences),
            orders=list(self._orders),
        )

    @property
    def parity_engine(self) -> ResearchPaperParityEngine:
        return self._parity
