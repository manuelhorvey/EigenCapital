"""MT5Broker — real broker integration via Wine MT5 bridge.

Implements BrokerInterface. Routes orders to a live demo (or real)
Exness account through the Wine-hosted MT5 terminal.

Designed as a drop-in replacement for PaperBroker.
"""

from __future__ import annotations

import logging
import threading
import time

import pytz

from paper_trading.execution.broker_interface import AccountSummary, BrokerInterface, Order, Position
from paper_trading.ops.mt5_client import MT5Client

logger = logging.getLogger("quantforge.mt5_broker")

ET = pytz.timezone("US/Eastern")

_POSITION_CACHE_TTL = 5.0


class MT5Broker(BrokerInterface):
    """Real broker integration via the Wine MT5 bridge.

    Connects to a running MT5 terminal (via the bridge server)
    and sends orders to the Exness demo account.

    Volume is in MT5 lots (1.0 = 100,000 units for forex).
    The caller is responsible for lot-size conversion.
    """

    def __init__(
        self,
        account: int = 0,
        password: str = "",
        server: str = "",
        symbol_map: dict[str, str] | None = None,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 9876,
        lot_size_map: dict[str, float] | None = None,
        client: MT5Client | None = None,
    ):
        if client is not None:
            self._client = client
        else:
            self._client = MT5Client(
                account=account,
                password=password,
                server=server,
                bridge_host=bridge_host,
                bridge_port=bridge_port,
                symbol_map=symbol_map or {},
            )
        self._symbol_map = symbol_map or {}
        self._lot_size_map = lot_size_map or {}
        self._connected = False

        # Cache for positions (avoids hammering the bridge)
        self._position_cache: list[Position] = []
        self._position_cache_time = 0.0
        self._cache_lock = threading.Lock()

    # ── Connection lifecycle ────────────────────────────────────────────

    def connect(self) -> bool:
        if self._connected:
            return True
        ok = self._client.connect()
        if ok:
            self._connected = True
            account_info = self._client.get_account()
            if account_info:
                logger.info(
                    "MT5Broker connected: account=%d (%s) balance=%.2f %s",
                    account_info.get("login", self._client.account),
                    account_info.get("name", ""),
                    account_info.get("balance", 0),
                    account_info.get("currency", ""),
                )
            else:
                logger.info("MT5Broker connected to bridge")
        return ok

    def disconnect(self) -> bool:
        self._client.disconnect()
        self._connected = False
        return True

    def ensure_connected(self) -> bool:
        if not self._connected:
            return self.connect()
        return self._client.ensure_connected()

    # ── Account ─────────────────────────────────────────────────────────

    def get_account_summary(self) -> AccountSummary:
        self.ensure_connected()
        info = self._client.get_account()
        if info is None:
            raise ConnectionError("Cannot fetch account info")

        positions = self.get_positions()
        total_value = info.get("balance", 0.0)
        buying_power = info.get("equity", total_value) * info.get("leverage", 1)

        return AccountSummary(
            total_cash=round(info.get("balance", 0), 2),
            buying_power=round(buying_power, 2),
            portfolio_value=round(info.get("equity", total_value), 2),
            positions=positions,
        )

    # ── Orders ─────────────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        self.ensure_connected()

        if order.order_type != "market":
            logger.warning("MT5Broker only supports market orders; got %s", order.order_type)
            return ""

        volume = self._quantity_to_lots(order.asset, order.quantity)
        if volume <= 0:
            logger.error("Invalid volume for %s: qty=%s", order.asset, order.quantity)
            return ""

        try:
            result = self._client.place_order(
                ticker=order.asset,
                side=order.side,
                volume=volume,
                sl=order.sl or 0.0,
                tp=order.tp or 0.0,
                comment="QuantForge",
            )
        except Exception as e:
            logger.error("Order placement failed for %s: %s", order.asset, e)
            return ""

        retcode = result.get("retcode", -1)
        ticket = result.get("ticket", 0)

        if retcode != 10009:
            logger.error(
                "Order rejected: retcode=%d ticket=%s asset=%s side=%s vol=%.2f",
                retcode,
                ticket,
                order.asset,
                order.side,
                volume,
            )
            return ""

        order_id = str(ticket)
        logger.info(
            "Order filled: %s %s %.4f lots (ticket=%s)",
            order.side,
            order.asset,
            volume,
            order_id,
        )
        return order_id

    def close_position(self, asset: str, position_id: str) -> bool:
        self.ensure_connected()
        ticket = int(position_id)
        result = self._client.close_position(ticket)
        retcode = result.get("result", {}).get("retcode", -1)
        if retcode != 10009:
            logger.error("Close position failed: retcode=%d ticket=%s asset=%s", retcode, ticket, asset)
            return False
        logger.info("Position closed: ticket=%s asset=%s", ticket, asset)
        return True

    def modify_position(self, asset: str, position_id: str, sl: float | None = None, tp: float | None = None) -> bool:
        self.ensure_connected()
        ticket = int(position_id)
        result = self._client.modify_position(ticket, sl=sl, tp=tp)
        retcode = result.get("result", {}).get("retcode", -1)
        if retcode != 10009:
            logger.error("Modify position failed: retcode=%d ticket=%s asset=%s", retcode, ticket, asset)
            return False
        logger.info("Position modified: ticket=%s asset=%s sl=%s tp=%s", ticket, asset, sl, tp)
        return True

    def cancel_order(self, order_id: str) -> bool:
        logger.warning("cancel_order not implemented for MT5")
        return False

    def get_order_status(self, order_id: str) -> str:
        return "filled"

    # ── Positions ──────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        self.ensure_connected()
        now = time.monotonic()
        with self._cache_lock:
            if now - self._position_cache_time < _POSITION_CACHE_TTL and self._position_cache:
                return self._position_cache

        try:
            raw = self._client.get_positions()
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            with self._cache_lock:
                return list(self._position_cache) if self._position_cache else []

        positions = []
        for p in raw:
            side = "buy" if p.get("type") == "buy" else "sell"
            quantity = self._lots_to_quantity(p.get("symbol", ""), p.get("volume", 0))
            pos = Position(
                asset=p.get("symbol", ""),
                quantity=quantity if side == "buy" else -quantity,
                avg_entry_price=float(p.get("price_open", 0)),
                current_price=float(p.get("price_current", 0)),
                unrealized_pnl=float(p.get("profit", 0)),
                realized_pnl=float(p.get("commission", 0)),
            )
            positions.append(pos)

        with self._cache_lock:
            self._position_cache = positions
            self._position_cache_time = now
        return positions

    def get_current_price(self, asset: str) -> float:
        self.ensure_connected()
        price = self._client.realtime_mid_price(asset)
        if price is not None:
            return price
        logger.warning("No price for %s via MT5 bridge", asset)
        return 0.0

    def get_current_prices(self, assets: list[str]) -> dict[str, float]:
        """Fetch mid-prices for multiple assets concurrently."""
        self.ensure_connected()
        results = self._client.batch_realtime_price(assets)
        return {
            a: (p if p is not None else 0.0)
            for a, p in results.items()
        }

    # ── Lot / Quantity conversion ──────────────────────────────────────

    def _quantity_to_lots(self, asset: str, quantity: float) -> float:
        info = self._client.symbol_info(asset)
        if info:
            contract_size = info.get("contract_size", 100000.0)
            step = info.get("volume_step", 0.01)
            min_vol = info.get("min_volume", 0.01)
            max_vol = info.get("max_volume", 100.0)
            lots = quantity / contract_size
            lots = round(lots / step) * step
            lots = max(min_vol, min(lots, max_vol))
            return lots
        return quantity

    def _lots_to_quantity(self, mt5_symbol: str, lots: float) -> float:
        info = self._client.symbol_info(mt5_symbol)
        if info:
            return lots * info.get("contract_size", 100000.0)
        return lots * 100000.0
