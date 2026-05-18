from typing import Optional, List, Dict
from datetime import datetime
from execution.broker_interface import BrokerInterface, Order


class OrderManager:
    def __init__(self, broker: BrokerInterface):
        self.broker = broker
        self.pending_orders: Dict[str, Order] = {}
        self.filled_orders: List[Order] = []
        self.cancelled_orders: List[Order] = []

    def submit_market_order(self, asset: str, side: str, quantity: float) -> Optional[str]:
        order = Order(
            asset=asset, side=side, quantity=quantity,
            order_type="market", timestamp=datetime.now(),
        )
        order_id = self.broker.place_order(order)
        order.order_id = order_id
        self.pending_orders[order_id] = order
        return order_id

    def submit_limit_order(
        self, asset: str, side: str, quantity: float, limit_price: float
    ) -> Optional[str]:
        order = Order(
            asset=asset, side=side, quantity=quantity,
            order_type="limit", limit_price=limit_price,
            timestamp=datetime.now(),
        )
        order_id = self.broker.place_order(order)
        order.order_id = order_id
        self.pending_orders[order_id] = order
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id not in self.pending_orders:
            return False
        success = self.broker.cancel_order(order_id)
        if success:
            order = self.pending_orders.pop(order_id)
            order.status = "cancelled"
            self.cancelled_orders.append(order)
        return success

    def check_pending_orders(self) -> List[Order]:
        filled = []
        for order_id, order in list(self.pending_orders.items()):
            status = self.broker.get_order_status(order_id)
            if status == "filled":
                order.status = "filled"
                self.filled_orders.append(order)
                self.pending_orders.pop(order_id)
                filled.append(order)
            elif status == "cancelled":
                order.status = "cancelled"
                self.cancelled_orders.append(order)
                self.pending_orders.pop(order_id)
        return filled

    def get_open_quantity(self, asset: str) -> float:
        return sum(
            o.quantity for o in self.pending_orders.values()
            if o.asset == asset and o.side == "buy"
        ) - sum(
            o.quantity for o in self.pending_orders.values()
            if o.asset == asset and o.side == "sell"
        )

    @property
    def has_pending(self) -> bool:
        return len(self.pending_orders) > 0
