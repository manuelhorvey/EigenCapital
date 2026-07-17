from paper_trading.entry.decision import TradeDecision, PositionIntent


class TestTradeDecision:
    def test_create_buy_decision(self):
        d = TradeDecision(
            asset="BTC",
            signal="BUY",
            label=2,
            confidence=71.0,
            prob_long=0.71,
            prob_short=0.10,
            prob_neutral=0.19,
            close_price=50000.0,
            timestamp="2026-06-01",
            position_size=1.0,
        )
        assert d.asset == "BTC"
        assert d.signal == "BUY"
        assert d.label == 2
        assert d.confidence == 71.0

    def test_create_sell_decision(self):
        d = TradeDecision(
            asset="NZDJPY",
            signal="SELL",
            label=0,
            confidence=65.0,
            prob_long=0.10,
            prob_short=0.65,
            prob_neutral=0.25,
            close_price=85.0,
            timestamp="2026-06-01",
            position_size=0.8,
        )
        assert d.signal == "SELL"
        assert d.label == 0
        assert d.position_size == 0.8

    def test_create_flat_decision(self):
        d = TradeDecision(
            asset="GC",
            signal="FLAT",
            label=1,
            confidence=35.0,
            prob_long=0.30,
            prob_short=0.35,
            prob_neutral=0.35,
            close_price=2000.0,
            timestamp="2026-06-01",
            position_size=1.0,
        )
        assert d.signal == "FLAT"
        assert d.label == 1


class TestPositionIntent:
    def test_from_price_and_vol_long(self):
        intent = PositionIntent.from_price_and_vol("long", 100.0, "2026-06-01", 0.02)
        assert intent.side == "long"
        assert intent.entry_price == 100.0
        assert intent.stop_loss == 100.0 * (1 - 0.02 * 1)
        assert intent.take_profit == 100.0 * (1 + 0.02 * 2.5)

    def test_from_price_and_vol_short(self):
        intent = PositionIntent.from_price_and_vol("short", 100.0, "2026-06-01", 0.02)
        assert intent.side == "short"
        assert intent.stop_loss == 100.0 * (1 + 0.02 * 1)
        assert intent.take_profit == 100.0 * (1 - 0.02 * 2.5)

    def test_fields(self):
        intent = PositionIntent(
            side="long",
            entry_price=100.0,
            entry_date="2026-06-01",
            stop_loss=95.0,
            take_profit=110.0,
            vol=0.02,
        )
        assert intent.side == "long"
        assert intent.entry_price == 100.0
        assert intent.stop_loss == 95.0
        assert intent.take_profit == 110.0
        assert intent.vol == 0.02
