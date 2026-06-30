from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from quorrin.domain.entities.position import PositionSide
from quorrin.domain.entities.trade import Trade, TradeLog


class TestTrade:
    @pytest.fixture
    def sample_trade(self):
        return Trade(
            asset="EURUSD",
            side=PositionSide.LONG,
            entry_price=1.1000,
            exit_price=1.1050,
            entry_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            exit_date=datetime(2026, 6, 10, tzinfo=timezone.utc),
            reason="TP_HIT",
            return_pct=0.5,
            pnl=500.0,
            total_pnl=500.0,
            realized_r=2.0,
            bars=7,
        )

    def test_to_dict_roundtrip(self, sample_trade):
        d = sample_trade.to_dict()
        restored = Trade.from_dict(d)
        assert restored.asset == sample_trade.asset
        assert restored.side == sample_trade.side
        assert restored.entry_price == sample_trade.entry_price
        assert restored.realized_r == sample_trade.realized_r
        assert restored.bars == sample_trade.bars

    def test_from_dict_handles_optional_fields(self):
        d = {
            "asset": "GBPUSD",
            "side": "short",
            "entry_price": 1.2500,
            "exit_price": 1.2400,
            "entry_date": "2026-06-01T00:00:00+00:00",
            "exit_date": "2026-06-10T00:00:00+00:00",
            "reason": "SL_HIT",
            "return_pct": -0.5,
            "pnl": -300.0,
            "total_pnl": -300.0,
            "realized_r": -1.5,
            "bars": 5,
        }
        trade = Trade.from_dict(d)
        assert trade.asset == "GBPUSD"
        assert trade.side == PositionSide.SHORT
        assert trade.return_pct == -0.5

    def test_from_dict_with_missing_optionals(self):
        d = {
            "asset": "EURUSD",
            "side": "long",
            "entry_price": 1.10,
            "exit_price": 1.11,
            "entry_date": "2026-06-01T00:00:00+00:00",
            "exit_date": "2026-06-10T00:00:00+00:00",
            "reason": "TP_HIT",
            "return_pct": 0.9,
            "pnl": 900.0,
            "total_pnl": 900.0,
            "realized_r": 3.0,
            "bars": 7,
        }
        trade = Trade.from_dict(d)
        assert trade.mae is None
        assert trade.mfe is None

    def test_to_dict_immutable(self, sample_trade):
        d = sample_trade.to_dict()
        orig_pnl = d["pnl"]
        d["pnl"] = 99999
        assert sample_trade.pnl == orig_pnl

    def test_deepcopy(self, sample_trade):
        copied = copy.deepcopy(sample_trade)
        copied.pnl = 0.0
        assert sample_trade.pnl != copied.pnl

    def test_equality(self):
        t1 = Trade("A", PositionSide.LONG, 1.0, 1.1, None, None, "TP", 10.0, 100.0, 100.0, 1.0, 5)
        t2 = Trade("A", PositionSide.LONG, 1.0, 1.1, None, None, "TP", 10.0, 100.0, 100.0, 1.0, 5)
        assert t1 == t2


class TestTradeLog:
    def test_empty_log(self):
        log = TradeLog()
        assert log.total_trades == 0
        assert log.win_rate == 0.0
        assert log.profit_factor == 0.0

    @pytest.fixture
    def winning(self):
        return Trade("A", PositionSide.LONG, 1.0, 1.1, None, None, "TP", 10.0, 100.0, 100.0, 2.0, 5)

    @pytest.fixture
    def losing(self):
        return Trade("B", PositionSide.SHORT, 1.0, 1.05, None, None, "SL", -5.0, -50.0, -50.0, -1.0, 3)

    def test_add_trade(self, winning):
        log = TradeLog()
        log.add(winning)
        assert log.total_trades == 1
        assert len(log.winning_trades) == 1

    def test_win_rate_all_wins(self, winning):
        log = TradeLog()
        log.add(winning)
        log.add(winning)
        assert log.win_rate == 1.0

    def test_win_rate_mixed(self, winning, losing):
        log = TradeLog()
        log.add(winning)
        log.add(losing)
        assert log.win_rate == 0.5

    def test_profit_factor(self, winning, losing):
        log = TradeLog()
        log.add(winning)
        log.add(losing)
        assert log.profit_factor == 100.0 / 50.0

    def test_profit_factor_no_losses(self, winning):
        log = TradeLog()
        log.add(winning)
        assert log.profit_factor == float("inf")

    def test_total_pnl(self, winning, losing):
        log = TradeLog()
        log.add(winning)
        log.add(losing)
        assert log.total_pnl == 50.0

    def test_avg_r_multiple(self, winning, losing):
        log = TradeLog()
        log.add(winning)
        log.add(losing)
        assert log.avg_r_multiple == 0.5

    def test_avg_return(self, winning, losing):
        log = TradeLog()
        log.add(winning)
        log.add(losing)
        assert log.avg_return == 2.5

    def test_tracks_losing_trades(self, losing):
        log = TradeLog()
        log.add(losing)
        assert len(log.losing_trades) == 1

    def test_trade_log_preserves_insertion_order(self):
        log = TradeLog()
        t1 = Trade("A", PositionSide.LONG, 1.0, 2.0, None, None, "TP", 100.0, 100.0, 100.0, 5.0, 10)
        t3 = Trade("C", PositionSide.LONG, 1.0, 1.01, None, None, "TP", 1.0, 10.0, 10.0, 0.2, 2)
        t2 = Trade("B", PositionSide.SHORT, 1.0, 0.5, None, None, "TP", 50.0, 50.0, 50.0, 2.0, 5)
        log.add(t1)
        log.add(t2)
        log.add(t3)
        assert len(log.trades) == 3
