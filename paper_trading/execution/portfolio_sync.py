from dataclasses import dataclass

from paper_trading.execution.broker_interface import BrokerInterface, Order


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

    def get_current_weights(self, portfolio_value: float) -> dict[str, float]:
        positions = self.broker.get_positions()
        weights = {}
        for pos in positions:
            market_value = pos.quantity * pos.current_price
            weights[pos.asset] = market_value / portfolio_value if portfolio_value > 0 else 0.0
        return weights

    def compute_rebalance_orders(
        self,
        target_weights: dict[str, float],
        portfolio_value: float,
        drift_threshold: float = 0.05,
    ) -> list[Order]:
        current_weights = self.get_current_weights(portfolio_value)
        orders = []

        drifted_assets = []
        for asset, target in target_weights.items():
            current = current_weights.get(asset, 0.0)
            drift = abs(target - current)
            if drift >= drift_threshold:
                drifted_assets.append(asset)

        if hasattr(self.broker, "get_current_prices"):
            prices = self.broker.get_current_prices(drifted_assets)
        else:
            prices = {a: self.broker.get_current_price(a) for a in drifted_assets}

        for asset in drifted_assets:
            target = target_weights[asset]
            current = current_weights.get(asset, 0.0)
            current_price = prices.get(asset, self.broker.get_current_price(asset))
            target_value = portfolio_value * target
            current_value = current * portfolio_value
            delta = target_value - current_value

            if abs(delta) < 1.0:
                continue

            side = "buy" if delta > 0 else "sell"
            quantity = abs(delta) / current_price
            orders.append(
                Order(
                    asset=asset,
                    side=side,
                    quantity=round(quantity, 6),
                    order_type="market",
                )
            )

        return orders

    def sync_positions(self, expected_assets: list[str]) -> dict[str, float]:
        positions = self.broker.get_positions()
        pos_dict = {p.asset: p.quantity for p in positions}
        return {a: pos_dict.get(a, 0.0) for a in expected_assets}
