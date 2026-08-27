"""Adversarial tests for momentum and mean-reversion alpha feature primitives.

Tests cover:
- ROC, MA crossover, dual momentum (time-series momentum)
- Cross-sectional rank, relative strength, percentile rank
- Donchian breakout, Bollinger position
- Z-score, Bollinger bandwidth, distance from SMA/EMA
- Short-term reversal, RSI
- Edge cases: insufficient history, constant prices, extreme values
- Deterministic repeatability
"""

import math
import random

from eigencapital.core.models.bar import Bar
from eigencapital.features.mean_reversion.deviation import (
    compute_distance_from_ema,
    compute_distance_from_sma,
)
from eigencapital.features.mean_reversion.reversal import (
    compute_rsi,
    compute_short_term_reversal,
)
from eigencapital.features.mean_reversion.zscore import (
    compute_bollinger_bandwidth,
    compute_rolling_zscore,
)
from eigencapital.features.momentum.breakout import (
    compute_bollinger_position,
    compute_donchian_breakout,
    compute_donchian_position,
)
from eigencapital.features.momentum.cross_sectional import (
    compute_cross_sectional_rank,
    compute_percentile_rank,
    compute_relative_strength,
)
from eigencapital.features.momentum.time_series import (
    compute_dual_momentum,
    compute_ma_crossover,
    compute_momentum_zscore,
    compute_roc,
)

# ───────────────────────────────────────────────
#  Bar helpers
# ───────────────────────────────────────────────

_bar_counter = 0


def _reset_bar_registry():
    """Clear the Bar registry to allow fresh bar creation."""
    Bar._registry.clear()


def _make_bar(
    close: float,
    day_offset: int = 0,
    instrument_id: str = "ES",
    high: float | None = None,
    low: float | None = None,
    volume: int = 1000,
) -> Bar:
    """Create a valid Bar with proper timestamps and price invariants."""
    global _bar_counter
    _bar_counter += 1

    # Ensure high >= close, low <= close
    if high is None:
        high = close * 1.002
    if low is None:
        low = close * 0.998
    if high < close:
        high = close
    if low > close:
        low = close

    ts = f"2025-01-{15 + day_offset:02d}T10:00:00Z"
    start = f"2025-01-{15 + day_offset:02d}T09:55:00Z"

    return Bar(
        instrument_id=instrument_id,
        timestamp_utc=ts,
        bar_start_utc=start,
        bar_end_utc=ts,
        open=close,  # Use close as open for simplicity
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_bars(
    n: int,
    start_price: float = 100.0,
    drift: float = 0.001,
    instrument_id: str = "ES",
    seed: int = 42,
) -> list[Bar]:
    """Generate a sequence of n valid Bar objects with deterministic prices."""
    _reset_bar_registry()
    rng = random.Random(seed)
    prices = [start_price]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1.0 + drift + rng.gauss(0, 0.01)))

    bars = []
    for i, p in enumerate(prices):
        bars.append(_make_bar(close=p, day_offset=i, instrument_id=instrument_id))
    return bars


def _constant_bars(n: int, price: float = 100.0, instrument_id: str = "ES") -> list[Bar]:
    """Generate n bars at constant price."""
    _reset_bar_registry()
    return [_make_bar(close=price, day_offset=i, instrument_id=instrument_id) for i in range(n)]


def _extreme_bars(n: int, instrument_id: str = "ES") -> list[Bar]:
    """Generate bars with extreme price jumps."""
    _reset_bar_registry()
    bars = [_make_bar(close=100.0, day_offset=0, instrument_id=instrument_id)]
    for i in range(1, n):
        prev = bars[-1].close
        if i % 10 == 0:
            bars.append(_make_bar(close=prev * 2.0, day_offset=i, instrument_id=instrument_id))
        else:
            bars.append(_make_bar(close=prev * 1.001, day_offset=i, instrument_id=instrument_id))
    return bars


def _rising_bars(n: int, start: float = 100.0, instrument_id: str = "ES") -> list[Bar]:
    """Generate monotonically rising bars."""
    _reset_bar_registry()
    return [_make_bar(close=start + i, day_offset=i, instrument_id=instrument_id) for i in range(n)]


def _falling_bars(n: int, start: float = 100.0, instrument_id: str = "ES") -> list[Bar]:
    """Generate monotonically falling bars."""
    _reset_bar_registry()
    return [_make_bar(close=start - i * 0.5, day_offset=i, instrument_id=instrument_id) for i in range(n)]


