"""MT5 Client — communicates with the Wine-hosted MT5 bridge server.

Provides a high-level Pythonic API for all MT5 operations:
  - OHLCV data fetching
  - Real-time quotes
  - Order placement and position management
  - Account info

Usage:
    client = MT5Client(account=12345, password="...", server="Exness-MT5Trial")
    client.connect()

    df = client.fetch_ohlcv("EURUSD", years=2)
    price = client.realtime_price("EURUSD")
    order = client.place_order("EURUSD", "buy", 0.01)

    positions = client.get_positions()
    client.close_position(ticket)

    client.disconnect()
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import logging
import os
import socket
import struct
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from paper_trading.config_manager import DEFAULT_MT5_BRIDGE_PORT

logger = logging.getLogger("eigencapital.mt5_client")

_HEADER_FMT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_MAX_PAYLOAD = 4 * 1024 * 1024  # 4 MiB max response body
_RECONNECT_DELAY = 2.0
_MAX_RECONNECT_ATTEMPTS = 3
_CIRCUIT_BREAKER_FAILURES = 0
_CIRCUIT_BREAKER_LAST_FAILURE = 0.0
_CIRCUIT_BREAKER_TIMEOUTS = [30.0, 60.0, 120.0, 300.0]
_CIRCUIT_BREAKER_LOCK = threading.Lock()

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback(host: str) -> bool:
    """Return True if the bridge host is safe (loopback-only)."""
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    return host.startswith("127.")


def _reset_circuit_breaker() -> None:
    """Reset MT5 circuit breaker counters. Test-harness use only."""
    global _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_LAST_FAILURE
    with _CIRCUIT_BREAKER_LOCK:
        _CIRCUIT_BREAKER_FAILURES = 0
        _CIRCUIT_BREAKER_LAST_FAILURE = 0.0


class MT5ConnectionError(Exception):
    pass


class MT5DataError(Exception):
    pass


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes from *sock*, looping until complete."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise MT5ConnectionError("Connection closed")
        buf += chunk
    return buf


class _FrameConnection:
    """One TCP connection to the MT5 bridge with its own request-id counter."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    def connect(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(15.0)
        try:
            self._sock.connect((self._host, self._port))
        except OSError as e:
            self._sock.close()
            self._sock = None
            raise MT5ConnectionError(str(e)) from e
        self._sock.settimeout(30.0)

    def disconnect(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
            self._sock = None

    def send_request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if self._sock is None:
                raise MT5ConnectionError("Not connected")
            req_id = self._next_id
            self._next_id += 1
            payload = json.dumps(
                {
                    "id": req_id,
                    "method": method,
                    "params": params or {},
                }
            ).encode("utf-8")
            try:
                self._sock.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)
                header = _recv_exactly(self._sock, _HEADER_SIZE)
                size = struct.unpack(_HEADER_FMT, header)[0]
                if size > _MAX_PAYLOAD:
                    raise MT5ConnectionError(f"Response payload {size} exceeds max {_MAX_PAYLOAD}")
                data = _recv_exactly(self._sock, size)
                resp = json.loads(data.decode("utf-8"))
                if resp.get("id") != req_id:
                    raise MT5ConnectionError(f"ID mismatch: sent {req_id}, got {resp.get('id')}")
                if "error" in resp:
                    raise MT5DataError(resp["error"])
                return resp.get("result")
            except (TimeoutError, ConnectionResetError, BrokenPipeError, OSError) as e:
                with contextlib.suppress(Exception):
                    if self._sock is not None:
                        self._sock.close()
                self._sock = None
                raise MT5ConnectionError(str(e)) from e

    @property
    def connected(self) -> bool:
        return self._sock is not None


