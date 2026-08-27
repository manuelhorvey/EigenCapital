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

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


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
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from MT5."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected."""
        pass

    @abstractmethod
    def account_info(self) -> AccountInfo | None:
        """Get account information."""
        pass

    @abstractmethod
    def positions_get(self, ticket: int | None = None) -> List[PositionInfo]:
        """Get open positions. Optionally filter by ticket."""
        pass

    @abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        """Get symbol information."""
        pass

    @abstractmethod
    def symbol_info_tick(self, symbol: str) -> TickInfo | None:
        """Get current tick for a symbol."""
        pass

    @abstractmethod
    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        """Select/deselect a symbol in Market Watch."""
        pass

    @abstractmethod
    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> List[Dict[str, Any]] | None:
        """Copy rates from position. Timeframe constants provided by implementation."""
        pass

    @abstractmethod
    def order_send(self, request: OrderRequest) -> OrderResult:
        """Submit an order."""
        pass

    @abstractmethod
    def last_error(self) -> str:
        """Get last error message."""
        pass

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


class LinuxMT5Provider(TradingProvider):
    """MT5 provider using mt5linux (RPyC bridge to Wine)."""

    def __init__(self) -> None:
        self._mt5 = None
        self._connected = False

    def connect(self, host: str = "127.0.0.1", port: int = 8001) -> bool:
        try:
            from mt5linux import MetaTrader5

            self._mt5 = MetaTrader5(host=host, port=port)
            self._connected = self._mt5.initialize()
            return self._connected
        except Exception:
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._mt5:
            self._mt5.shutdown()
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

        from mt5linux import MetaTrader5

        filling_map = {
            "FOK": MetaTrader5.ORDER_FILLING_FOK,
            "IOC": MetaTrader5.ORDER_FILLING_IOC,
            "RETURN": MetaTrader5.ORDER_FILLING_RETURN,
        }
        side_map = {
            "BUY": MetaTrader5.ORDER_TYPE_BUY,
            "SELL": MetaTrader5.ORDER_TYPE_SELL,
        }

        mt5_request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": request.volume,
            "type": side_map.get(request.side, MetaTrader5.ORDER_TYPE_BUY),
            "price": request.price,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": filling_map.get(request.filling_mode, MetaTrader5.ORDER_FILLING_FOK),
        }
        if request.sl > 0:
            mt5_request["sl"] = request.sl
        if request.tp > 0:
            mt5_request["tp"] = request.tp

        result = self._mt5.order_send(mt5_request)
        if result is None:
            return OrderResult(success=False, comment="order_send returned None")

        return OrderResult(
            success=result.retcode == MetaTrader5.TRADE_RETCODE_DONE,
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

    # Expose MT5 constants from the underlying library
    @property
    def TIMEFRAME_D1(self) -> int:
        if self._mt5:
            return self._mt5.TIMEFRAME_D1
        return 1440

    @property
    def TRADE_RETCODE_DONE(self) -> int:
        if self._mt5:
            return self._mt5.TRADE_RETCODE_DONE
        return 10009


class WindowsMT5Provider(TradingProvider):
    """MT5 provider using the official MetaTrader5 Python package.

    The official package only runs on Windows.
    Import will fail on Linux — this is expected.
    """

    def __init__(self) -> None:
        self._mt5 = None
        self._connected = False

    def connect(self, host: str = "127.0.0.1", port: int = 8001) -> bool:
        try:
            import MetaTrader5 as mt5

            self._mt5 = mt5
            self._connected = mt5.initialize()
            return self._connected
        except ImportError:
            return False
        except Exception:
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._mt5:
            self._mt5.shutdown()
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

        import MetaTrader5 as mt5

        filling_map = {
            "FOK": mt5.ORDER_FILLING_FOK,
            "IOC": mt5.ORDER_FILLING_IOC,
            "RETURN": mt5.ORDER_FILLING_RETURN,
        }
        side_map = {
            "BUY": mt5.ORDER_TYPE_BUY,
            "SELL": mt5.ORDER_TYPE_SELL,
        }

        mt5_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": request.volume,
            "type": side_map.get(request.side, mt5.ORDER_TYPE_BUY),
            "price": request.price,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_map.get(request.filling_mode, mt5.ORDER_FILLING_FOK),
        }
        if request.sl > 0:
            mt5_request["sl"] = request.sl
        if request.tp > 0:
            mt5_request["tp"] = request.tp

        result = self._mt5.order_send(mt5_request)
        if result is None:
            return OrderResult(success=False, comment="order_send returned None")

        return OrderResult(
            success=result.retcode == mt5.TRADE_RETCODE_DONE,
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

    @property
    def TIMEFRAME_D1(self) -> int:
        if self._mt5:
            return self._mt5.TIMEFRAME_D1
        return 1440

    @property
    def TRADE_RETCODE_DONE(self) -> int:
        if self._mt5:
            return self._mt5.TRADE_RETCODE_DONE
        return 10009


def create_trading_provider() -> TradingProvider:
    """Factory: create the appropriate MT5 provider for the current platform.

    On Linux: tries mt5linux first
    On Windows: tries official MetaTrader5 package
    Falls back gracefully.
    """
    system = platform.system()

    if system == "Linux":
        # Try mt5linux first
        try:
            provider = LinuxMT5Provider()
            return provider
        except Exception:
            pass
    elif system == "Windows":
        # Try official package
        try:
            provider = WindowsMT5Provider()
            return provider
        except Exception:
            pass

    # Fallback: try both
    try:
        provider = LinuxMT5Provider()
        return provider
    except Exception:
        pass

    try:
        provider = WindowsMT5Provider()
        return provider
    except Exception:
        pass

    raise RuntimeError(
        f"No MT5 provider available for platform '{system}'. Install mt5linux (Linux) or MetaTrader5 (Windows)."
    )