# ═══════════════════════════════════════════════
#  TIME-SERIES MOMENTUM
# ═══════════════════════════════════════════════


class TestROC:
    def test_basic_roc(self):
        bars = _rising_bars(30)
        roc = compute_roc(bars, lookback=5)
        assert roc is not None
        assert roc > 0  # Rising prices → positive ROC

    def test_roc_insufficient_history(self):
        bars = _rising_bars(3)
        assert compute_roc(bars, lookback=20) is None

    def test_roc_falling(self):
        bars = _falling_bars(30)
        roc = compute_roc(bars, lookback=5)
        assert roc is not None
        assert roc < 0

    def test_roc_zero_denominator(self):
        bars = _constant_bars(10)
        roc = compute_roc(bars, lookback=5)
        assert roc == 0.0

    def test_roc_deterministic(self):
        bars = _make_bars(50)
        assert compute_roc(bars, lookback=10) == compute_roc(bars, lookback=10)

    def test_roc_constant(self):
        bars = _constant_bars(30)
        assert compute_roc(bars, lookback=20) == 0.0


class TestMACrossover:
    def test_basic_crossover(self):
        bars = _rising_bars(60)
        result = compute_ma_crossover(bars, short_window=10, long_window=50)
        assert result is not None
        assert result > 0  # Rising → short MA above long MA

    def test_crossover_insufficient_history(self):
        bars = _rising_bars(10)
        assert compute_ma_crossover(bars, short_window=10, long_window=50) is None

    def test_crossover_flat(self):
        bars = _constant_bars(60)
        result = compute_ma_crossover(bars, short_window=10, long_window=50)
        assert result == 0.0

    def test_crossover_falling(self):
        bars = _falling_bars(60)
        result = compute_ma_crossover(bars, short_window=10, long_window=50)
        assert result is not None
        assert result < 0

    def test_crossover_deterministic(self):
        bars = _make_bars(100)
        assert compute_ma_crossover(bars, 20, 50) == compute_ma_crossover(bars, 20, 50)

    def test_crossover_bounded(self):
        bars = _rising_bars(100)
        result = compute_ma_crossover(bars, short_window=10, long_window=50)
        assert -1.0 <= result <= 1.0


class TestDualMomentum:
    def test_basic_dual_momentum(self):
        bars = _rising_bars(60)
        result = compute_dual_momentum(bars, absolute_lookback=20, relative_lookback=40)
        assert result is not None
        assert result == 1.0  # Both abs and rel positive

    def test_dual_momentum_insufficient_history(self):
        bars = _rising_bars(10)
        assert compute_dual_momentum(bars, 20, 40) is None

    def test_dual_momentum_falling(self):
        bars = _falling_bars(60)
        result = compute_dual_momentum(bars, absolute_lookback=20, relative_lookback=40)
        assert result is not None
        assert result == -1.0

    def test_dual_momentum_mixed(self):
        bars = _make_bars(100, drift=0.0)
        result = compute_dual_momentum(bars, absolute_lookback=5, relative_lookback=80)
        assert result is not None
        # Mixed: short-term up but long-term flat/down → 0
        assert result in (-1.0, 0.0, 1.0)

    def test_dual_momentum_deterministic(self):
        bars = _make_bars(100)
        assert compute_dual_momentum(bars, 20, 40) == compute_dual_momentum(bars, 20, 40)


class TestMomentumZscore:
    def test_basic_zscore(self):
        bars = _rising_bars(30)
        result = compute_momentum_zscore(bars, lookback=5, vol_lookback=20)
        assert result is not None
        assert result > 0

    def test_zscore_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_momentum_zscore(bars, lookback=5, vol_lookback=20) is None

    def test_zscore_constant(self):
        bars = _constant_bars(30)
        result = compute_momentum_zscore(bars, lookback=5, vol_lookback=20)
        # Zero vol → returns None
        assert result is None

    def test_zscore_deterministic(self):
        bars = _make_bars(50)
        r1 = compute_momentum_zscore(bars, 10, 20)
        r2 = compute_momentum_zscore(bars, 10, 20)
        assert r1 == r2


# ═══════════════════════════════════════════════
#  CROSS-SECTIONAL
# ═══════════════════════════════════════════════


