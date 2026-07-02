"""Mock MT5 client for testing MT5Broker and MT5Client interface compliance.

Operates fully in memory — no Wine or MT5 terminal required.
Tracks all calls for assertion in tests.
"""

from __future__ import annotations

import pandas as pd

_UNSET = object()


class MockMT5Client:
    """Drop-in mock for MT5Client.

    Configurable with canned responses per method. Tracks every call
    in a `calls` dict for test assertions.

    Defaults simulate a healthy bridge with a real-time price of 100.0,
    standard forex contract size, and successful order placement.

    Pass ``account_info=_UNSET`` to simulate a bridge that returns None
    for get_account().
    """

    def __init__(
        self,
        *,
        ohlcv_data: pd.DataFrame | None = None,
        realtime_prices: dict[str, float | None] | None = None,
        symbol_infos: dict[str, dict] | None = None,
        account_info: dict | object = _UNSET,
        positions: list[dict] | None = None,
        order_result: dict | None = None,
        close_result: dict | None = None,
        modify_result: dict | None = None,
        deal_results: dict[str, dict | None] | None = None,
        connect_fails: bool = False,
        ensure_fails: bool = False,
    ):
        self.ohlcv_data = ohlcv_data if ohlcv_data is not None else pd.DataFrame()
        self._realtime_prices = realtime_prices if realtime_prices is not None else {}
        self._symbol_infos = symbol_infos if symbol_infos is not None else {}
        if account_info is _UNSET:
            self._account_info = {
                "login": 123456,
                "name": "Tester",
                "balance": 10000.0,
                "equity": 10000.0,
                "leverage": 100,
                "currency": "USD",
            }
        else:
            self._account_info = account_info
        self._positions = positions or []
        self._order_result = order_result or {"retcode": 10009, "ticket": 98765}
        self._close_result = close_result or {"result": {"retcode": 10009}}
        self._modify_result = modify_result or {"result": {"retcode": 10009}}
        self._deal_results: dict[str, dict | None] = deal_results or {}
        self._connect_fails = connect_fails
        self._ensure_fails = ensure_fails

        self._connected = False
        self.calls: dict[str, list[tuple]] = {}

    def _record(self, method: str, *args: object) -> None:
        self.calls.setdefault(method, []).append(args)

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        self._record("connect")
        if self._connect_fails:
            self._connected = False
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._record("disconnect")
        self._connected = False

    def ensure_connected(self) -> bool:
        self._record("ensure_connected")
        if self._ensure_fails:
            return False
        self._connected = True
        return True

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Data fetching ────────────────────────────────────────────────────

    def fetch_ohlcv(self, ticker: str, years: int = 2) -> pd.DataFrame:
        self._record("fetch_ohlcv", ticker, years)
        return self.ohlcv_data

    def fetch_ticks(self, ticker: str, from_dt=None, to_dt=None):
        self._record("fetch_ticks", ticker, from_dt, to_dt)
        return pd.DataFrame()

    def realtime_price(self, ticker: str) -> dict | None:
        self._record("realtime_price", ticker)
        price = self._realtime_prices.get(ticker, 100.0)
        if price is None:
            return None
        return {"bid": price - 0.1, "ask": price + 0.1, "last": price}

    def realtime_mid_price(self, ticker: str) -> float | None:
        self._record("realtime_mid_price", ticker)
        return self._realtime_prices.get(ticker, 100.0)

    def realtime_spread(self, ticker: str) -> float | None:
        self._record("realtime_spread", ticker)
        price = self._realtime_prices.get(ticker, 100.0)
        if price is None:
            return None
        bid = price - 0.1
        ask = price + 0.1
        if bid and ask and (bid + ask) > 0:
            return (ask - bid) / ((bid + ask) / 2.0) * 10000.0
        return None

    def symbol_info(self, ticker: str) -> dict | None:
        self._record("symbol_info", ticker)
        return self._symbol_infos.get(ticker, {
            "contract_size": 100000.0,
            "volume_step": 0.01,
            "min_volume": 0.01,
            "max_volume": 100.0,
        })

    # ── Batch operations ─────────────────────────────────────────────────

    def batch_realtime_price(self, tickers: list[str]) -> dict[str, float | None]:
        self._record("batch_realtime_price", tuple(tickers))
        results: dict[str, float | None] = {}
        for t in tickers:
            price = self._realtime_prices.get(t, 100.0)
            results[t] = price
        return results

    def batch_symbol_info(self, tickers: list[str]) -> dict[str, dict | None]:
        self._record("batch_symbol_info", tuple(tickers))
        results: dict[str, dict | None] = {}
        for t in tickers:
            results[t] = self._symbol_infos.get(t, {
                "contract_size": 100000.0,
                "volume_step": 0.01,
                "min_volume": 0.01,
                "max_volume": 100.0,
            })
        return results

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
        self._record("place_order", ticker, side, volume, sl, tp, comment, deviation, idempotency_key)
        return self._order_result

    def get_positions(self) -> list[dict]:
        self._record("get_positions")
        return self._positions

    def get_account(self) -> dict | None:
        self._record("get_account")
        if self._account_info is None:
            return None
        return dict(self._account_info)

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        self._record("modify_position", ticket, sl, tp)
        return self._modify_result

    def get_deal_by_ticket(self, ticket: int) -> dict | None:
        self._record("get_deal_by_ticket", ticket)
        return self._deal_results.get(str(ticket))

    def close_position(self, ticket: int) -> dict:
        self._record("close_position", ticket)
        return self._close_result

    # ── Convenience ──────────────────────────────────────────────────────

    @property
    def account(self) -> int:
        return self._account_info.get("login", 0) if self._account_info else 0

    @property
    def server(self) -> str:
        return "MockServer"
