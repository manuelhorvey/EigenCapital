import logging
from datetime import datetime

import numpy as np
import pytz
import yfinance as yf

from paper_trading.execution.broker_interface import AccountSummary, BrokerInterface, Order, Position
from shared.execution_config import (
    DEFAULT_EXECUTION_CONFIGS,
    ExecutionConfig,
    compute_market_impact,
    compute_slippage_cost,
)

logger = logging.getLogger("eigencapital.paper_broker")

ET = pytz.timezone("US/Eastern")


class PaperBroker(BrokerInterface):
    """
    Simulated broker that fills market orders at yfinance prices.
    Uses asset-specific ExecutionConfig for realistic spread expansion.
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        execution_configs: dict[str, ExecutionConfig] | None = None,
        fees: float = 0.0,
        allow_short: bool = False,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.execution_configs = execution_configs or DEFAULT_EXECUTION_CONFIGS
        self.fees = fees
        self.allow_short = allow_short
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._next_order_id = 1
        self._price_cache: dict[str, float] = {}
        self._returns_history: dict[str, list[float]] = {}
        self._last_price: dict[str, float] = {}

    def connect(self) -> bool:
        return True

    def disconnect(self) -> bool:
        return True

    def get_account_summary(self) -> AccountSummary:
        positions = list(self._positions.values())
        portfolio_value = self.cash + sum(p.quantity * p.current_price for p in positions)
        buying_power = self.cash * 2
        return AccountSummary(
            total_cash=round(self.cash, 2),
            buying_power=round(buying_power, 2),
            portfolio_value=round(portfolio_value, 2),
            positions=positions,
        )

    def _get_config(self, asset: str) -> ExecutionConfig:
        return self.execution_configs.get(asset, self.execution_configs.get("default", ExecutionConfig()))

    def _update_vol_tracking(self, asset: str, current_price: float) -> None:
        if asset in self._last_price:
            prev_price = self._last_price[asset]
            if prev_price > 0:
                ret = current_price / prev_price - 1.0
                self._returns_history.setdefault(asset, []).append(ret)

                # Prune history to avoid memory bloat, keep enough for a few windows
                config = self._get_config(asset)
                max_history = config.vol_window * 10
                if len(self._returns_history[asset]) > max_history:
                    self._returns_history[asset] = self._returns_history[asset][-max_history:]

        self._last_price[asset] = current_price

    def get_vol_zscore(self, asset: str) -> float:
        history = self._returns_history.get(asset, [])
        config = self._get_config(asset)
        if len(history) < config.vol_window:
            return 1.0

        recent = np.array(history[-config.vol_window :])
        full = np.array(history)

        recent_std = np.std(recent)
        full_std = np.std(full)

        if full_std < 1e-10:
            return 1.0

        return float(recent_std / full_std)

    def _finalize_order(self, order: Order) -> str:
        order_id = str(self._next_order_id)
        self._next_order_id += 1
        order.order_id = order_id
        order.status = "filled"
        order.timestamp = datetime.now(tz=ET)
        self._orders[order_id] = order
        return order_id

    def _apply_fill(self, order: Order, fill_price: float, fill_qty: float, fee: float) -> bool:
        if order.side == "buy":
            pos = self._positions.get(order.asset)
            if pos is not None and pos.quantity < 0:
                cover_qty = min(fill_qty, abs(pos.quantity))
                realized = (pos.avg_entry_price - fill_price) * cover_qty - fee
                pos.realized_pnl += realized
                pos.quantity += cover_qty
                self.cash -= fill_price * cover_qty + fee
                if pos.quantity == 0:
                    del self._positions[order.asset]
                remaining_qty = fill_qty - cover_qty
                if remaining_qty <= 0:
                    return True
                cost = fill_price * remaining_qty
                self.cash -= cost
                self._update_position(order.asset, remaining_qty, fill_price)
                return True

            cost = fill_price * fill_qty
            self.cash -= cost + fee
            self._update_position(order.asset, fill_qty, fill_price)
            return True

        if order.side == "sell":
            pos = self._positions.get(order.asset)
            if pos is not None and pos.quantity > 0:
                sell_qty = min(fill_qty, pos.quantity)
                realized = (fill_price - pos.avg_entry_price) * sell_qty - fee
                pos.realized_pnl += realized
                pos.quantity -= sell_qty
                self.cash += fill_price * sell_qty - fee
                if pos.quantity <= 0:
                    del self._positions[order.asset]
                remaining_qty = fill_qty - sell_qty
                if remaining_qty <= 0:
                    return True
                if not self.allow_short:
                    return True
                self._open_short(order.asset, remaining_qty, fill_price)
                return True

            if pos is None and not self.allow_short:
                logger.warning("No position to sell for %s", order.asset)
                return False

            self._open_short(order.asset, fill_qty, fill_price)
            self.cash -= fee
            return True

        logger.warning("Unsupported order side %s for %s", order.side, order.asset)
        return False

    def place_filled_order(self, order: Order, fill_price: float) -> str:
        """Record a market order using an externally computed fill price."""
        if fill_price <= 0:
            logger.error("Invalid fill price %s for %s", fill_price, order.asset)
            return ""
        fill_qty = order.quantity
        fee = fill_price * fill_qty * self.fees
        if order.side == "buy" and fill_price * fill_qty + fee > self.cash:
            fill_qty = self.cash / (fill_price * (1 + self.fees))
            fee = fill_price * fill_qty * self.fees
            logger.info("Order partially filled: %s qty reduced to %.4f", order.asset, fill_qty)
        if not self._apply_fill(order, fill_price, fill_qty, fee):
            return ""
        order.quantity = fill_qty
        return self._finalize_order(order)

    def place_order(self, order: Order) -> str:
        price = self.get_current_price(order.asset)
        if price <= 0:
            logger.error("Invalid price %s for %s", price, order.asset)
            return ""

        self._update_vol_tracking(order.asset, price)
        vol_z = self.get_vol_zscore(order.asset)
        config = self._get_config(order.asset)

        slippage = compute_slippage_cost(np.array([vol_z]), config)[0]
        impact = compute_market_impact(order.quantity * price, config)
        total_slippage = slippage + impact

        fill_price = price * (1 + total_slippage) if order.side == "buy" else price * (1 - total_slippage)
        fill_qty = order.quantity
        cost = fill_price * fill_qty
        fee = cost * self.fees

        if order.side == "buy":
            total_required = cost + fee
            if total_required > self.cash:
                fill_qty = self.cash / (fill_price * (1 + self.fees))
                cost = fill_price * fill_qty
                fee = cost * self.fees
                logger.info("Order partially filled: %s qty reduced to %.4f", order.asset, fill_qty)
        if not self._apply_fill(order, fill_price, fill_qty, fee):
            return ""

        order.quantity = fill_qty
        order_id = self._finalize_order(order)
        logger.debug(
            "Order %s: %s %s %.4f @ %.2f (vol_z=%.2f, slippage=%.4f, impact=%.4f)",
            order_id,
            order.side,
            order.asset,
            fill_qty,
            fill_price,
            vol_z,
            slippage,
            impact,
        )
        return order_id

    def close_position(self, asset: str, position_id: str) -> bool:
        return True

    def modify_position(self, asset: str, position_id: str, sl: float | None = None, tp: float | None = None) -> bool:
        return True

    def cancel_order(self, order_id: str) -> bool:
        return False

    def get_order_status(self, order_id: str) -> str:
        order = self._orders.get(order_id)
        return order.status if order else "unknown"

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_current_price(self, asset: str) -> float:
        if asset in self._price_cache:
            return self._price_cache[asset]
        try:
            ticker = yf.Ticker(asset)
            data = ticker.history(period="1d")
            if not data.empty:
                price = float(data["Close"].iloc[-1])
                self._price_cache[asset] = price
                return price
        except Exception as e:
            logger.warning("Price fetch failed for %s: %s", asset, e)
        return 0.0

    def _update_position(self, asset: str, quantity: float, price: float) -> None:
        if quantity <= 0:
            return
        if asset in self._positions:
            pos = self._positions[asset]
            total_qty = pos.quantity + quantity
            total_cost = pos.avg_entry_price * pos.quantity + price * quantity
            pos.avg_entry_price = total_cost / total_qty
            pos.quantity = total_qty
        else:
            self._positions[asset] = Position(
                asset=asset,
                quantity=quantity,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )

    def _open_short(self, asset: str, quantity: float, price: float) -> None:
        proceeds = price * quantity
        self.cash += proceeds
        if asset in self._positions:
            pos = self._positions[asset]
            total_qty = abs(pos.quantity) + quantity
            total_proceeds = pos.avg_entry_price * abs(pos.quantity) + proceeds
            pos.avg_entry_price = total_proceeds / total_qty
            pos.quantity -= quantity
        else:
            self._positions[asset] = Position(
                asset=asset,
                quantity=-quantity,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )

    def refresh_prices(self) -> None:
        for asset in list(self._positions.keys()):
            price = self.get_current_price(asset)
            if price > 0:
                pos = self._positions[asset]
                pos.current_price = price
                if pos.quantity >= 0:
                    pos.unrealized_pnl = (price - pos.avg_entry_price) * pos.quantity
                else:
                    pos.unrealized_pnl = (pos.avg_entry_price - price) * abs(pos.quantity)

    def set_price(self, asset: str, price: float) -> None:
        self._price_cache[asset] = price

    def reset(self, capital: float = 100_000) -> None:
        self.initial_capital = capital
        self.cash = capital
        self._positions.clear()
        self._orders.clear()
        self._next_order_id = 1
        self._price_cache.clear()
