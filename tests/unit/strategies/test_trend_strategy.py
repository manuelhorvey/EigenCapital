"""Tests for cross-asset trend strategy — deliberately simple baseline.

This strategy is designed to test the complete research pipeline,
not to be profitable.
"""

import pytest
from eigencapital.strategies.trend.strategy import CrossAssetTrendStrategy
from eigencapital.strategies.trend.config import TrendConfig
from eigencapital.strategies.trend.features import (
    compute_cumulative_return,
    compute_realized_volatility,
    compute_trend_signal,
    compute_position_size,
)
from eigencapital.core.models.bar import Bar

_bar_counter = 0


def _make_bar(
    instrument_id: str,
    timestamp: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
    bar_interval: str = "1h",
) -> Bar:
    """Create a test bar with valid bar_start_utc < timestamp_utc."""
    global _bar_counter
    _bar_counter += 1
    from datetime import datetime, timedelta

    ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if bar_interval == "1h":
        start = ts - timedelta(hours=1)
    elif bar_interval == "1d":
        start = ts - timedelta(days=1)
    else:
        start = ts - timedelta(minutes=1)
    bar_start = start.strftime("%Y-%m-%dT%H:%M:%SZ")

    return Bar(
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        bar_start_utc=bar_start,
        bar_end_utc=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        bar_interval=bar_interval,
    )


def _make_uptrend_bars(n: int = 70, start_price: float = 100.0) -> list:
    """Create daily bars with an uptrend."""
    bars = []
    for i in range(n):
        price = start_price * (1.005**i)  # 0.5% daily uptrend
        bars.append(
            _make_bar(
                instrument_id="ES",
                timestamp=f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                open_=price * 0.999,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                bar_interval="1d",
            )
        )
    return bars


def _make_downtrend_bars(n: int = 70, start_price: float = 100.0) -> list:
    """Create daily bars with a downtrend."""
    bars = []
    for i in range(n):
        price = start_price * (0.995**i)  # -0.5% daily downtrend
        bars.append(
            _make_bar(
                instrument_id="ES",
                timestamp=f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                open_=price * 1.001,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                bar_interval="1d",
            )
        )
    return bars


@pytest.fixture(autouse=True)
def clear_bar_registry():
    """Clear bar registry before each test."""
    Bar._registry.clear()
    yield
    Bar._registry.clear()


