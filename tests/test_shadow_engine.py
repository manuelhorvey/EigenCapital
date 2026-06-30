"""Tests for shadow/engine.py — ShadowSLTPEngine counterfactual replay."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from paper_trading.position.dynamic_sltp import DynamicSLTPEngine
from paper_trading.shadow.engine import ShadowSLTPEngine, ShadowTradeRecord


@pytest.fixture
def default_sltp():
    return DynamicSLTPEngine()


@pytest.fixture
def shadow(default_sltp):
    return ShadowSLTPEngine(name="test_shadow", alt_engine=default_sltp)


@pytest.fixture
def price_data():
    """100 bars of uptrending price data."""
    import numpy as np

    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.randn(100) * 0.1) + np.linspace(0, 2, 100)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": 1_000_000,
    }, index=pd.RangeIndex(100))


class TestShadowTradeRecord:
    def test_dataclass_fields(self):
        record = ShadowTradeRecord(
            asset="EURUSD", side="long", entry_price=1.0500, entry_date="2025-01-01",
            exit_price=1.0600, exit_date="2025-01-02", exit_reason="tp",
            bars_held=24, realized_r=2.0, sl_price=1.0400, tp_price=1.0600,
            alt_label="tight_trail", live_exit_reason="sl", live_realized_r=-1.0,
        )
        assert record.asset == "EURUSD"
        assert record.realized_r == 2.0
        assert record.live_exit_reason == "sl"


class TestShadowSLTPEngine:
    def test_initial_state(self, shadow):
        assert not shadow.is_active
        assert shadow.shadow_trades == []
        assert shadow.name == "test_shadow"

    def test_record_entry_activates(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        assert shadow.is_active
        assert shadow._shadow_entry_price == 100.0
        assert shadow._shadow_side == "long"
        assert shadow._shadow_initial_sl < 100.0  # long SL is below entry
        assert shadow._shadow_initial_tp > 100.0  # long TP is above entry

    def _trigger_sl(self, shadow, price_data):
        """Helper: tick below SL to force a stop-out."""
        sl = shadow._shadow_initial_sl
        shadow.tick(sl - 0.01, price_data, "2025-01-02")

    def _trigger_tp(self, shadow, price_data):
        """Helper: tick above TP to force a take-profit."""
        tp = shadow._shadow_initial_tp
        shadow.tick(tp + 0.01, price_data, "2025-01-02")

    def test_tick_hits_stop_loss(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_sl(shadow, price_data)
        assert not shadow.is_active
        assert len(shadow.shadow_trades) == 1
        assert shadow.shadow_trades[0].exit_reason == "sl"

    def test_tick_hits_take_profit(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_tp(shadow, price_data)
        assert not shadow.is_active
        assert len(shadow.shadow_trades) == 1
        assert shadow.shadow_trades[0].exit_reason == "tp"

    def test_tick_within_barriers_no_close(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        mid = (shadow._shadow_initial_sl + shadow._shadow_initial_tp) / 2
        shadow.tick(mid, price_data, "2025-01-02")
        assert shadow.is_active
        assert len(shadow.shadow_trades) == 0

    def test_short_position_sl_above_entry(self, shadow, price_data):
        shadow.record_entry("sell", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        assert shadow._shadow_initial_sl > 100.0
        assert shadow._shadow_initial_tp < 100.0

    def test_short_hits_stop_loss(self, shadow, price_data):
        shadow.record_entry("sell", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        sl = shadow._shadow_initial_sl
        shadow.tick(sl + 0.01, price_data, "2025-01-02")
        assert not shadow.is_active
        assert shadow.shadow_trades[0].exit_reason == "sl"

    def test_short_hits_take_profit(self, shadow, price_data):
        shadow.record_entry("sell", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        tp = shadow._shadow_initial_tp
        shadow.tick(tp - 0.01, price_data, "2025-01-02")
        assert not shadow.is_active
        assert shadow.shadow_trades[0].exit_reason == "tp"

    def test_close_shadow_manually(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        mid = (shadow._shadow_initial_sl + shadow._shadow_initial_tp) / 2
        shadow.close_shadow(mid, "2025-01-02", "signal_flip")
        assert not shadow.is_active
        assert shadow.shadow_trades[0].exit_reason == "signal_flip"

    def test_reset_clears_state(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_sl(shadow, price_data)
        assert not shadow.is_active
        shadow.reset()
        assert not shadow.is_active
        assert shadow.shadow_trades == []

    def test_flush_completed_sets_asset(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_sl(shadow, price_data)
        records = shadow.flush_completed(asset_name="EURUSD")
        assert len(records) == 1
        assert records[0].asset == "EURUSD"
        assert shadow.shadow_trades == []

    def test_set_live_outcome(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_sl(shadow, price_data)
        shadow.set_live_outcome("sl", -1.0)
        assert shadow.shadow_trades[-1].live_exit_reason == "sl"
        assert shadow.shadow_trades[-1].live_realized_r == -1.0

    def test_summary_with_trades(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        self._trigger_sl(shadow, price_data)
        summary = shadow.summary()
        assert summary["n_trades"] == 1
        assert summary["sl_rate"] == 1.0
        assert summary["tp_rate"] == 0.0
        assert summary["total_r"] != 0.0

    def test_tick_when_inactive_does_nothing(self, shadow, price_data):
        shadow.tick(100.0, price_data, "2025-01-02")
        assert len(shadow.shadow_trades) == 0

    def test_mae_mfe_tracked_correctly(self, shadow, price_data):
        shadow.record_entry("long", 100.0, "2025-01-01", price_data, sl_mult=1.0, tp_mult=2.0)
        shadow.tick(100.5, price_data, "2025-01-02")
        shadow.tick(99.5, price_data, "2025-01-03")
        shadow.tick(101.0, price_data, "2025-01-04")
        shadow.close_shadow(101.0, "2025-01-04", "tp")
        record = shadow.shadow_trades[0]
        assert record.mae > 0.0  # price went against entry
        assert record.mfe > 0.0  # price went in favor beyond exit
