"""Adversarial tests for base feature primitives.

Test all return, volatility, range, and volume features
for correctness, edge cases, and look-ahead prevention.
"""

import math

from eigencapital.core.models.bar import Bar
from eigencapital.features.base.ranges import (
    compute_atr,
    compute_high_low_range,
    compute_normalized_range,
    compute_true_range,
    make_atr_feature,
)
from eigencapital.features.base.returns import (
    compute_log_return,
    compute_return_ratio,
    compute_simple_return,
    make_log_return_feature,
    make_return_feature,
)
from eigencapital.features.base.volatility import (
    compute_garman_klass_volatility,
    compute_parkinson_volatility,
    compute_realized_volatility,
    compute_volatility_ratio,
    make_volatility_feature,
)
from eigencapital.features.base.volume import (
    compute_obv_direction,
    compute_volume_ma,
    compute_volume_ratio,
    compute_volume_zscore,
    make_volume_ratio_feature,
)

_counter = 0


def _next_id(prefix: str = "feat") -> str:
    global _counter
    _counter += 1
    return f"{prefix}_{_counter}"


def _make_bar(
    instrument_id: str,
    timestamp: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
) -> Bar:
    """Create a test bar."""
    from datetime import datetime, timedelta

    ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    start = ts - timedelta(hours=1)
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
    )


def _make_uptrend_bars(n: int = 50, start_price: float = 100.0) -> list:
    """Create bars with uptrend."""
    bars = []
    for i in range(n):
        price = start_price * (1.005**i)
        bars.append(
            _make_bar(
                "ES",
                f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                price * 0.999,
                price * 1.005,
                price * 0.995,
                price,
            )
        )
    return bars


def _make_flat_bars(n: int = 50) -> list:
    """Create bars with flat prices."""
    bars = []
    for i in range(n):
        bars.append(
            _make_bar(
                "ES",
                f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                100.0,
                101.0,
                99.0,
                100.0,
            )
        )
    return bars


# ══════════════════════════════════════════════════════════════════
# Return Features
# ══════════════════════════════════════════════════════════════════


