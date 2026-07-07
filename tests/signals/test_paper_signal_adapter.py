"""Tests for signals/paper_signal_adapter — PaperSignalAdapter."""

import numpy as np
import pandas as pd
import pytest

from signals.paper_signal_adapter import PaperSignalAdapter


class TestFromProbabilities:
    def test_buy_signal_when_long_above_threshold(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.70, prob_short=0.20, prob_neutral=0.10,
            close_price=1.1050, timestamp="2026-07-07", threshold=0.45,
        )
        assert decision.signal == "BUY"
        assert decision.label == 2

    def test_sell_signal_when_short_above_threshold(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.20, prob_short=0.70, prob_neutral=0.10,
            close_price=1.1050, timestamp="2026-07-07",
        )
        assert decision.signal == "SELL"
        assert decision.label == 0

    def test_flat_when_neither_above_threshold(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.40, prob_short=0.40, prob_neutral=0.20,
            close_price=1.1050, timestamp="2026-07-07", threshold=0.45,
        )
        assert decision.signal == "FLAT"
        assert decision.label == 1

    def test_confidence_is_max_prob(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.75, prob_short=0.15, prob_neutral=0.10,
            close_price=1.1050, timestamp="2026-07-07",
        )
        assert decision.confidence == 75.0

    def test_archetype_carried_through(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.70, prob_short=0.20, prob_neutral=0.10,
            close_price=1.1050, timestamp="2026-07-07", archetype="TREND_PULLBACK",
        )
        assert decision.archetype == "TREND_PULLBACK"

    def test_default_threshold(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.46, prob_short=0.30, prob_neutral=0.24,
            close_price=1.1050, timestamp="2026-07-07",
        )
        assert decision.signal == "BUY"

    def test_close_price_rounding(self):
        decision = PaperSignalAdapter.from_probabilities(
            asset="EURUSD", prob_long=0.5, prob_short=0.3, prob_neutral=0.2,
            close_price=1.1056789, timestamp="2026-07-07",
        )
        assert decision.close_price == 1.1057


class TestFromModelOutput:
    def test_buy_signal(self):
        proba = np.array([[0.2, 0.1, 0.7]])  # [short, neutral, long]
        close = pd.Series([1.1050])
        timestamps = pd.DatetimeIndex(["2026-07-07"])
        decision = PaperSignalAdapter.from_model_output(
            asset="EURUSD", proba=proba, close_prices=close, timestamps=timestamps,
        )
        assert decision.signal == "BUY"

    def test_sell_signal(self):
        proba = np.array([[0.7, 0.1, 0.2]])
        close = pd.Series([1.1050])
        timestamps = pd.DatetimeIndex(["2026-07-07"])
        decision = PaperSignalAdapter.from_model_output(
            asset="EURUSD", proba=proba, close_prices=close, timestamps=timestamps,
        )
        assert decision.signal == "SELL"

    def test_raises_with_wrong_proba_shape(self):
        proba = np.array([[0.5, 0.5]])  # Only 2 columns, need 3
        close = pd.Series([1.1050])
        timestamps = pd.DatetimeIndex(["2026-07-07"])
        with pytest.raises(ValueError, match="expected 3"):
            PaperSignalAdapter.from_model_output(
                asset="EURUSD", proba=proba, close_prices=close, timestamps=timestamps,
            )

    def test_uses_last_row_of_proba(self):
        proba = np.array([[0.1, 0.1, 0.8], [0.2, 0.2, 0.6], [0.7, 0.1, 0.2]])
        close = pd.Series([1.1000, 1.1020, 1.1050])
        timestamps = pd.DatetimeIndex(["2026-07-05", "2026-07-06", "2026-07-07"])
        decision = PaperSignalAdapter.from_model_output(
            asset="EURUSD", proba=proba, close_prices=close, timestamps=timestamps,
        )
        # Last row: [0.7, 0.1, 0.2] → SELL
        assert decision.signal == "SELL"
        assert decision.close_price == 1.1050
