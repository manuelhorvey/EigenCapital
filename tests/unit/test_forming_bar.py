"""F-11: live D1 signal must not consume the forming bar."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def _load_loop_module():
    spec = importlib.util.spec_from_file_location(
        "r4_rebalance_loop_forming_bar", REPO / "scripts" / "r4_rebalance_loop.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop_forming_bar"] = module
    spec.loader.exec_module(module)
    return module


class _FakeMT5:
    TIMEFRAME_D1 = 16385

    def __init__(self, empty: bool = False):
        self.empty = empty
        self.rate_calls: list[tuple[str, int, int]] = []
        self.selected: list[str] = []

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        self.selected.append(symbol)
        return enabled

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict]:
        self.rate_calls.append((symbol, start_pos, count))
        if self.empty:
            return []
        base = 1_700_000_000
        return [
            {
                "time": base + index * 86_400,
                "open": 1.0 + index * 0.001,
                "high": 1.1 + index * 0.001,
                "low": 0.9 + index * 0.001,
                "close": 1.05 + index * 0.001,
                "tick_volume": 100 + index,
            }
            for index in range(count)
        ]


def test_fetch_d1_data_starts_at_last_closed_bar():
    loop = _load_loop_module()
    mt5 = _FakeMT5()

    data = loop.fetch_d1_data(mt5, ["EURUSD"], bars=10)

    assert mt5.rate_calls == [("EURUSD", 1, 10)]
    assert list(data) == ["EURUSD"]
    assert isinstance(data["EURUSD"], pd.DataFrame)
    assert len(data["EURUSD"]) == 10


def test_fetch_d1_data_requests_one_closed_bar_per_requested_bar():
    loop = _load_loop_module()
    mt5 = _FakeMT5()

    loop.fetch_d1_data(mt5, ["EURUSD", "GBPUSD"], bars=7)

    assert [(symbol, start_pos, count) for symbol, start_pos, count in mt5.rate_calls] == [
        ("EURUSD", 1, 7),
        ("GBPUSD", 1, 7),
    ]


def test_fetch_d1_data_skips_symbol_without_closed_bars():
    loop = _load_loop_module()
    mt5 = _FakeMT5(empty=True)

    data = loop.fetch_d1_data(mt5, ["EURUSD"], bars=5)

    assert data == {}
    assert mt5.rate_calls == [("EURUSD", 1, 5)]
