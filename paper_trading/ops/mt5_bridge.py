"""MT5 Bridge Server — runs under Python (Wine on Linux, native on Windows).

Connects to the MT5 terminal, listens on a local TCP socket, and
executes MetaTrader5 operations on behalf of the host EigenCapital process.

Protocol: JSON-RPC over TCP with 4-byte length-prefixed frames.
Each frame: [4-byte big-endian payload length][UTF-8 JSON payload].

Request:  {"id": 1, "method": "...", "params": {}}
Response: {"id": 1, "result": ...}  or  {"id": 1, "error": "..."}

Credentials are supplied to the bridge via environment variables
(MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER).  The TCP protocol never
transmits the MT5 password — it would be cleartext.

Supports:
  - fetch_ohlcv     (symbol, years, timeframe)
  - fetch_ticks     (symbol, from_timestamp, to_timestamp)
  - realtime_price  (symbol)
  - symbol_info     (symbol)
  - place_order     (symbol, side, volume, sl, tp, comment)
  - get_positions   ()
  - get_account     ()
  - modify_position (ticket, sl, tp)
  - close_position  (ticket)
  - get_deal        (ticket)
  - heartbeat       ()
  - shutdown        ()
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import struct
import threading
import time
from datetime import datetime
from typing import Any

import MetaTrader5 as mt5  # noqa: N813

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MT5-BRIDGE] %(levelname)s %(message)s",
)
logger = logging.getLogger("mt5_bridge")

HOST = "127.0.0.1"
PORT = int(os.environ.get("MT5_BRIDGE_PORT") or 9879)

# Credentials: supplied via MT5_PASSWORD env var only (never CLI args)
# to prevent password exposure via `ps aux`.

# Frame format: 4-byte big-endian length prefix + JSON payload
_HEADER_FMT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_MAX_PAYLOAD = 4 * 1024 * 1024  # 4 MiB max request/response body

_config: dict[str, Any] = {}
_running = threading.Event()
_placed_orders: dict[str, tuple[int, float]] = {}  # dedup_key -> (order_id, timestamp)
_PLACED_ORDERS_TTL = 86400.0  # 1 day TTL for dedup cache entries


def _send_frame(conn: socket.socket, data: dict) -> None:
    payload = json.dumps(data, cls=EigenCapitalJSONEncoder).encode("utf-8")
    conn.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)


def _recv_exactly(conn: socket.socket, n: int) -> bytes | None:
    """Read exactly *n* bytes from *conn*, looping until complete."""
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_frame(conn: socket.socket) -> dict | None:
    header = _recv_exactly(conn, _HEADER_SIZE)
    if header is None:
        return None
    size = struct.unpack(_HEADER_FMT, header)[0]
    if size > _MAX_PAYLOAD:
        logger.error("Request payload %d exceeds max %d", size, _MAX_PAYLOAD)
        return None
    payload = _recv_exactly(conn, size)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


def _ensure_initialized() -> bool:
    global _config
    if mt5.terminal_info() is not None:
        return True
    logger.info("Initializing MT5...")
    if not mt5.initialize():
        logger.error("initialize() failed: %s", mt5.last_error())
        return False
    account = _config.get("account")
    password = _config.get("password")
    server = _config.get("server")
    if account and password and server:
        if not mt5.login(account, password, server):
            logger.error("login() failed: %s", mt5.last_error())
            return False
        logger.info("Logged in to %s as account %d", server, account)
    return True


# ── Frame handlers ────────────────────────────────────────────────────────────


def _handle_fetch_ohlcv(params: dict) -> dict:
    symbol = params["symbol"]
    years = params.get("years", 2)
    from_date = datetime.now() - __import__("datetime").timedelta(days=years * 365)
    to_date = datetime.now()
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, from_date, to_date)
    if rates is None:
        return {"error": f"No data for {symbol}: {mt5.last_error()}"}
    result = []
    for r in rates:
        result.append(
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
            }
        )
    return {"result": result}


def _handle_fetch_ticks(params: dict) -> dict:
    symbol = params["symbol"]
    from_ts = params.get("from", int(time.time()) - 86400)
    to_ts = params.get("to", int(time.time()))
    ticks = mt5.copy_ticks_range(symbol, from_ts, to_ts, mt5.COPY_TICKS_ALL)
    if ticks is None:
        return {"error": f"No ticks for {symbol}: {mt5.last_error()}"}
    result = []
    for t in ticks:
        result.append(
            {
                "time": int(t["time"]),
                "bid": float(t["bid"]),
                "ask": float(t["ask"]),
                "last": float(t["last"]) if t["last"] else None,
                "volume": int(t["volume"]),
                "flags": int(t["flags"]),
            }
        )
    return {"result": result}


def _handle_realtime_price(params: dict) -> dict:
    symbol = params["symbol"]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        for _ in range(10):
            time.sleep(0.1)
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                break
    if tick is None:
        return {"error": f"No tick for {symbol}"}
    return {
        "result": {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "last": float(tick.last) if tick.last else None,
            "spread": int(getattr(tick, "spread", 0)),
            "time": tick.time,
        }
    }


def _handle_symbol_info(params: dict) -> dict:
    symbol = params["symbol"]
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"Symbol {symbol} not found"}
    return {
        "result": {
            "name": info.name,
            "digits": info.digits,
            "point": float(info.point),
            "trade_mode": info.trade_mode,
            "trade_exec_mode": getattr(info, "trade_exec_mode", info.trade_exemode),
            "contract_size": info.trade_contract_size,
            "min_volume": info.volume_min,
            "max_volume": info.volume_max,
            "volume_step": info.volume_step,
        }
    }


def _handle_place_order(params: dict) -> dict:
    symbol = params["symbol"]
    side = params.get("side", "")
    id_key = params.get("idempotency_key")
    if id_key:
        dedup_key = f"{symbol}_{side}_{id_key}"
        entry = _placed_orders.get(dedup_key)
        if entry is not None:
            ticket, ts = entry
            if time.monotonic() - ts < _PLACED_ORDERS_TTL:
                logger.info("Dedup: order %s already placed (ticket=%s)", dedup_key, ticket)
                return {"result": {"retcode": 10009, "ticket": ticket, "dedup": True}}
            # expired — remove and allow re-placement
            del _placed_orders[dedup_key]
    volume = params["volume"]
    sl = params.get("sl", 0.0)
    tp = params.get("tp", 0.0)
    comment = params.get("comment", "EigenCapital")
    deviation = params.get("deviation", 20)

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        for _ in range(10):
            time.sleep(0.1)
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                break
    if tick is None:
        return {"error": f"No tick for {symbol} to place order"}

    price = tick.ask if side == "buy" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": 202406,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return {"error": f"order_send failed: {mt5.last_error()}"}

    if id_key:
        _placed_orders[dedup_key] = (result.order, time.monotonic())

    return {
        "result": {
            "retcode": result.retcode,
            "ticket": result.order,
            "volume": float(result.volume),
            "price": float(result.price),
            "comment": result.comment,
        }
    }


def _handle_get_positions(params: dict) -> dict:
    positions = mt5.positions_get()
    if positions is None:
        return {"result": []}
    result = []
    for p in positions:
        result.append(
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == mt5.ORDER_TYPE_BUY else "sell",
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl) if p.sl else None,
                "tp": float(p.tp) if p.tp else None,
                "price_current": float(p.price_current),
                "profit": float(p.profit),
                "swap": float(p.swap),
                "commission": float(getattr(p, "commission", 0.0)),
                "time": p.time,
                "comment": p.comment,
            }
        )
    return {"result": result}


def _handle_get_account(params: dict) -> dict:
    info = mt5.account_info()
    if info is None:
        return {"error": "account_info failed"}
    return {
        "result": {
            "login": info.login,
            "server": info.server,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(info.margin),
            "margin_free": float(info.margin_free),
            "margin_level": float(info.margin_level) if info.margin_level else None,
            "currency": info.currency,
            "leverage": info.leverage,
            "name": info.name,
        }
    }


def _handle_modify_position(params: dict) -> dict:
    ticket = params["ticket"]
    sl = params.get("sl")
    tp = params.get("tp")

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"error": f"Position {ticket} not found"}

    pos = positions[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": pos.symbol,
        "sl": sl if sl is not None else pos.sl,
        "tp": tp if tp is not None else pos.tp,
        "volume": pos.volume,
        "type": pos.type,
        "price": pos.price_open,
        "deviation": 20,
        "magic": 202406,
        "comment": "EigenCapital mod",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return {"error": f"modify failed: {mt5.last_error()}"}
    return {"result": {"retcode": result.retcode, "ticket": ticket}}


def _handle_close_position(params: dict) -> dict:
    ticket = params["ticket"]

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"error": f"Position {ticket} not found"}

    pos = positions[0]
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        for _ in range(10):
            time.sleep(0.1)
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is not None:
                break
    if tick is None:
        return {"error": f"No tick for {pos.symbol} to close position"}

    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 202406,
        "comment": "EigenCapital close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return {"error": f"close failed: {mt5.last_error()}"}
    return {"result": {"retcode": result.retcode, "ticket": ticket}}


def _handle_get_deal(params: dict) -> dict:
    """Look up a deal in MT5 history by ticket.  Returns deal dict or null if not found."""
    ticket = params["ticket"]
    mt5.history_select(datetime(2000, 1, 1), datetime.now())
    deals = mt5.history_deals_get(ticket=ticket)
    if deals is None or len(deals) == 0:
        return {"result": None}
    d = deals[0]
    return {
        "result": {
            "ticket": d.ticket,
            "order": d.order,
            "symbol": d.symbol,
            "type": d.type,
            "volume": float(d.volume),
            "price": float(d.price),
            "profit": float(d.profit),
            "commission": float(getattr(d, "commission", 0.0)),
            "swap": float(getattr(d, "swap", 0.0)),
            "time": d.time,
            "comment": d.comment,
        }
    }


def _handle_heartbeat(params: dict) -> dict:
    return {"result": {"status": "alive", "time": time.time()}}


# ── Dispatch ──────────────────────────────────────────────────────────────────

_HANDLERS = {
    "fetch_ohlcv": _handle_fetch_ohlcv,
    "fetch_ticks": _handle_fetch_ticks,
    "realtime_price": _handle_realtime_price,
    "symbol_info": _handle_symbol_info,
    "place_order": _handle_place_order,
    "get_positions": _handle_get_positions,
    "get_account": _handle_get_account,
    "modify_position": _handle_modify_position,
    "close_position": _handle_close_position,
    "get_deal": _handle_get_deal,
    "heartbeat": _handle_heartbeat,
}


def _dispatch(method: str, params: dict, conn: socket.socket) -> dict:
    if method == "shutdown":
        _running.clear()
        return {"result": "shutting down"}
    if method == "configure":
        global _config
        # Credentials are supplied via CLI args (--password) or env vars;
        # the TCP protocol never transmits the password — it would be
        # cleartext.  Ignore password if sent (backward compat).
        params.pop("password", None)
        _config.update(params)
        return {"result": "configured"}
    handler = _HANDLERS.get(method)
    if handler is None:
        return {"error": f"Unknown method: {method}"}
    if not _ensure_initialized():
        return {"error": "MT5 not initialized"}

    if "symbol" in params:
        symbol = params["symbol"]
        info = mt5.symbol_info(symbol)
        if info is None:
            return {"error": f"Symbol {symbol} not found on server"}
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                logger.error("Failed to select symbol %s in Market Watch: %s", symbol, mt5.last_error())
                return {"error": f"Failed to select symbol {symbol} in Market Watch"}
            logger.info("Automatically selected/added symbol %s to Market Watch", symbol)

    try:
        return handler(params)
    except (OSError, ValueError, TypeError, KeyError, ConnectionError) as e:
        logger.exception("Handler error for %s", method)
        return {"error": str(e)}


def _handle_client(conn: socket.socket) -> None:
    try:
        while _running.is_set():
            req = _recv_frame(conn)
            if req is None:
                break
            req_id = req.get("id", 0)
            method = req.get("method", "")
            params = req.get("params", {})
            resp = _dispatch(method, params, conn)
            resp["id"] = req_id
            _send_frame(conn, resp)
    except ConnectionResetError:
        pass
    except (OSError, ConnectionError, ValueError, json.JSONDecodeError) as e:
        logger.warning("Client error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def main() -> None:
    global _config

    # Read credentials from environment variables ONLY.
    # CLI --password is intentionally not supported — it would be visible
    # in `ps aux` to any user on the system.
    _config["password"] = os.environ.get("MT5_PASSWORD", "")
    _config["account"] = int(os.environ.get("MT5_ACCOUNT", "0"))
    _config["server"] = os.environ.get("MT5_SERVER", "")

    _running.set()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    server.settimeout(1.0)
    logger.info("MT5 Bridge listening on %s:%d", HOST, PORT)
    logger.info(
        "Config: account=%s server=%s",
        _config.get("account", "?"),
        _config.get("server", "?"),
    )

    try:
        while _running.is_set():
            try:
                conn, addr = server.accept()
                logger.debug("Connection from %s", addr)
                threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
            except TimeoutError:
                continue
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        _running.clear()
        server.close()
        mt5.shutdown()
        logger.info("Bridge stopped")


if __name__ == "__main__":
    main()