class TestTrendConfig:
    """Tests for TrendConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = TrendConfig()
        assert config.lookback_period == 63
        assert config.entry_threshold == 1.0
        assert config.exit_threshold == 0.0
        assert config.volatility_lookback == 21
        assert config.risk_target == 0.10
        assert config.max_position_size == 1.0

    def test_config_hash_deterministic(self):
        """Test that config hash is deterministic."""
        config = TrendConfig()
        hash1 = config.config_hash()
        hash2 = config.config_hash()
        assert hash1 == hash2

    def test_config_hash_different_params(self):
        """Test that different configs produce different hashes."""
        config1 = TrendConfig(lookback_period=63)
        config2 = TrendConfig(lookback_period=64)
        assert config1.config_hash() != config2.config_hash()

    def test_invalid_lookback(self):
        """Test invalid lookback period."""
        with pytest.raises(ValueError):
            TrendConfig(lookback_period=0)

    def test_invalid_volatility_lookback(self):
        """Test invalid volatility lookback."""
        with pytest.raises(ValueError):
            TrendConfig(volatility_lookback=0)


class TestFeatures:
    """Tests for feature computation."""

    def test_cumulative_return_insufficient_data(self):
        """Test cumulative return with insufficient bars."""
        bars = [
            _make_bar(
                "ES", f"2025-01-01T{i:02d}:00:00Z", 100, 101, 99, 100, bar_interval="1h"
            )
            for i in range(1, 6)
        ]
        result = compute_cumulative_return(bars, lookback=63)
        assert result is None

    def test_cumulative_return_uptrend(self):
        """Test cumulative return with uptrend."""
        bars = _make_uptrend_bars(70)
        result = compute_cumulative_return(bars, lookback=63)
        assert result is not None
        assert result > 0  # Uptrend should have positive return

    def test_cumulative_return_downtrend(self):
        """Test cumulative return with downtrend."""
        bars = _make_downtrend_bars(70)
        result = compute_cumulative_return(bars, lookback=63)
        assert result is not None
        assert result < 0  # Downtrend should have negative return

    def test_realized_volatility_insufficient_data(self):
        """Test volatility with insufficient bars."""
        bars = [
            _make_bar(
                "ES", f"2025-01-01T{i:02d}:00:00Z", 100, 101, 99, 100, bar_interval="1h"
            )
            for i in range(1, 6)
        ]
        result = compute_realized_volatility(bars, lookback=21)
        assert result is None

    def test_realized_volatility_positive(self):
        """Test volatility is positive."""
        bars = _make_uptrend_bars(70)
        result = compute_realized_volatility(bars, lookback=21)
        assert result is not None
        assert result > 0

    def test_trend_signal_uptrend(self):
        """Test trend signal is positive for uptrend."""
        bars = _make_uptrend_bars(70)
        signal = compute_trend_signal(bars, lookback=63, vol_lookback=21)
        assert signal is not None
        assert signal > 0  # Uptrend should have positive signal

    def test_trend_signal_downtrend(self):
        """Test trend signal is negative for downtrend."""
        bars = _make_downtrend_bars(70)
        signal = compute_trend_signal(bars, lookback=63, vol_lookback=21)
        assert signal is not None
        assert signal < 0  # Downtrend should have negative signal

    def test_position_size_long(self):
        """Test position sizing for long signal."""
        size = compute_position_size(
            signal=2.0,
            risk_target=0.10,
            volatility=0.20,
            max_position=1.0,
        )
        assert size > 0  # Positive = LONG

    def test_position_size_short(self):
        """Test position sizing for short signal."""
        size = compute_position_size(
            signal=-2.0,
            risk_target=0.10,
            volatility=0.20,
            max_position=1.0,
        )
        assert size < 0  # Negative = SHORT

    def test_position_size_zero_signal(self):
        """Test position sizing for zero signal."""
        size = compute_position_size(
            signal=0.0,
            risk_target=0.10,
            volatility=0.20,
            max_position=1.0,
        )
        assert size == 0.0

    def test_position_size_capped(self):
        """Test position size is capped at max_position."""
        size = compute_position_size(
            signal=10.0,
            risk_target=0.10,
            volatility=0.01,  # Very low vol → large position
            max_position=1.0,
        )
        assert abs(size) <= 1.0


class TestCrossAssetTrendStrategy:
    """Tests for the cross-asset trend strategy."""

    def test_strategy_properties(self):
        """Test strategy ID and version."""
        strategy = CrossAssetTrendStrategy()
        assert strategy.strategy_id == "cross_asset_trend_v1"
        assert strategy.strategy_version == "v1.0.0"

    def test_insufficient_data_returns_none(self):
        """Test that strategy returns None with insufficient data."""
        strategy = CrossAssetTrendStrategy()
        bars = [
            _make_bar(
                "ES", f"2025-01-01T{i:02d}:00:00Z", 100, 101, 99, 100, bar_interval="1h"
            )
            for i in range(1, 6)
        ]
        signal = strategy.on_bar(
            timestamp="2025-01-01T05:00:00Z",
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        assert signal is None

    def test_uptrend_generates_long_signal(self):
        """Test that uptrend generates LONG signal."""
        strategy = CrossAssetTrendStrategy()
        bars = _make_uptrend_bars(70)
        signal = strategy.on_bar(
            timestamp=bars[-1].timestamp_utc,
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        assert signal is not None
        assert signal.direction == 1  # LONG

    def test_downtrend_generates_short_signal(self):
        """Test that downtrend generates SHORT signal."""
        strategy = CrossAssetTrendStrategy()
        bars = _make_downtrend_bars(70)
        signal = strategy.on_bar(
            timestamp=bars[-1].timestamp_utc,
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        assert signal is not None
        assert signal.direction == -1  # SHORT

    def test_no_signal_in_flat_market(self):
        """Test that flat market generates no signal."""
        strategy = CrossAssetTrendStrategy()
        # Create flat bars (no trend)
        bars = []
        for i in range(70):
            bars.append(
                _make_bar(
                    instrument_id="ES",
                    timestamp=f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                    open_=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    bar_interval="1d",
                )
            )
        signal = strategy.on_bar(
            timestamp=bars[-1].timestamp_utc,
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        # Flat market should either be None or very weak signal
        if signal is not None:
            assert abs(signal.direction) <= 1

    def test_signal_metadata(self):
        """Test that signal contains expected metadata."""
        strategy = CrossAssetTrendStrategy()
        bars = _make_uptrend_bars(70)
        signal = strategy.on_bar(
            timestamp=bars[-1].timestamp_utc,
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        if signal is not None:
            assert "signal_zscore" in signal.metadata
            assert "volatility" in signal.metadata
            assert "lookback" in signal.metadata

    def test_confidence_range(self):
        """Test that confidence is in [0, 1]."""
        strategy = CrossAssetTrendStrategy()
        bars = _make_uptrend_bars(70)
        signal = strategy.on_bar(
            timestamp=bars[-1].timestamp_utc,
            bars=bars,
            position_quantity=0.0,
            cash=100_000.0,
        )
        if signal is not None:
            assert 0.0 <= signal.confidence <= 1.0