class TestCrossSectionalRank:
    def test_basic_rank(self):
        returns = {"ES": 0.05, "NQ": 0.08, "GC": 0.02}
        rank = compute_cross_sectional_rank(returns, "NQ")
        assert rank == 1.0  # highest

    def test_rank_lowest(self):
        returns = {"ES": 0.05, "NQ": 0.08, "GC": 0.02}
        rank = compute_cross_sectional_rank(returns, "GC")
        assert rank == 0.0  # lowest

    def test_rank_missing_instrument(self):
        returns = {"ES": 0.05, "NQ": 0.08}
        assert compute_cross_sectional_rank(returns, "SPY") is None

    def test_rank_single_instrument(self):
        returns = {"ES": 0.05}
        assert compute_cross_sectional_rank(returns, "ES") is None  # < 2 instruments

    def test_rank_many_instruments(self):
        returns = {f"I{i}": float(i) for i in range(100)}
        rank = compute_cross_sectional_rank(returns, "I99")
        assert rank == 1.0  # highest of 100


class TestRelativeStrength:
    def test_basic_rs(self):
        returns = {"ES": 0.05, "NQ": 0.08}
        rs = compute_relative_strength(returns, "ES", "NQ")
        assert rs == -0.03  # underperforming

    def test_rs_outperforming(self):
        returns = {"ES": 0.08, "NQ": 0.05}
        rs = compute_relative_strength(returns, "ES", "NQ")
        assert rs == 0.03

    def test_rs_equal(self):
        returns = {"ES": 0.05, "NQ": 0.05}
        rs = compute_relative_strength(returns, "ES", "NQ")
        assert rs == 0.0

    def test_rs_missing(self):
        returns = {"ES": 0.05}
        assert compute_relative_strength(returns, "ES", "NQ") is None
        assert compute_relative_strength(returns, "NQ", "ES") is None


class TestPercentileRank:
    def test_basic_percentile(self):
        rank = compute_percentile_rank([10.0, 20.0, 30.0, 40.0, 50.0], 40.0)
        assert 0.6 <= rank <= 0.9

    def test_percentile_min(self):
        rank = compute_percentile_rank([10.0, 20.0, 30.0], 10.0)
        assert rank < 0.5

    def test_percentile_max(self):
        rank = compute_percentile_rank([10.0, 20.0, 30.0], 30.0)
        assert rank > 0.5

    def test_percentile_empty(self):
        rank = compute_percentile_rank([], 10.0)
        assert rank == 0.5

    def test_percentile_all_same(self):
        rank = compute_percentile_rank([100.0, 100.0], 100.0)
        assert rank == 0.5


# ═══════════════════════════════════════════════
#  BREAKOUT
# ═══════════════════════════════════════════════


class TestDonchianPosition:
    def test_at_upper_band(self):
        bars = _rising_bars(30)
        pos = compute_donchian_position(bars, lookback=20)
        assert pos is not None
        assert pos > 0.8  # near upper band

    def test_at_lower_band(self):
        bars = _falling_bars(30)
        pos = compute_donchian_position(bars, lookback=20)
        assert pos is not None
        assert pos < 0.2  # near lower band

    def test_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_donchian_position(bars, lookback=20) is None

    def test_flat_market(self):
        bars = _constant_bars(30)
        pos = compute_donchian_position(bars, lookback=20)
        assert pos == 0.5  # mid-channel

    def test_bounded(self):
        bars = _make_bars(50)
        pos = compute_donchian_position(bars, lookback=20)
        assert 0.0 <= pos <= 1.0


class TestDonchianBreakout:
    def test_breakout_up(self):
        bars = _rising_bars(30)
        result = compute_donchian_breakout(bars, lookback=20)
        assert result is not None
        assert result == 1.0

    def test_breakout_down(self):
        bars = _falling_bars(30)
        result = compute_donchian_breakout(bars, lookback=20)
        assert result is not None
        assert result == -1.0

    def test_no_breakout(self):
        bars = _constant_bars(30)
        result = compute_donchian_breakout(bars, lookback=20)
        assert result is not None
        assert result == 0.0

    def test_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_donchian_breakout(bars, lookback=20) is None


