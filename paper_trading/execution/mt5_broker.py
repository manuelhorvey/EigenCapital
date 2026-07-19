"""MT5Broker — real broker integration via Wine MT5 bridge.

Implements BrokerInterface. Routes orders to a live demo (or real)
Exness account through the Wine-hosted MT5 terminal.

Designed as a drop-in replacement for PaperBroker.
"""

from __future__ import annotations

import logging
import threading
import time

import pandas as pd
import pytz

from paper_trading.config_manager import DEFAULT_MT5_BRIDGE_PORT
from paper_trading.execution.broker_interface import AccountSummary, BrokerInterface, Order, Position
from paper_trading.ops.mt5_client import MT5Client, MT5ConnectionError

logger = logging.getLogger("eigencapital.mt5_broker")

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
        bridge_port: int = DEFAULT_MT5_BRIDGE_PORT,
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

        # MT5 drawdown tracking for independent sizing
        self._peak_equity: float | None = None

        # Optional WAL writer for order lifecycle events
        self._wal_writer = None

    def set_wal_writer(self, wal_writer) -> None:
        """Attach a WAL writer for order lifecycle event logging."""
        self._wal_writer = wal_writer

    def _wal_event(self, event_type: str, payload: dict) -> None:
        """Write a WAL event if a writer is attached."""
        if self._wal_writer is not None:
            try:
                self._wal_writer.write(event_type, payload)
            except (OSError, RuntimeError, KeyError) as e:
                logger.debug("WAL write failed for %s: %s", event_type, e)

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
        equity = info.get("equity", total_value)
        buying_power = equity * info.get("leverage", 1)

        # Track peak equity for MT5 drawdown
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity

        return AccountSummary(
            total_cash=round(info.get("balance", 0), 2),
            buying_power=round(buying_power, 2),
            portfolio_value=round(equity, 2),
            positions=positions,
        )

    def current_mt5_drawdown_pct(self) -> float:
        """Current drawdown from MT5 peak equity, as a negative fraction (e.g. -0.05 for 5% down)."""
        if self._peak_equity is None or self._peak_equity <= 0:
            return 0.0
        try:
            summary = self.get_account_summary()
            current = summary.portfolio_value
        except (OSError, TypeError, ValueError, AttributeError):
            return 0.0
        if current <= 0 or self._peak_equity <= 0:
            return 0.0
        return current / self._peak_equity - 1.0

    # ── Orders ─────────────────────────────────────────────────────────

    def place_filled_order(self, order: Order, fill_price: float) -> str:
        """Place a market order using an externally provided fill price.

        MT5Broker ignores the provided fill_price since execution price
        is determined by the broker; this is equivalent to a market order.
        """
        return self.place_order(order)

    def place_order(self, order: Order) -> str:
        self.ensure_connected()

        if order.order_type != "market":
            logger.warning("MT5Broker only supports market orders; got %s", order.order_type)
            self._wal_event(
                "mt5_order_rejected",
                {
                    "asset": order.asset,
                    "side": order.side,
                    "reason": f"unsupported_order_type:{order.order_type}",
                },
            )
            return ""

        volume = self._quantity_to_lots(order.asset, order.quantity)
        if volume <= 0:
            logger.error("Invalid volume for %s: qty=%s", order.asset, order.quantity)
            self._wal_event(
                "mt5_order_rejected",
                {
                    "asset": order.asset,
                    "side": order.side,
                    "reason": f"invalid_volume:{order.quantity}",
                },
            )
            return ""

        id_key = f"{order.asset}_{order.side}_{int(time.time() / 30)}"

        self._wal_event(
            "mt5_order_placed",
            {
                "asset": order.asset,
                "side": order.side,
                "volume": volume,
                "sl": order.sl,
                "tp": order.tp,
                "idempotency_key": id_key,
            },
        )

        try:
            result = self._client.place_order(
                ticker=order.asset,
                side=order.side,
                volume=volume,
                sl=0.0 if (order.sl is None or pd.isna(order.sl)) else order.sl,
                tp=0.0 if (order.tp is None or pd.isna(order.tp)) else order.tp,
                comment="EigenCapital",
                idempotency_key=id_key,
            )
        except (OSError, TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.error("Order placement failed for %s: %s", order.asset, e)
            self._wal_event(
                "mt5_order_rejected",
                {
                    "asset": order.asset,
                    "side": order.side,
                    "volume": volume,
                    "reason": f"exception:{e}",
                },
            )
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
            self._wal_event(
                "mt5_order_rejected",
                {
                    "asset": order.asset,
                    "side": order.side,
                    "volume": volume,
                    "retcode": retcode,
                    "ticket": ticket,
                },
            )
            return ""

        order_id = str(ticket)
        self._wal_event(
            "mt5_order_filled",
            {
                "asset": order.asset,
                "side": order.side,
                "volume": volume,
                "ticket": order_id,
                "retcode": retcode,
            },
        )
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

        error = result.get("error", "")
        if "not found" in error:
            self._wal_event(
                "mt5_position_closed",
                {
                    "asset": asset,
                    "ticket": str(ticket),
                    "reason": "already_closed",
                },
            )
            logger.info(
                "Position already closed: ticket=%s asset=%s (raw=%s)",
                ticket,
                asset,
                result,
            )
            return True

        retcode = result.get("result", {}).get("retcode", -1)
        if retcode != 10009:
            logger.error("Close position failed: retcode=%d ticket=%s asset=%s", retcode, ticket, asset)
            self._wal_event(
                "mt5_position_closed",
                {
                    "asset": asset,
                    "ticket": str(ticket),
                    "retcode": retcode,
                    "reason": "close_failed",
                },
            )
            return False

        self._wal_event(
            "mt5_position_closed",
            {
                "asset": asset,
                "ticket": str(ticket),
                "retcode": retcode,
                "reason": "closed",
            },
        )
        logger.info("Position closed: ticket=%s asset=%s", ticket, asset)
        return True

    def _verify_sltp_applied(
        self, ticket: int, asset: str, submitted_sl: float | None, submitted_tp: float | None
    ) -> bool:
        """Read back position from broker to verify SL/TP was applied correctly.

        Fetches positions directly from the bridge (bypassing the TTL cache)
        to ensure a fresh read. Logs ERROR on mismatch and returns False so
        the caller can escalate."""
        try:
            # Bypass cache: directly fetch from bridge for verification
            raw = self._client.get_positions()
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
                    realized_pnl=0.0,
                    stop_loss=p.get("sl", 0.0),
                    take_profit=p.get("tp", 0.0),
                    position_id=str(p.get("ticket", "")),
                )
                positions.append(pos)
            # Update cache with fresh data
            with self._cache_lock:
                self._position_cache = positions
                self._position_cache_time = time.monotonic()
        except (OSError, TypeError, ValueError, KeyError, MT5ConnectionError) as e:
            logger.error("SLTP_VERIFY: failed to fetch positions for ticket=%s asset=%s: %s", ticket, asset, e)
            return False
        for p in positions:
            if p.position_id == str(ticket):
                # Broker may return None for unset SL/TP — treat as 0.0
                actual_sl = float(p.stop_loss) if p.stop_loss is not None else 0.0
                actual_tp = float(p.take_profit) if p.take_profit is not None else 0.0
                sub_sl = 0.0 if submitted_sl is None else float(submitted_sl)
                sub_tp = 0.0 if submitted_tp is None else float(submitted_tp)

                sl_match = abs(actual_sl - sub_sl) < 1e-4 or (actual_sl == 0.0 and sub_sl == 0.0)
                tp_match = abs(actual_tp - sub_tp) < 1e-4 or (actual_tp == 0.0 and sub_tp == 0.0)

                if not sl_match:
                    logger.error(
                        "SLTP_VERIFY_SL_MISMATCH: ticket=%s asset=%s submitted=%.5f actual=%.5f",
                        ticket,
                        asset,
                        sub_sl,
                        actual_sl,
                    )
                if not tp_match:
                    logger.error(
                        "SLTP_VERIFY_TP_MISMATCH: ticket=%s asset=%s submitted=%.5f actual=%.5f",
                        ticket,
                        asset,
                        sub_tp,
                        actual_tp,
                    )
                return sl_match and tp_match

        # Position not found in broker positions — not a verification failure.
        # The position may have been closed by MT5-native SL/TP between
        # modify and read-back. The retcode already confirmed success;
        # a missing position is a separate concern handled by orphan
        # reconciliation (Phase B). Log a warning and return True so
        # the caller considers the modification successful.
        logger.warning(
            "SLTP_VERIFY: position ticket=%s asset=%s not found after modify "
            "— likely closed by MT5-native SL/TP or manual intervention",
            ticket,
            asset,
        )
        return True

    def modify_position(self, asset: str, position_id: str, sl: float | None = None, tp: float | None = None) -> bool:
        self.ensure_connected()
        ticket = int(position_id)
        self._wal_event(
            "mt5_order_modified",
            {
                "asset": asset,
                "ticket": str(ticket),
                "sl": sl,
                "tp": tp,
            },
        )
        result = self._client.modify_position(ticket, sl=sl, tp=tp)
        retcode = result.get("result", {}).get("retcode", -1)
        if retcode != 10009:
            logger.error("Modify position failed: retcode=%d ticket=%s asset=%s", retcode, ticket, asset)
            return False

        # Read-back verification: confirm the broker actually applied our SL/TP
        if not self._verify_sltp_applied(ticket, asset, sl, tp):
            logger.error(
                "Modify position VERIFICATION FAILED for ticket=%s asset=%s sl=%s tp=%s "
                "— retcode=%d reported success but broker SL/TP differs",
                ticket,
                asset,
                sl,
                tp,
                retcode,
            )
            return False

        logger.info(
            "Position modified and verified: ticket=%s asset=%s sl=%s tp=%s",
            ticket,
            asset,
            sl,
            tp,
        )
        return True

    def get_deal_by_ticket(self, ticket: int) -> dict | None:
        """Look up a deal in MT5 history by ticket number.

        Returns the deal dict if the ticket was ever filled on the broker,
        or None if no deal exists for this ticket (order never filled).
        """
        self.ensure_connected()
        try:
            return self._client.get_deal_by_ticket(ticket)
        except (OSError, TypeError, ValueError, KeyError) as e:
            logger.error("get_deal_by_ticket failed for ticket=%s: %s", ticket, e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        logger.warning("cancel_order not implemented for MT5")
        return False

    def get_order_status(self, order_id: str) -> str:
        return "filled"

    # ── Positions ──────────────────────────────────────────────────────

    def ticker_to_mt5_symbol(self, ticker: str) -> str:
        return self._symbol_map.get(ticker, ticker)

    def get_positions(self) -> list[Position]:
        self.ensure_connected()
        now = time.monotonic()
        with self._cache_lock:
            if now - self._position_cache_time < _POSITION_CACHE_TTL and self._position_cache:
                return self._position_cache

        try:
            raw = self._client.get_positions()
        except (OSError, TypeError, ValueError, KeyError, MT5ConnectionError) as e:
            logger.error("Failed to fetch positions: %s", e)
            with self._cache_lock:
                return list(self._position_cache) if self._position_cache else []

        positions: list[Position] = []
        for p in raw:
            side = "buy" if p.get("type") == "buy" else "sell"
            quantity = self._lots_to_quantity(p.get("symbol", ""), p.get("volume", 0))
            pos = Position(
                asset=p.get("symbol", ""),
                quantity=quantity if side == "buy" else -quantity,
                avg_entry_price=float(p.get("price_open", 0)),
                current_price=float(p.get("price_current", 0)),
                unrealized_pnl=float(p.get("profit", 0)),
                realized_pnl=0.0,
                position_id=str(p.get("ticket", "")),
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
        return {a: (p if p is not None else 0.0) for a, p in results.items()}

    # ── Lot / Quantity conversion ──────────────────────────────────────

    def min_viable_qty(self, ticker: str) -> float:
        """Return the minimum viable quantity for a symbol (in base-currency units).

        Returns 0.0 if symbol_info is unavailable.
        For standard forex: min_volume=0.01 lots × contract_size=100,000 = 1,000 base units.
        For GC=F: min_volume=0.01 lots × contract_size=100 = 1 troy ounce.
        """
        info = self._client.symbol_info(ticker)
        if not info:
            return 0.0
        contract_size = info.get("contract_size", 100000.0)
        min_vol = info.get("min_volume", 0.01)
        return min_vol * contract_size

    def normalize_volume(self, ticker: str, raw_qty: float) -> float:
        """Normalize qty to broker volume constraints.

        Converts raw_qty (in base currency / contract-equivalent units)
        to lots, rounds DOWN to the symbol's volume_step, then converts
        back to original units. Returns 0.0 if the normalized volume
        rounds to zero or falls below broker min_volume.

        This is the single shared choke point for volume normalization.
        All MT5 order paths must call this before submitting to the
        broker.
        """
        info = self._client.symbol_info(ticker)
        if not info:
            logger.warning(
                "%s: no symbol_info available — can't normalize qty=%.6f, returning as-is",
                ticker,
                raw_qty,
            )
            return raw_qty

        contract_size = info.get("contract_size", 100000.0)
        step = info.get("volume_step", 0.01)
        min_vol = info.get("min_volume", 0.01)
        max_vol = info.get("max_volume", 100.0)

        lots = raw_qty / contract_size
        # Round DOWN — never submit more risk than sized
        lots = int(lots / step) * step

        if lots < min_vol or lots <= 0:
            logger.warning(
                "%s: qty=%.6f normalizes to lots=%.4f — below broker min_volume=%.2f (step=%.4f, contract_size=%.0f)",
                ticker,
                raw_qty,
                lots,
                min_vol,
                step,
                contract_size,
            )
            self._wal_event(
                "mt5_order_rejected",
                {
                    "asset": ticker,
                    "side": "unknown",
                    "reason": f"volume_too_small:qty={raw_qty:.6f},lots={lots:.4f}<min={min_vol}",
                },
            )
            return 0.0

        lots = min(lots, max_vol)
        normalized = lots * contract_size
        logger.debug(
            "%s: volume normalized qty=%.6f -> lots=%.4f (step=%.4f, min=%.2f, max=%.2f)",
            ticker,
            raw_qty,
            lots,
            step,
            min_vol,
            max_vol,
        )
        return normalized

    def _quantity_to_lots(self, asset: str, quantity: float) -> float:
        """Convert quantity to lots using floor rounding — consistent with normalize_volume."""
        info = self._client.symbol_info(asset)
        if info:
            contract_size = info.get("contract_size", 100000.0)
            step = info.get("volume_step", 0.01)
            broker_min = info.get("min_volume", 0.01)
            max_vol = info.get("max_volume", 100.0)
            lots = quantity / contract_size
            lots = int(lots / step) * step
            if lots < broker_min or lots <= 0:
                return 0.0
            return min(lots, max_vol)
        return quantity

    def _lots_to_quantity(self, mt5_symbol: str, lots: float) -> float:
        info = self._client.symbol_info(mt5_symbol)
        if info:
            return lots * info.get("contract_size", 100000.0)
        return lots * 100000.0
