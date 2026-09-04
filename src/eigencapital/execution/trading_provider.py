"""Trading Provider — platform-agnostic MT5 interface.

Provides a unified interface for MT5 operations regardless of:
- Linux (mt5linux via Wine bridge)
- Windows (official MetaTrader5 Python package)

Strategy, risk, and execution code must depend on TradingProvider,
never on platform-specific MT5 modules.

Capability matrix:
  Capability        | Windows | Linux
  ------------------|---------|--------
  connect           | req     | req
  account_info      | req     | req
  positions_get     | req     | req
  order_send        | req     | req
  symbol_info       | req     | req
  symbol_info_tick  | req     | req
  copy_rates_from   | req     | req
  shutdown          | req     | req
  health_check      | req     | req
"""

from __future__ import annotations

import logging
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderFillingMode(str, Enum):
    FOK = "FOK"
    IOC = "IOC"
    RETURN = "RETURN"


@dataclass(frozen=True)
class AccountInfo:
    """Platform-agnostic account information."""

    login: int = 0
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    leverage: int = 0
    currency: str = "USD"
    profit: float = 0.0
    server: str = ""
    name: str = ""


@dataclass(frozen=True)
class PositionInfo:
    """Platform-agnostic position information."""

    ticket: int = 0
    symbol: str = ""
    side: str = "BUY"  # "BUY" or "SELL"
    volume: float = 0.0
    price_open: float = 0.0
    price_current: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    magic: int = 0
    comment: str = ""
    type_raw: int = 0  # 0=BUY, 1=SELL (MT5 native)


@dataclass(frozen=True)
class TickInfo:
    """Platform-agnostic tick information."""

    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: float = 0.0
    time: int = 0


@dataclass(frozen=True)
class SymbolInfo:
    """Platform-agnostic symbol information."""

    symbol: str = ""
    bid: float = 0.0
    ask: float = 0.0
    spread: int = 0
    digits: int = 0
    point: float = 0.0
    trade_contract_size: float = 0.0
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0


@dataclass(frozen=True)
class OrderRequest:
    """Platform-agnostic order request."""

    symbol: str
    side: str  # "BUY" or "SELL"
    volume: float
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    deviation: int = 10
    magic: int = 0
    comment: str = ""
    filling_mode: str = "FOK"


@dataclass(frozen=True)
class OrderResult:
    """Platform-agnostic order result."""

    success: bool = False
    order: int = 0
    deal: int = 0
    retcode: int = 0
    comment: str = ""
    price: float = 0.0
    volume: float = 0.0


@dataclass(frozen=True)
class BarData:
    """Platform-agnostic bar data."""

    time: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    tick_volume: float = 0.0
    volume: float = 0.0