class TestBollingerPosition:
    def test_basic_bollinger(self):
        bars = _rising_bars(30)
        pos = compute_bollinger_position(bars, lookback=20, num_std=2.0)
        assert pos is not None
        assert isinstance(pos, float)

    def test_bollinger_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_bollinger_position(bars, lookback=20) is None

    def test_bollinger_constant(self):
        bars = _constant_bars(30)
        pos = compute_bollinger_position(bars, lookback=20)
        assert pos == 0.5  # flat → mid-band

    def test_bollinger_deterministic(self):
        bars = _make_bars(50)
        r1 = compute_bollinger_position(bars, lookback=20)
        r2 = compute_bollinger_position(bars, lookback=20)
        assert r1 == r2

    def test_bollinger_bounded(self):
        bars = _make_bars(50)
        pos = compute_bollinger_position(bars, lookback=20)
        assert 0.0 <= pos <= 1.0


# ═══════════════════════════════════════════════
#  Z-SCORE & BANDWIDTH
# ═══════════════════════════════════════════════


class TestRollingZscore:
    def test_basic_zscore(self):
        bars = _rising_bars(30)
        z = compute_rolling_zscore(bars, lookback=20)
        assert z is not None
        assert z > 0  # prices above mean

    def test_zscore_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_rolling_zscore(bars, lookback=20) is None

    def test_zscore_constant(self):
        bars = _constant_bars(30)
        z = compute_rolling_zscore(bars, lookback=20)
        assert z == 0.0

    def test_zscore_deterministic(self):
        bars = _make_bars(50)
        assert compute_rolling_zscore(bars, 20) == compute_rolling_zscore(bars, 20)


class TestBollingerBandwidth:
    def test_basic_bandwidth(self):
        bars = _make_bars(30, drift=0.005)
        bw = compute_bollinger_bandwidth(bars, lookback=20)
        assert bw is not None
        assert bw > 0

    def test_bandwidth_insufficient_history(self):
        bars = _make_bars(5)
        assert compute_bollinger_bandwidth(bars, lookback=20) is None

    def test_bandwidth_constant(self):
        bars = _constant_bars(30)
        bw = compute_bollinger_bandwidth(bars, lookback=20)
        assert bw == 0.0  # zero std → zero bandwidth


# ═══════════════════════════════════════════════
#  DISTANCE FROM MA
# ═══════════════════════════════════════════════


class TestDistanceFromSMA:
    def test_above_sma(self):
        bars = _rising_bars(30)
        dist = compute_distance_from_sma(bars, lookback=20)
        assert dist is not None
        assert dist > 0

    def test_below_sma(self):
        bars = _falling_bars(30)
        dist = compute_distance_from_sma(bars, lookback=20)
        assert dist is not None
        assert dist < 0

    def test_at_sma(self):
        bars = _constant_bars(30)
        dist = compute_distance_from_sma(bars, lookback=20)
        assert dist == 0.0

    def test_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_distance_from_sma(bars, lookback=20) is None


class TestDistanceFromEMA:
    def test_above_ema(self):
        bars = _rising_bars(30)
        dist = compute_distance_from_ema(bars, lookback=20)
        assert dist is not None
        assert dist > 0

    def test_below_ema(self):
        bars = _falling_bars(30)
        dist = compute_distance_from_ema(bars, lookback=20)
        assert dist is not None
        assert dist < 0

    def test_insufficient_history(self):
        bars = _rising_bars(5)
        assert compute_distance_from_ema(bars, lookback=20) is None


# ═══════════════════════════════════════════════
#  REVERSAL & RSI
# ═══════════════════════════════════════════════


class TestShortTermReversal:
    def test_basic_reversal(self):
        bars = _rising_bars(10)
        rev = compute_short_term_reversal(bars, lookback=1)
        assert rev is not None
        assert rev < 0  # Price rose → negative reversal

    def test_falling_price(self):
        bars = _falling_bars(10)
        rev = compute_short_term_reversal(bars, lookback=1)
        assert rev is not None
        assert rev > 0  # Price fell → positive reversal

    def test_insufficient_history(self):
        bars = _rising_bars(1)
        assert compute_short_term_reversal(bars, lookback=5) is None

    def test_deterministic(self):
        bars = _make_bars(30)
        r1 = compute_short_term_reversal(bars, lookback=1)
        r2 = compute_short_term_reversal(bars, lookback=1)
        assert r1 == r2