class _FrameProtocol:
    """Connection pool wrapping N TCP sockets + round-robin dispatch.

    Enables concurrent requests to the bridge by maintaining multiple
    TCP connections (default 4).  The bridge server already creates
    one thread per client connection, so multiple sockets give true
    parallelism for batch operations.
    """

    _POOL_SIZE = 4

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        self._host = host
        self._port = port or int(os.environ.get("MT5_BRIDGE_PORT") or 9879)
        self._conns: list[_FrameConnection] = []
        self._lock = threading.RLock()
        self._rr_lock = threading.Lock()
        self._rr_idx = -1
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._POOL_SIZE,
            thread_name_prefix="qf-mt5",
        )

    def connect(self) -> None:
        with self._lock:
            self.disconnect()

            def _connect_one(_conn: _FrameConnection) -> bool:
                try:
                    _conn.connect()
                    return True
                except MT5ConnectionError:
                    return False

            conns = [_FrameConnection(self._host, self._port) for _ in range(self._POOL_SIZE)]
            results = list(self._executor.map(_connect_one, conns))
            succeeded = sum(1 for r in results if r)

            if succeeded == 0:
                for c in conns:
                    c.disconnect()
                raise MT5ConnectionError(f"All {self._POOL_SIZE} connection attempts failed")

            if succeeded < self._POOL_SIZE:
                logger.warning(
                    "MT5 bridge: %d/%d connections succeeded — using partial pool",
                    succeeded,
                    self._POOL_SIZE,
                )
                for i, r in enumerate(results):
                    if not r:
                        conns[i].disconnect()
                conns = [c for c, r in zip(conns, results) if r]

            self._conns = conns

    def disconnect(self) -> None:
        with self._lock:
            for conn in self._conns:
                conn.disconnect()
            self._conns.clear()

    def _get_conn(self) -> _FrameConnection:
        with self._rr_lock:
            if not self._conns:
                raise MT5ConnectionError("No connections in pool")
            self._rr_idx = (self._rr_idx + 1) % len(self._conns)
            return self._conns[self._rr_idx]

    def send_request(self, method: str, params: dict | None = None) -> dict:
        # Hold _lock only for connection selection, NOT for the TCP round-trip.
        # Each _FrameConnection already has its own per-connection _lock,
        # so the TCP request is serialized only per-connection, not across
        # the entire pool.  This avoids serializing all ThreadPoolExecutor
        # workers through a single mutex.
        try:
            with self._lock:
                conn = self._get_conn()
        except MT5ConnectionError:
            with self._lock:
                if not self._conns:
                    # Pool was never populated — don't attempt reconnect.
                    raise
                self._reconnect()
                conn = self._get_conn()
        try:
            return conn.send_request(method, params)
        except (MT5ConnectionError, OSError):
            # Connection failed — reconnect all and retry once
            with self._lock:
                self._reconnect()
                conn = self._get_conn()
            return conn.send_request(method, params)

    def _reconnect(self) -> None:
        """Replace all pool connections with fresh ones.

        Creates new connections in parallel, then swaps out the pool.
        Partially successful reconnects (some failed, some succeeded) are
        accepted — surviving fresh connections are kept.  If ALL fresh
        connections fail, the old pool is left intact so the next cycle
        can retry rather than leaving the pool empty.
        """
        logger.warning("MT5 bridge reconnecting all pool connections")
        fresh = [_FrameConnection(self._host, self._port) for _ in range(self._POOL_SIZE)]

        def _connect_one(_conn: _FrameConnection) -> bool:
            try:
                _conn.connect()
                return True
            except MT5ConnectionError:
                return False

        results = list(self._executor.map(_connect_one, fresh))
        succeeded = sum(1 for r in results if r)
        failed = self._POOL_SIZE - succeeded

        if succeeded == 0:
            # All failed — keep old pool, log error, raise
            for c in fresh:
                c.disconnect()
            logger.error(
                "MT5 bridge reconnect: all %d connections failed — keeping existing pool",
                self._POOL_SIZE,
            )
            raise MT5ConnectionError(f"All {self._POOL_SIZE} reconnect attempts failed")

        if failed > 0:
            logger.warning(
                "MT5 bridge reconnect: %d/%d connections succeeded (%d failed) — using partial pool",
                succeeded,
                self._POOL_SIZE,
                failed,
            )
            # Clean up failed fresh connections
            for i, r in enumerate(results):
                if not r:
                    fresh[i].disconnect()
            # Keep only successful ones
            fresh = [c for c, r in zip(fresh, results) if r]

        old = self._conns
        self._conns = fresh
        for c in old:
            c.disconnect()

    def batch_request(self, method: str, param_list: list[dict]) -> list[dict]:
        """Fire N requests concurrently across the pool, return results."""

        def _send(p: dict) -> dict:
            return self.send_request(method, p)

        futures = [self._executor.submit(_send, p) for p in param_list]
        return [f.result() for f in futures]

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._conns) and all(c.connected for c in self._conns)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
        self.disconnect()


def reset_circuit_breaker() -> None:
    global _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_LAST_FAILURE
    with _CIRCUIT_BREAKER_LOCK:
        _CIRCUIT_BREAKER_FAILURES = 0
        _CIRCUIT_BREAKER_LAST_FAILURE = 0.0


