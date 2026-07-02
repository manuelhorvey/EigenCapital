from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.domain.entities.signal import SignalResult, SignalType, TradeDecision


class TestSignalType:
    def test_from_label_buy(self):
        assert SignalType.from_label(1) == SignalType.BUY

    def test_from_label_sell(self):
        assert SignalType.from_label(-1) == SignalType.SELL

    def test_from_label_flat(self):
        assert SignalType.from_label(0) == SignalType.FLAT

    def test_from_label_invalid_defaults_flat(self):
        assert SignalType.from_label(99) == SignalType.FLAT

    def test_from_string_buy(self):
        assert SignalType.from_string("BUY") == SignalType.BUY

    def test_from_string_sell(self):
        assert SignalType.from_string("SELL") == SignalType.SELL

    def test_from_string_flat(self):
        assert SignalType.from_string("FLAT") == SignalType.FLAT

    def test_from_string_case_insensitive(self):
        assert SignalType.from_string("buy") == SignalType.BUY

    def test_from_string_long_alias(self):
        assert SignalType.from_string("LONG") == SignalType.BUY

    def test_from_string_short_alias(self):
        assert SignalType.from_string("SHORT") == SignalType.SELL

    def test_from_string_invalid_defaults_flat(self):
        assert SignalType.from_string("HOLD") == SignalType.FLAT


class TestSignalResult:
    @pytest.fixture
    def buy_result(self):
        return SignalResult(
            signal_type=SignalType.BUY,
            confidence_pct=0.85,
            label=1,
            prob_long=0.85,
            prob_short=0.10,
            prob_neutral=0.05,
            position_size=1.0,
        )

    def test_direction_buy(self, buy_result):
        assert buy_result.direction == 1

    def test_direction_sell(self):
        sr = SignalResult(SignalType.SELL, 0.75, -1, 0.1, 0.75, 0.15, 1.0)
        assert sr.direction == -1

    def test_direction_flat(self):
        sr = SignalResult(SignalType.FLAT, 0.5, 0, 0.4, 0.4, 0.2, 1.0)
        assert sr.direction == 0

    def test_from_dataframe_row(self):
        row = pd.Series({
            "label": 1,
            "confidence": 0.9,
            "prob_long": 0.9,
            "prob_short": 0.05,
            "prob_neutral": 0.05,
            "position_size": 0.5,
        })
        sr = SignalResult.from_dataframe_row(row)
        assert sr.signal_type == SignalType.BUY
        assert sr.confidence_pct == 0.9
        assert sr.position_size == 0.5


class TestTradeDecision:
    @pytest.fixture
    def buy_decision(self):
        return TradeDecision(
            asset="EURUSD",
            signal=SignalType.BUY,
            label=1,
            confidence=0.85,
            prob_long=0.85,
            prob_short=0.10,
            prob_neutral=0.05,
            close_price=1.1000,
            timestamp="2026-06-30T12:00:00",
            position_size=1.0,
        )

    def test_direction_buy(self, buy_decision):
        assert buy_decision.direction == 1

    def test_direction_sell(self):
        td = TradeDecision("USDJPY", SignalType.SELL, -1, 0.8, 0.1, 0.8, 0.1, 150.0, "2026-06-30", 1.0)
        assert td.direction == -1

    def test_direction_flat(self):
        td = TradeDecision("EURUSD", SignalType.FLAT, 0, 0.5, 0.4, 0.4, 0.2, 1.10, "2026-06-30", 1.0)
        assert td.direction == 0

    def test_is_actionable_buy(self, buy_decision):
        assert buy_decision.is_actionable is True

    def test_is_actionable_flat(self):
        td = TradeDecision("EURUSD", SignalType.FLAT, 0, 0.5, 0.4, 0.4, 0.2, 1.10, "2026-06-30", 1.0)
        assert td.is_actionable is False

    def test_to_dict(self, buy_decision):
        d = buy_decision.to_dict()
        assert d["asset"] == "EURUSD"
        assert d["signal"] == "BUY"
        assert d["confidence"] == 0.85
        assert d["label"] == 1

    def test_default_archetype(self):
        td = TradeDecision("GBPUSD", SignalType.BUY, 1, 0.7, 0.7, 0.2, 0.1, 1.30, "2026-06-30", 0.5)
        assert td.archetype == "UNKNOWN"

    def test_to_dict_includes_feature_hash(self):
        td = TradeDecision("EURUSD", SignalType.BUY, 1, 0.7, 0.7, 0.2, 0.1, 1.10, "2026-06-30", 0.5, feature_hash="abc123")
        d = td.to_dict()
        assert d["feature_hash"] == "abc123"
