"""Portfolio layer — aggregates strategy intents into targets, routes through risk.

The Portfolio is the central coordinator:
1. Receives StrategyIntent(s) from strategy
2. Aggregates into PortfolioTarget(s) per instrument
3. Routes through EigenRisk (fail-closed boundary)
4. Converts ApprovedTarget(s) to OrderPlan(s)

Architecture invariant:
    Strategy → StrategyIntent → Portfolio → EigenRisk → ApprovedTarget → OrderPlan

Strategy CANNOT bypass Portfolio or EigenRisk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from eigencapital.core.models.approved_target import ApprovedTarget
from eigencapital.core.models.order_plan import OrderPlan, Urgency
from eigencapital.core.models.portfolio_target import PortfolioTarget
from eigencapital.core.models.position import Position
from eigencapital.core.models.strategy_intent import StrategyIntent
from eigencapital.risk.checks.account_checks import AccountState
from eigencapital.risk.engine import EigenRiskEngine, RiskDecision


@dataclass
class PortfolioState:
    """Current state of the portfolio.

    Tracks positions, cash, and pending intents.
    """

    positions: Dict[str, Position] = field(default_factory=dict)
    current_cash: float = 100_000.0
    account_state: AccountState = field(
        default_factory=lambda: AccountState(
            equity=100_000.0,
            peak_equity=100_000.0,
            daily_pnl=0.0,
            weekly_pnl=0.0,
            gross_exposure=0.0,
            net_exposure=0.0,
            position_count=0,
        )
    )

    def update_account_state(self) -> None:
        """Recompute account state from current positions."""
        total_notional = sum(abs(p.quantity * (p.average_entry_price or 0.0)) for p in self.positions.values())
        equity = self.current_cash + sum(p.unrealized_pnl for p in self.positions.values())

        self.account_state = AccountState(
            equity=equity,
            peak_equity=max(self.account_state.peak_equity, equity),
            daily_pnl=self.account_state.daily_pnl,
            weekly_pnl=self.account_state.weekly_pnl,
            gross_exposure=total_notional,
            net_exposure=total_notional,
            position_count=sum(1 for p in self.positions.values() if p.quantity != 0),
        )

    def get_position_quantity(self, instrument_id: str) -> float:
        """Get current position quantity for an instrument (0 if none)."""
        if instrument_id in self.positions:
            return self.positions[instrument_id].quantity
        return 0.0


@dataclass(frozen=True)
class PortfolioDecision:
    """Result of portfolio processing a set of strategy intents.

    Contains the full chain: targets → risk decisions → order plans.
    """

    targets: List[PortfolioTarget] = field(default_factory=list)
    risk_decisions: List[RiskDecision] = field(default_factory=list)
    approved_targets: List[ApprovedTarget] = field(default_factory=list)
    order_plans: List[OrderPlan] = field(default_factory=list)

    @property
    def has_rejections(self) -> bool:
        """Check if any target was rejected."""
        return any(d.decision == "REJECTED" for d in self.risk_decisions)

    @property
    def has_reductions(self) -> bool:
        """Check if any target was reduced."""
        return any(d.decision == "REDUCED" for d in self.risk_decisions)

    @property
    def active_order_plans(self) -> List[OrderPlan]:
        """Get order plans with non-zero delta."""
        return [p for p in self.order_plans if p.is_fulfillable]


class Portfolio:
    """Portfolio coordinator — the central pipeline between strategy and execution.

    Architecture:
        Strategy → StrategyIntent → Portfolio → EigenRisk → ApprovedTarget → OrderPlan

    The Portfolio:
    1. Receives StrategyIntent(s) from strategy
    2. Aggregates into PortfolioTarget(s) per instrument
    3. Routes through EigenRisk (fail-closed boundary)
    4. Converts ApprovedTarget(s) to OrderPlan(s)

    Strategy CANNOT bypass Portfolio or EigenRisk.
    """

    def __init__(
        self,
        risk_engine: EigenRiskEngine | None = None,
        execution_policy_version: str = "v1",
        urgency: Urgency = Urgency.SESSION,
    ) -> None:
        self.risk_engine = risk_engine or EigenRiskEngine()
        self.execution_policy_version = execution_policy_version
        self.urgency = urgency
        self.state = PortfolioState()

    def process_intents(
        self,
        intents: List[StrategyIntent],
        strategy_config_hash: str = "default_config_hash",
        strategy_artifact_hash: str = "default_artifact_hash",
        price_map: Dict[str, float] | None = None,
    ) -> PortfolioDecision:
        """Process a batch of strategy intents through the full pipeline.

        Args:
            intents: List of StrategyIntent from strategy/strategies
            strategy_config_hash: Hash of strategy configuration
            strategy_artifact_hash: Hash of strategy implementation
            price_map: Current prices per instrument (for notional calculation)

        Returns:
            PortfolioDecision with targets, risk decisions, and order plans
        """
        if not intents:
            return PortfolioDecision()

        price_map = price_map or {}
        decision = PortfolioDecision()

        # Step 1: Aggregate intents into portfolio targets per instrument
        instrument_targets: Dict[str, StrategyIntent] = {}
        for intent in intents:
            if intent.instrument_id in instrument_targets:
                # Multiple strategies for same instrument — take latest signal
                # (production: would aggregate/resolve conflicts)
                existing = instrument_targets[intent.instrument_id]
                if intent.timestamp_utc > existing.timestamp_utc:
                    instrument_targets[intent.instrument_id] = intent
            else:
                instrument_targets[intent.instrument_id] = intent

        # Step 2: Create PortfolioTargets
        for instrument_id, intent in instrument_targets.items():
            price = price_map.get(instrument_id, 1.0)
            target_quantity = intent.direction * 1.0  # Simple: 1 contract
            target_market_value = target_quantity * price

            target = PortfolioTarget(
                target_id=f"PT-{instrument_id}-{intent.timestamp_utc}",
                instrument_id=instrument_id,
                target_quantity=target_quantity,
                target_market_value=target_market_value,
                target_risk=intent.target_risk,
                justification=f"Signal: direction={intent.direction_enum}, strategy={intent.strategy_id}",
                strategy_config_hash=strategy_config_hash,
                strategy_artifact_hash=strategy_artifact_hash,
            )
            decision.targets.append(target)

        # Step 3: Route through EigenRisk
        self.state.update_account_state()

        from eigencapital.core.models.risk_check_result import RiskCheckResult

        for target in decision.targets:
            # Clear RiskCheckResult registry before each risk evaluation
            RiskCheckResult._registry.clear()
            risk_result = self.risk_engine.evaluate(
                account_state=self.state.account_state,
                requested_notional=abs(target.target_market_value),
                requested_quantity=target.target_quantity,
            )
            decision.risk_decisions.append(risk_result)

            # Step 4: Create ApprovedTarget
            if risk_result.decision == "REJECTED":
                approved_qty = 0.0
            else:
                approved_qty = risk_result.approved_quantity

            approved = ApprovedTarget(
                target_id=target.target_id,
                intended_quantity=target.target_quantity,
                approved_quantity=approved_qty,
                decision=risk_result.decision,
                approval_reason=risk_result.reason,
            )
            decision.approved_targets.append(approved)

            # Step 5: Create OrderPlan
            current_qty = self.state.get_position_quantity(target.instrument_id)
            plan_id = f"OP-{target.instrument_id}-{target.target_id}"
            order_plan = OrderPlan(
                plan_id=plan_id,
                instrument_id=target.instrument_id,
                target_quantity=approved_qty,
                current_quantity=current_qty,
                quantity_delta=approved_qty - current_qty,
                execution_policy_version=self.execution_policy_version,
                urgency=self.urgency,
            )
            decision.order_plans.append(order_plan)

        return decision

    def apply_fill(
        self,
        instrument_id: str,
        fill_price: float,
        quantity: float,
        side: str,
    ) -> None:
        """Apply a fill to the portfolio state.

        Args:
            instrument_id: Instrument filled
            fill_price: Fill price
            quantity: Quantity filled (positive)
            side: "BUY" or "SELL"
        """
        signed_qty = quantity if side == "BUY" else -quantity

        if instrument_id not in self.state.positions:
            # Create new position
            self.state.positions[instrument_id] = Position(
                instrument_id=instrument_id,
                quantity=signed_qty,
                average_entry_price=fill_price,
                market_value=abs(signed_qty * fill_price),
                unrealized_pnl=0.0,
                realized_pnl_today=0.0,
            )
        else:
            pos = self.state.positions[instrument_id]
            old_qty = pos.quantity
            new_qty = old_qty + signed_qty

            # Update average entry price
            if new_qty != 0:
                if old_qty == 0:
                    new_avg = fill_price
                else:
                    new_avg = (old_qty * (pos.average_entry_price or 0.0) + signed_qty * fill_price) / new_qty
            else:
                new_avg = 0.0

            # Calculate realized P&L on closed portion
            realized = 0.0
            if old_qty != 0 and new_qty != 0 and (old_qty > 0) != (new_qty > 0):
                # Position reversal or partial close
                closed_qty = min(abs(old_qty), abs(signed_qty))
                realized = closed_qty * (fill_price - (pos.average_entry_price or 0.0))
                if old_qty < 0:
                    realized = -realized

            self.state.positions[instrument_id] = Position(
                instrument_id=instrument_id,
                quantity=new_qty,
                average_entry_price=new_avg if new_qty != 0 else None,
                market_value=abs(new_qty * fill_price),
                unrealized_pnl=0.0,
                realized_pnl_today=pos.realized_pnl_today + realized,
            )

        # Update cash
        commission = 2.50  # Simplified; production uses CostModel
        if side == "BUY":
            self.state.current_cash -= quantity * fill_price + commission
        else:
            self.state.current_cash += quantity * fill_price - commission