class TestRSI:
    def test_bullish_rsi(self):
        bars = _rising_bars(30)
        rsi = compute_rsi(bars, lookback=14)
        assert rsi is not None
        assert rsi > 50

    def test_bearish_rsi(self):
        bars = _falling_bars(30)
        rsi = compute_rsi(bars, lookback=14)
        assert rsi is not None
        assert rsi < 50

    def test_rsi_insufficient_history(self):
        bars = _rising_bars(3)
        assert compute_rsi(bars, lookback=14) is None

    def test_rsi_bounds(self):
        bars = _make_bars(50)
        rsi = compute_rsi(bars, lookback=14)
        assert rsi is not None
        assert 0.0 <= rsi <= 100.0

    def test_rsi_all_gains(self):
        bars = _rising_bars(30)
        rsi = compute_rsi(bars, lookback=14)
        # All gains → RSI = 100
        assert rsi == 100.0

    def test_rsi_deterministic(self):
        bars = _make_bars(50)
        assert compute_rsi(bars, 14) == compute_rsi(bars, 14)

    def test_rsi_constant(self):
        bars = _constant_bars(30)
        rsi = compute_rsi(bars, lookback=14)
        # No gains or losses → avg_loss = 0 → RSI = 100
        assert rsi == 100.0


# ═══════════════════════════════════════════════
#  CROSS-ASSET STRESS
# ═══════════════════════════════════════════════


class TestCrossAssetStress:
    def test_rank_100_instruments(self):
        returns = {f"I{i}": float(i) for i in range(100)}
        rank = compute_cross_sectional_rank(returns, "I50")
        assert 0.4 <= rank <= 0.6

    def test_percentile_large_universe(self):
        values = list(range(1000))
        rank = compute_percentile_rank(values, 500)
        assert 0.4 <= rank <= 0.6

    def test_relative_strength_large(self):
        returns = {f"I{i}": float(i) * 0.001 for i in range(50)}
        rs = compute_relative_strength(returns, "I25", "I24")
        assert rs is not None
        assert abs(rs - 0.001) < 1e-10


# ═══════════════════════════════════════════════
#  EXTREME VALUE STRESS
# ═══════════════════════════════════════════════


class TestExtremeValues:
    def test_extreme_prices_roc(self):
        bars = _extreme_bars(30)
        roc = compute_roc(bars, lookback=5)
        assert roc is not None
        assert math.isfinite(roc)

    def test_extreme_prices_zscore(self):
        bars = _extreme_bars(30)
        z = compute_rolling_zscore(bars, lookback=20)
        assert z is not None
        assert math.isfinite(z)

    def test_very_large_prices(self):
        _reset_bar_registry()
        bars = [_make_bar(close=1e15 + i, day_offset=i) for i in range(30)]
        roc = compute_roc(bars, lookback=5)
        assert roc is not None
        assert math.isfinite(roc)

    def test_extreme_donchian(self):
        bars = _extreme_bars(30)
        pos = compute_donchian_position(bars, lookback=20)
        assert pos is not None
        assert 0.0 <= pos <= 1.0

    def test_extreme_bollinger(self):
        bars = _extreme_bars(30)
        pos = compute_bollinger_position(bars, lookback=20)
        assert pos is not None
        assert 0.0 <= pos <= 1.0


# ═══════════════════════════════════════════════
#  DETERMINISM & REPRODUCIBILITY
# ═══════════════════════════════════════════════


class TestDeterminism:
    def test_roc_determinism(self):
        bars = _make_bars(50, seed=123)
        assert compute_roc(bars, 10) == compute_roc(bars, 10)

    def test_ma_crossover_determinism(self):
        bars = _make_bars(100, seed=456)
        assert compute_ma_crossover(bars, 10, 50) == compute_ma_crossover(bars, 10, 50)

    def test_donchian_determinism(self):
        bars = _make_bars(50, seed=789)
        assert compute_donchian_position(bars, 20) == compute_donchian_position(bars, 20)

    def test_bollinger_determinism(self):
        bars = _make_bars(50, seed=101)
        assert compute_bollinger_position(bars, 20) == compute_bollinger_position(bars, 20)

    def test_rsi_determinism(self):
        bars = _make_bars(50, seed=202)
        assert compute_rsi(bars, 14) == compute_rsi(bars, 14)

    def test_zscore_determinism(self):
        bars = _make_bars(50, seed=303)
        assert compute_rolling_zscore(bars, 20) == compute_rolling_zscore(bars, 20)
