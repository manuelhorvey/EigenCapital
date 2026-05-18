from typing import List, Dict, Optional
from dataclasses import dataclass
from execution.broker_interface import BrokerInterface, Position, Order


@dataclass
class TargetAllocation:
    asset: str
    target_weight: float
    current_weight: float
    drift: float


class PortfolioSync:
    def __init__(self, broker: BrokerInterface):
        self.broker = broker
        self._last_sync = None

    def get_current_weights(self, portfolio_value: float) -> Dict[str, float]:
        positions = self.broker.get_positions()
        weights = {}
        for pos in positions:
            market_value = pos.quantity * pos.current_price
            weights[pos.asset] = market_value / portfolio_value if portfolio_value > 0 else 0.0
        return weights

    def compute_rebalance_orders(
        self,
        target_weights: Dict[str, float],
        portfolio_value: float,
        drift_threshold: float = 0.05,
    ) -> List[Order]:
        current_weights = self.get_current_weights(portfolio_value)
        positions = {p.asset: p for p in self.broker.get_positions()}
        orders = []

        for asset, target in target_weights.items():
            current = current_weights.get(asset, 0.0)
            drift = abs(target - current)
            if drift < drift_threshold:
                continue

            current_price = self.broker.get_current_price(asset)
            target_value = portfolio_value * target
            current_value = current * portfolio_value
            delta = target_value - current_value

            if abs(delta) < 1.0:
                continue

            side = "buy" if delta > 0 else "sell"
            quantity = abs(delta) / current_price
            orders.append(
                Order(
                    asset=asset, side=side, quantity=round(quantity, 6),
                    order_type="market",
                )
            )

        return orders

    def sync_positions(self, expected_assets: List[str]) -> Dict[str, float]:
        positions = self.broker.get_positions()
        pos_dict = {p.asset: p.quantity for p in positions}
        missing = [a for a in expected_assets if a not in pos_dict]
        return {a: pos_dict.get(a, 0.0) for a in expected_assets}