class TradingProvider(ABC):
    """Abstract trading provider — platform-agnostic MT5 interface.

    All live trading code must depend on this interface, not on
    mt5linux or MetaTrader5 directly.
    """

    @abstractmethod
    def connect(self, host: str = "127.0.0.1", port: int = 8001) -> bool:
        """Connect to MT5. Returns True on success."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from MT5."""
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected."""
        raise NotImplementedError

    @abstractmethod
    def account_info(self) -> AccountInfo | None:
        """Get account information."""
        raise NotImplementedError

    @abstractmethod
    def positions_get(self, ticket: int | None = None) -> List[PositionInfo]:
        """Get open positions. Optionally filter by ticket."""
        raise NotImplementedError

    @abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        """Get symbol information."""
        raise NotImplementedError

    @abstractmethod
    def symbol_info_tick(self, symbol: str) -> TickInfo | None:
        """Get current tick for a symbol."""
        raise NotImplementedError

    @abstractmethod
    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        """Select/deselect a symbol in Market Watch."""
        raise NotImplementedError

    @abstractmethod
    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> List[Dict[str, Any]] | None:
        """Copy rates from position. Timeframe constants provided by implementation."""
        raise NotImplementedError

    @abstractmethod
    def order_send(self, request: OrderRequest) -> OrderResult:
        """Submit an order."""
        raise NotImplementedError

    @abstractmethod
    def last_error(self) -> str:
        """Get last error message."""
        raise NotImplementedError

    # Timeframe constants (subclasses may override)
    TIMEFRAME_D1: int = 1440
    TIMEFRAME_H1: int = 60
    TIMEFRAME_M15: int = 15
    TIMEFRAME_M5: int = 5
    TIMEFRAME_M1: int = 1

    # Order type constants
    ORDER_TYPE_BUY: int = 0
    ORDER_TYPE_SELL: int = 1
    TRADE_ACTION_DEAL: int = 1
    ORDER_TIME_GTC: int = 0
    TRADE_RETCODE_DONE: int = 10009


class MT5BaseProvider(TradingProvider):
    """Shared MT5 implementation for Linux and Windows providers.

    The Linux and Windows bindings expose the same API surface, so the
    entire data-access implementation is shared here. Concrete subclasses
    only differ in how they obtain the underlying ``_mt5`` binding inside
    :meth:`_load_mt5`; everything else goes through the injected object.
    """

    def __init__(self) -> None:
        self._mt5: Any = None
        self._connected = False

    @abstractmethod
    def _load_mt5(self, host: str, port: int) -> Any:
        """Import/instantiate the platform-specific MT5 binding.

        Raises ImportError if the binding is unavailable on this platform.
        """

    def connect(self, host: str = "127.0.0.1", port: int = 8001) -> bool:
        try:
            self._mt5 = self._load_mt5(host, port)
            self._connected = bool(self._mt5.initialize())
            if self._connected:
                # Resolve platform-specific constants into instance attributes
                # (mirrors the read-only property behavior without the
                # property-overrides-class-attribute conflict).
                self.TIMEFRAME_D1 = int(getattr(self._mt5, "TIMEFRAME_D1", TradingProvider.TIMEFRAME_D1))
                self.TRADE_RETCODE_DONE = int(
                    getattr(self._mt5, "TRADE_RETCODE_DONE", TradingProvider.TRADE_RETCODE_DONE)
                )
            return self._connected
        except ImportError:
            logger.debug("MT5 binding not available on this platform")
            self._connected = False
            return False
        except Exception as e:
            logger.debug("MT5 connect failed: %s", e)
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._mt5:
            try:
                self._mt5.shutdown()
            except Exception as e:
                logger.debug("MT5 shutdown failed: %s", e)
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def account_info(self) -> AccountInfo | None:
        if not self._connected or self._mt5 is None:
            return None
        info = self._mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            login=info.login,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            leverage=info.leverage,
            currency=info.currency,
            profit=info.profit,
            server=getattr(info, "server", ""),
            name=getattr(info, "name", ""),
        )

    def positions_get(self, ticket: int | None = None) -> List[PositionInfo]:
        if not self._connected or self._mt5 is None:
            return []
        positions = self._mt5.positions_get(ticket=ticket) if ticket else self._mt5.positions_get()
        if positions is None:
            return []
        return [
            PositionInfo(
                ticket=p.ticket,
                symbol=p.symbol,
                side="BUY" if p.type == 0 else "SELL",
                volume=p.volume,
                price_open=p.price_open,
                price_current=p.price_current,
                sl=p.sl,
                tp=p.tp,
                profit=p.profit,
                swap=p.swap,
                magic=p.magic,
                comment=p.comment,
                type_raw=p.type,
            )
            for p in positions
        ]

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        if not self._connected or self._mt5 is None:
            return None
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return None
        return SymbolInfo(
            symbol=info.symbol,
            bid=info.bid,
            ask=info.ask,
            spread=info.spread,
            digits=info.digits,
            point=info.point,
            trade_contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
        )

    def symbol_info_tick(self, symbol: str) -> TickInfo | None:
        if not self._connected or self._mt5 is None:
            return None
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return TickInfo(
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            volume=tick.volume,
            time=tick.time,
        )

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        if not self._connected or self._mt5 is None:
            return False
        return self._mt5.symbol_select(symbol, enable)

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> List[Dict[str, Any]] | None:
        if not self._connected or self._mt5 is None:
            return None
        rates = self._mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
        if rates is None:
            return None
        return [dict(r) for r in rates]

    def order_send(self, request: OrderRequest) -> OrderResult:
        if not self._connected or self._mt5 is None:
            return OrderResult(success=False, comment="Not connected")

        filling_map = {
            "FOK": getattr(self._mt5, "ORDER_FILLING_FOK", 0),
            "IOC": getattr(self._mt5, "ORDER_FILLING_IOC", 0),
            "RETURN": getattr(self._mt5, "ORDER_FILLING_RETURN", 0),
        }
        side_map = {
            "BUY": getattr(self._mt5, "ORDER_TYPE_BUY", self.ORDER_TYPE_BUY),
            "SELL": getattr(self._mt5, "ORDER_TYPE_SELL", self.ORDER_TYPE_SELL),
        }

        mt5_request: Dict[str, Any] = {
            "action": getattr(self._mt5, "TRADE_ACTION_DEAL", self.TRADE_ACTION_DEAL),
            "symbol": request.symbol,
            "volume": request.volume,
            "type": side_map.get(request.side, self.ORDER_TYPE_BUY),
            "price": request.price,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": getattr(self._mt5, "ORDER_TIME_GTC", self.ORDER_TIME_GTC),
            "type_filling": filling_map.get(request.filling_mode, filling_map["FOK"]),
        }
        if request.sl > 0:
            mt5_request["sl"] = request.sl
        if request.tp > 0:
            mt5_request["tp"] = request.tp

        result = self._mt5.order_send(mt5_request)
        if result is None:
            return OrderResult(success=False, comment="order_send returned None")

        return OrderResult(
            success=result.retcode == getattr(self._mt5, "TRADE_RETCODE_DONE", self.TRADE_RETCODE_DONE),
            order=result.order,
            deal=result.deal,
            retcode=result.retcode,
            comment=result.comment,
            price=result.price,
            volume=result.volume,
        )

    def last_error(self) -> str:
        if self._mt5 is None:
            return "MT5 not initialized"
        return str(self._mt5.last_error())


class LinuxMT5Provider(MT5BaseProvider):
    """MT5 provider using mt5linux (RPyC bridge to Wine)."""

    def _load_mt5(self, host: str, port: int) -> Any:
        from mt5linux import MetaTrader5

        return MetaTrader5(host=host, port=port)


class WindowsMT5Provider(MT5BaseProvider):
    """MT5 provider using the official MetaTrader5 Python package.

    The official package only runs on Windows.
    Import will fail on Linux — this is expected.
    """

    def _load_mt5(self, host: str, port: int) -> Any:
        import MetaTrader5 as mt5

        return mt5


def create_trading_provider() -> TradingProvider:
    """Factory: create the appropriate MT5 provider for the current platform.

    Provider construction never fails — the platform-specific imports are
    deferred to connect(), which reports success/failure and returns False
    (never raises) when the binding is unavailable. No fallback chain is
    needed here.
    """
    system = platform.system()
    if system == "Windows":
        return WindowsMT5Provider()
    return LinuxMT5Provider()
