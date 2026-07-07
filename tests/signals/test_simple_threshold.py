"""Tests for signals/simple_threshold — generate_signals."""

import numpy as np

from signals.simple_threshold import THRESHOLD, generate_signals


class TestThreshold:
    def test_default_threshold(self):
        assert THRESHOLD == 0.475


class TestGenerateSignals:
    def test_buy_signal(self):
        probs = np.array([[0.2, 0.2, 0.6]])  # long above threshold
        signals = generate_signals(probs)
        assert signals[0] == 1

    def test_sell_signal(self):
        probs = np.array([[0.6, 0.2, 0.2]])  # short above threshold
        signals = generate_signals(probs)
        assert signals[0] == -1

    def test_flat_when_neither_above(self):
        probs = np.array([[0.3, 0.4, 0.3]])  # neither above 0.475
        signals = generate_signals(probs)
        assert signals[0] == 0

    def test_sell_takes_priority_over_buy(self):
        """If both are above threshold, SELL takes priority (last assignment in code)."""
        probs = np.array([[0.6, 0.0, 0.6]])  # both short and long above threshold
        signals = generate_signals(probs)
        assert signals[0] == -1  # SELL (last write in the function)

    def test_multiple_samples(self):
        probs = np.array([
            [0.2, 0.3, 0.5],  # buy
            [0.6, 0.2, 0.2],  # sell
            [0.3, 0.4, 0.3],  # flat
            [0.6, 0.0, 0.6],  # both above, SELL wins (last write)
        ])
        signals = generate_signals(probs)
        expected = np.array([1, -1, 0, -1], dtype=np.int8)
        np.testing.assert_array_equal(signals, expected)

    def test_just_above_threshold(self):
        """Signal just above threshold triggers."""
        probs = np.array([[0.476, 0.3, 0.224]])  # short = 0.476 > 0.475
        signals = generate_signals(probs)
        assert signals[0] == -1

    def test_just_below_threshold(self):
        probs = np.array([[0.474, 0.3, 0.226]])  # short = 0.474, below threshold
        signals = generate_signals(probs)
        assert signals[0] == 0