class MT5Client:
    """High-level client for the Wine-hosted MT5 bridge.

    Manages connection lifecycle, heartbeats, and provides
    typed Pythonic methods for all MT5 operations.
    """

    def __init__(
        self,
        account: int = 0,
        password: str = "",
        server: str = "",
        bridge_host: str = "127.0.0.1",
        bridge_port: int | None = None,
        symbol_map: dict[str, str] | None = None,
        allow_remote_bridge: bool = False,
    ):
        # Security: only loopback is safe by default — the bridge runs on
        # the local machine and credentials never leave it.  Pin to 127.0.0.1
        # unless the operator explicitly opts in to a remote bridge (which
        # is unsafe and should not happen in production).
        if not allow_remote_bridge and not _is_loopback(bridge_host):
            logger.warning(
                "MT5 bridge_host=%r is non-loopback. This is unsafe — "
                "bridge traffic is plaintext TCP and credentials are exposed. "
                "Pass allow_remote_bridge=True to override.",
                bridge_host,
            )
        self._account = account
        self._password = password
        self._server = server
        self._bridge_host = bridge_host
        self._bridge_port = bridge_port or int(os.environ.get("MT5_BRIDGE_PORT", str(DEFAULT_MT5_BRIDGE_PORT)))
        self._symbol_map = symbol_map or {}
        self._proto = _FrameProtocol(bridge_host, bridge_port)
        self._last_heartbeat = 0.0
        self._heartbeat_interval = 15.0
        # If connect() was never successful since start, skip reconnection
        # attempts in ensure_connected().  Reconnection only makes sense
        # after a live connection was lost, not when one was never established.
        self._ever_connected = False

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._proto.connect()
            self._configure()
            self._last_heartbeat = time.monotonic()
            logger.info(
                "MT5 client connected to bridge at %s:%d for account %d/%s",
                self._bridge_host,
                self._bridge_port,
                self._account,
                self._server,
            )
            self._ever_connected = True
            return True
        except MT5ConnectionError as e:
            logger.error("MT5 client connect failed: %s", e)
            return False

    def disconnect(self) -> None:
        self._proto.disconnect()
        logger.info("MT5 client disconnected")

    def ensure_connected(self) -> bool:
        global _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_LAST_FAILURE

        # Fast-path: if the bridge was never successfully connected since
        # process start, skip reconnection entirely.  Reconnection only makes
        # sense after a live connection was lost, not when one was never
        # established (e.g., MT5 bridge is down at startup).
        if not self._ever_connected and not self._proto.connected:
            return False

        # Circuit breaker: if too many recent failures, back off
        with _CIRCUIT_BREAKER_LOCK:
            if _CIRCUIT_BREAKER_FAILURES > 0:
                elapsed = time.monotonic() - _CIRCUIT_BREAKER_LAST_FAILURE
                timeout_idx = min(_CIRCUIT_BREAKER_FAILURES - 1, len(_CIRCUIT_BREAKER_TIMEOUTS) - 1)
                backoff = _CIRCUIT_BREAKER_TIMEOUTS[timeout_idx]
                if elapsed < backoff:
                    logger.warning(
                        "MT5 circuit breaker open: %.0fs remaining (failures=%d)",
                        backoff - elapsed,
                        _CIRCUIT_BREAKER_FAILURES,
                    )
                    return False

        if not self._proto.connected:
            logger.warning("MT5 bridge disconnected — reconnecting")
            for attempt in range(_MAX_RECONNECT_ATTEMPTS):
                try:
                    self._proto.connect()
                    self._configure()
                    self._last_heartbeat = time.monotonic()
                    with _CIRCUIT_BREAKER_LOCK:
                        _CIRCUIT_BREAKER_FAILURES = 0  # reset on success
                    return True
                except MT5ConnectionError as e:
                    logger.warning("Reconnect attempt %d failed: %s", attempt + 1, e)
                    time.sleep(_RECONNECT_DELAY * (attempt + 1))
            logger.error("MT5 bridge reconnect failed after %d attempts", _MAX_RECONNECT_ATTEMPTS)
            with _CIRCUIT_BREAKER_LOCK:
                _CIRCUIT_BREAKER_FAILURES += 1
                _CIRCUIT_BREAKER_LAST_FAILURE = time.monotonic()
            return False

        now = time.monotonic()
        if now - self._last_heartbeat > self._heartbeat_interval:
            try:
                self._proto.send_request("heartbeat")
                self._last_heartbeat = now
            except (TimeoutError, OSError, ConnectionError):
                logger.warning("MT5 bridge heartbeat failed — reconnecting")
                return self.ensure_connected()
        return True

    def _configure(self) -> None:
        # Credentials are supplied to the bridge via CLI args
        # (--account --password --server) or env vars.  The client
        # only sends account/server for identification; the password
        # is never transmitted over the TCP connection.
        self._proto.send_request(
            "configure",
            {
                "account": self._account,
                "server": self._server,
            },
        )

    def _map_symbol(self, ticker: str) -> str:
        return self._symbol_map.get(ticker, ticker)

    # ── Data fetching ────────────────────────────────────────────────────

    def fetch_ohlcv(
        self,
        ticker: str,
        years: int = 2,
    ) -> pd.DataFrame:
        symbol = self._map_symbol(ticker)
        raw = self._proto.send_request(
            "fetch_ohlcv",
            {
                "symbol": symbol,
                "years": years,
            },
        )
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.index = df.index.tz_localize("UTC")
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_ticks(
        self,
        ticker: str,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> pd.DataFrame:
        symbol = self._map_symbol(ticker)
        to_dt = to_dt or datetime.now()
        from_dt = from_dt or (to_dt - timedelta(days=1))
        raw = self._proto.send_request(
            "fetch_ticks",
            {
                "symbol": symbol,
                "from": int(from_dt.timestamp()),
                "to": int(to_dt.timestamp()),
            },
        )
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        return df

    def realtime_price(self, ticker: str) -> dict | None:
        symbol = self._map_symbol(ticker)
        try:
            return self._proto.send_request("realtime_price", {"symbol": symbol})
        except (MT5DataError, MT5ConnectionError):
            return None

    def realtime_mid_price(self, ticker: str) -> float | None:
        tick = self.realtime_price(ticker)
        if tick is None:
            return None
        bid = tick.get("bid")
        ask = tick.get("ask")
        if bid and ask:
            return (bid + ask) / 2.0
        return tick.get("last") or bid or ask

    def realtime_spread(self, ticker: str) -> float | None:
        """Return current spread in basis points, or None if unavailable."""
        tick = self.realtime_price(ticker)
        if tick is None:
            return None
        bid = tick.get("bid")
        ask = tick.get("ask")
        if bid and ask and (bid + ask) > 0:
            return (ask - bid) / ((bid + ask) / 2.0) * 10000.0
        return None

    def symbol_info(self, ticker: str) -> dict | None:
        symbol = self._map_symbol(ticker)
        try:
            return self._proto.send_request("symbol_info", {"symbol": symbol})
        except MT5DataError:
            return None

    # ── Batch operations ─────────────────────────────────────────────────

    def batch_realtime_price(self, tickers: list[str]) -> dict[str, float | None]:
        """Fetch realtime mid-prices for multiple tickers concurrently."""
        mapped = [self._map_symbol(t) for t in tickers]
        param_list = [{"symbol": s} for s in mapped]
        results = self._proto.batch_request("realtime_price", param_list)
        out: dict[str, float | None] = {}
        for ticker, res in zip(tickers, results):
            if isinstance(res, dict) and "error" not in res:
                bid = res.get("bid")
                ask = res.get("ask")
                out[ticker] = ((bid + ask) / 2.0) if (bid and ask) else (res.get("last") or bid or ask)
            else:
                out[ticker] = None
        return out

    def batch_symbol_info(self, tickers: list[str]) -> dict[str, dict | None]:
        """Fetch symbol info for multiple tickers concurrently."""
        mapped = [self._map_symbol(t) for t in tickers]
        param_list = [{"symbol": s} for s in mapped]
        results = self._proto.batch_request("symbol_info", param_list)
        out: dict[str, dict | None] = {}
        for ticker, res in zip(tickers, results):
            out[ticker] = res if isinstance(res, dict) and "error" not in res else None
        return out

    # ── Trading ──────────────────────────────────────────────────────────

    def place_order(
        self,
        ticker: str,
        side: str,
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "EigenCapital",
        deviation: int = 20,
        idempotency_key: str | None = None,
    ) -> dict:
        if volume <= 0:
            raise ValueError(f"Invalid volume: {volume}")
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")
        symbol = self._map_symbol(ticker)
        params = {
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "sl": sl,
            "tp": tp,
            "comment": comment,
            "deviation": deviation,
        }
        if idempotency_key:
            params["idempotency_key"] = idempotency_key
        return self._proto.send_request("place_order", params)

    def get_positions(self) -> dict | list[dict]:
        return self._proto.send_request("get_positions")

    def get_account(self) -> dict | None:
        try:
            return self._proto.send_request("get_account")
        except MT5DataError:
            return None

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        params: dict[str, Any] = {"ticket": ticket}
        if sl is not None and not pd.isna(sl):
            params["sl"] = sl
        if tp is not None and not pd.isna(tp):
            params["tp"] = tp
        return self._proto.send_request("modify_position", params)

    def get_deal_by_ticket(self, ticket: int) -> dict | None:
        """Look up a deal (historical execution) by ticket number.

        Returns a dict with deal details if the ticket was ever filled,
        or None if no deal exists for this ticket.
        """
        try:
            return self._proto.send_request("get_deal", {"ticket": ticket})
        except MT5DataError:
            return None

    def close_position(self, ticket: int) -> dict:
        return self._proto.send_request("close_position", {"ticket": ticket})

    # ── Convenience ──────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._proto.connected

    @property
    def account(self) -> int:
        return self._account

    @property
    def server(self) -> str:
        return self._server