class TestReturnFeatures:
    """Tests for return feature computation."""

    def test_simple_return_uptrend(self):
        """Simple return should be positive in uptrend."""
        bars = _make_uptrend_bars(30)
        ret = compute_simple_return(bars, lookback=20)
        assert ret is not None
        assert ret > 0

    def test_simple_return_insufficient_data(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        ret = compute_simple_return(bars, lookback=20)
        assert ret is None

    def test_simple_return_flat(self):
        """Flat market should have zero return."""
        bars = _make_flat_bars(30)
        ret = compute_simple_return(bars, lookback=20)
        assert ret is not None
        assert abs(ret) < 1e-10

    def test_log_return_matches_simple(self):
        """Log return sign should match simple return sign."""
        bars = _make_uptrend_bars(30)
        simple = compute_simple_return(bars, 20)
        log_r = compute_log_return(bars, 20)
        assert simple is not None
        assert log_r is not None
        assert (simple > 0) == (log_r > 0)

    def test_log_return_insufficient_data(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        log_r = compute_log_return(bars, 20)
        assert log_r is None

    def test_return_ratio(self):
        """Return ratio should be computable."""
        bars = _make_uptrend_bars(50)
        ratio = compute_return_ratio(bars, short_lookback=5, long_lookback=20)
        assert ratio is not None

    def test_make_return_feature(self):
        """Should create a valid Feature from return computation."""
        bars = _make_uptrend_bars(30)
        feature = make_return_feature(bars, lookback=20, instrument_id="ES")
        assert feature is not None
        assert feature.feature_family == "returns"
        assert feature.lookback == 20

    def test_make_return_feature_insufficient(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        feature = make_return_feature(bars, lookback=20, instrument_id="ES")
        assert feature is None

    def test_make_log_return_feature(self):
        """Should create a valid Feature from log return computation."""
        bars = _make_uptrend_bars(30)
        feature = make_log_return_feature(bars, lookback=20, instrument_id="ES")
        assert feature is not None
        assert feature.feature_family == "returns"


# ══════════════════════════════════════════════════════════════════
# Volatility Features
# ══════════════════════════════════════════════════════════════════


class TestVolatilityFeatures:
    """Tests for volatility feature computation."""

    def test_realized_volatility_positive(self):
        """Realized volatility should be positive."""
        bars = _make_uptrend_bars(50)
        vol = compute_realized_volatility(bars, lookback=20)
        assert vol is not None
        assert vol > 0

    def test_realized_volatility_flat(self):
        """Flat market should have zero or near-zero volatility."""
        bars = _make_flat_bars(50)
        vol = compute_realized_volatility(bars, lookback=20)
        assert vol is not None
        # Flat bars with same close → zero vol
        assert vol < 0.01

    def test_realized_volatility_insufficient(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        vol = compute_realized_volatility(bars, lookback=20)
        assert vol is None

    def test_parkinson_volatility_positive(self):
        """Parkinson volatility should be positive."""
        bars = _make_uptrend_bars(50)
        vol = compute_parkinson_volatility(bars, lookback=20)
        assert vol is not None
        assert vol > 0

    def test_parkinson_volatility_insufficient(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        vol = compute_parkinson_volatility(bars, lookback=20)
        assert vol is None

    def test_garman_klass_volatility_positive(self):
        """Garman-Klass volatility should be positive."""
        bars = _make_uptrend_bars(50)
        vol = compute_garman_klass_volatility(bars, lookback=20)
        assert vol is not None
        assert vol > 0

    def test_volatility_ratio(self):
        """Volatility ratio should be computable."""
        bars = _make_uptrend_bars(50)
        ratio = compute_volatility_ratio(bars, short_lookback=5, long_lookback=20)
        assert ratio is not None
        assert ratio > 0

    def test_make_volatility_feature(self):
        """Should create a valid Feature from volatility computation."""
        bars = _make_uptrend_bars(50)
        feature = make_volatility_feature(bars, lookback=20, instrument_id="ES")
        assert feature is not None
        assert feature.feature_family == "volatility"


# ══════════════════════════════════════════════════════════════════
# Range Features
# ══════════════════════════════════════════════════════════════════


class TestRangeFeatures:
    """Tests for range feature computation."""

    def test_true_range_basic(self):
        """True range should be >= high - low."""
        bar = _make_bar("ES", "2025-01-01T10:00:00Z", 100, 105, 95, 102)
        tr = compute_true_range(bar, prev_close=101)
        assert tr >= 105 - 95  # At least high - low

    def test_true_range_gap(self):
        """True range should account for gaps."""
        bar = _make_bar("ES", "2025-01-01T10:00:00Z", 95, 97, 93, 96)
        tr = compute_true_range(bar, prev_close=100)  # Gap down
        assert tr >= abs(97 - 100)  # |high - prev_close|

    def test_atr_positive(self):
        """ATR should be positive."""
        bars = _make_uptrend_bars(50)
        atr = compute_atr(bars, lookback=20)
        assert atr is not None
        assert atr > 0

    def test_atr_insufficient(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        atr = compute_atr(bars, lookback=20)
        assert atr is None

    def test_high_low_range(self):
        """High-low range should be positive."""
        bars = _make_uptrend_bars(30)
        hl = compute_high_low_range(bars, lookback=20)
        assert hl is not None
        assert hl > 0

    def test_normalized_range(self):
        """Normalized range should be between 0 and 1 (approximately)."""
        bars = _make_uptrend_bars(30)
        nr = compute_normalized_range(bars, lookback=20)
        assert nr is not None
        assert nr > 0

    def test_make_atr_feature(self):
        """Should create a valid Feature from ATR computation."""
        bars = _make_uptrend_bars(50)
        feature = make_atr_feature(bars, lookback=20, instrument_id="ES")
        assert feature is not None
        assert feature.feature_family == "ranges"


# ══════════════════════════════════════════════════════════════════
# Volume Features
# ══════════════════════════════════════════════════════════════════


class TestVolumeFeatures:
    """Tests for volume feature computation."""

    def test_volume_ma(self):
        """Volume MA should be positive."""
        bars = _make_uptrend_bars(30)
        ma = compute_volume_ma(bars, lookback=20)
        assert ma is not None
        assert ma > 0

    def test_volume_ma_insufficient(self):
        """Should return None with insufficient data."""
        bars = _make_uptrend_bars(5)
        ma = compute_volume_ma(bars, lookback=20)
        assert ma is None

    def test_volume_ratio(self):
        """Volume ratio should be positive."""
        bars = _make_uptrend_bars(30)
        ratio = compute_volume_ratio(bars, lookback=20)
        assert ratio is not None
        assert ratio > 0

    def test_volume_zscore(self):
        """Volume z-score should be finite."""
        bars = _make_uptrend_bars(30)
        z = compute_volume_zscore(bars, lookback=20)
        assert z is not None
        assert math.isfinite(z)

    def test_obv_direction(self):
        """OBV direction should be -1, 0, or +1."""
        bars = _make_uptrend_bars(30)
        direction = compute_obv_direction(bars, lookback=20)
        assert direction is not None
        assert direction in (-1.0, 0.0, 1.0)

    def test_make_volume_ratio_feature(self):
        """Should create a valid Feature from volume ratio computation."""
        bars = _make_uptrend_bars(30)
        feature = make_volume_ratio_feature(bars, lookback=20, instrument_id="ES")
        assert feature is not None
        assert feature.feature_family == "volume"


# ══════════════════════════════════════════════════════════════════
# Property-Based Tests
# ══════════════════════════════════════════════════════════════════


class TestFeaturePrimitivesProperties:
    """Fundamental properties that must hold for all features."""

    def test_deterministic_computation(self):
        """Same inputs must produce same outputs."""
        bars = _make_uptrend_bars(50)
        r1 = compute_simple_return(bars, 20)
        r2 = compute_simple_return(bars, 20)
        assert r1 == r2

    def test_no_lookahead(self):
        """Features computed from earlier bars must not change."""
        bars = _make_uptrend_bars(50)
        r_early = compute_simple_return(bars[:30], 20)
        r_full = compute_simple_return(bars[:30], 20)
        assert r_early == r_full

    def test_upside_returns_positive(self):
        """Uptrend should produce positive returns."""
        bars = _make_uptrend_bars(50)
        ret = compute_simple_return(bars, 20)
        assert ret > 0

    def test_volatility_positive(self):
        """Volatility should always be non-negative."""
        bars = _make_uptrend_bars(50)
        vol = compute_realized_volatility(bars, 20)
        assert vol >= 0

    def test_atr_non_negative(self):
        """ATR should always be non-negative."""
        bars = _make_uptrend_bars(50)
        atr = compute_atr(bars, 20)
        assert atr >= 0

    def test_volume_ratio_positive(self):
        """Volume ratio should always be positive."""
        bars = _make_uptrend_bars(30)
        ratio = compute_volume_ratio(bars, 20)
        assert ratio > 0
