"""Unit tests for Backtest Engine — adversarial synthetic scenarios."""

from eigencapital.core.models.bar import Bar
from eigencapital.backtest.engine import BacktestEngine, BacktestConfig
from eigencapital.research.costs.model import ZERO_COST, MODERATE_COST
from eigencapital.strategies.base import BaseStrategy, StrategySignal


def _make_bar(
    ts_min: int, close: float = 4500.0, volume: int = 1000, instrument_id="ES"
):
    """Helper to create a bar at minute ts_min."""
    return Bar(
        instrument_id=instrument_id,
        timestamp_utc=f"2024-03-15T09:{ts_min:02d}:00Z",
        bar_start_utc=f"2024-03-15T09:{ts_min - 5:02d}:00Z",
        bar_end_utc=f"2024-03-15T09:{ts_min:02d}:00Z",
        open=close - 5,
        high=close + 5,
        low=close - 10,
        close=close,
        volume=volume,
    )


class AlwaysBuyStrategy(BaseStrategy):
    """Simple strategy that always buys — for testing the engine loop."""

    @property
    def strategy_id(self) -> str:
        return "always_buy"

    @property
    def strategy_version(self) -> str:
        return "v1"

    def on_bar(self, timestamp, bars, position_quantity, cash):
        if position_quantity == 0:
            return StrategySignal(direction=1, target_risk=0.01)
        return None


class AlternateStrategy(BaseStrategy):
    """Alternates between buy and sell every bar."""

    def __init__(self):
        self._step = 0

    @property
    def strategy_id(self) -> str:
        return "alternate"

    @property
    def strategy_version(self) -> str:
        return "v1"

    def on_bar(self, timestamp, bars, position_quantity, cash):
        self._step += 1
        if self._step % 2 == 1:
            if position_quantity <= 0:
                return StrategySignal(direction=1, target_risk=0.01)
        else:
            if position_quantity > 0:
                return StrategySignal(direction=-1, target_risk=0.01)
        return None


class FlatStrategy(BaseStrategy):
    """Always flat — generates no signals."""

    @property
    def strategy_id(self) -> str:
        return "flat"

    @property
    def strategy_version(self) -> str:
        return "v1"

    def on_bar(self, timestamp, bars, position_quantity, cash):
        return None


class TestBacktestEngine:
    def test_empty_bars(self):
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=[])
        results = engine.run()
        assert results.final_equity == 100_000  # No trades

    def test_flat_strategy(self):
        bars = [_make_bar(i) for i in range(30, 40)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert results.trade_count == 0
        assert len(results.fill_events) == 0
        assert results.provenance_hash != ""

    def test_always_buy_strategy(self):
        bars = [_make_bar(i) for i in range(30, 40)]
        strategy = AlwaysBuyStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert len(results.signal_events) > 0
        assert len(results.fill_events) > 0
        assert len(results.equity_curve) == 10

    def test_no_look_ahead(self):
        """Verify strategy only sees bars up to current time."""
        bars = [_make_bar(i, close=4500 + i) for i in range(30, 40)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)

        seen_bars = []
        original_on_bar = strategy.on_bar

        def tracking_on_bar(timestamp, bars, position_quantity, cash):
            seen_bars.append(len(bars))
            return original_on_bar(timestamp, bars, position_quantity, cash)

        strategy.on_bar = tracking_on_bar
        engine.run()

        # At each step, bars seen should be <= step index + 1
        for i, count in enumerate(seen_bars):
            assert count <= i + 1, (
                f"Saw {count} bars at step {i}, max should be {i + 1}"
            )

    def test_execution_delay(self):
        """Signals should not fill immediately."""
        bars = [_make_bar(i) for i in range(30, 40)]
        strategy = AlwaysBuyStrategy()
        config = BacktestConfig(execution_delay=2)
        engine = BacktestEngine(strategy=strategy, bars=bars, config=config)
        results = engine.run()
        # With delay=2, fills should not happen on the first bar
        if results.fill_events:
            assert results.fill_events[0]["timestamp"] != "2024-03-15T09:30:00Z"

    def test_cost_model_applied(self):
        """Costs should reduce equity."""
        bars = [_make_bar(i) for i in range(30, 40)]
        strategy = AlwaysBuyStrategy()

        # No cost
        engine_no_cost = BacktestEngine(
            strategy=strategy,
            bars=bars,
            config=BacktestConfig(cost_model=ZERO_COST),
        )
        results_no_cost = engine_no_cost.run()

        # With costs
        strategy2 = AlwaysBuyStrategy()
        engine_with_cost = BacktestEngine(
            strategy=strategy2,
            bars=bars,
            config=BacktestConfig(cost_model=MODERATE_COST),
        )
        results_with_cost = engine_with_cost.run()

        # Cost should reduce equity
        assert results_with_cost.final_equity <= results_no_cost.final_equity

    def test_provenance_hash_deterministic(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        r1 = engine.run()

        strategy2 = FlatStrategy()
        engine2 = BacktestEngine(strategy=strategy2, bars=bars)
        r2 = engine2.run()

        assert r1.provenance_hash == r2.provenance_hash

    def test_synthetic_sudden_price_jump(self):
        """Price jumps 25% in one bar — engine should handle gracefully."""
        bars = [_make_bar(30, close=4500)]
        bars.append(_make_bar(31, close=5625))  # 25% jump
        bars.append(_make_bar(32, close=5625))
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert results.final_equity > 0

    def test_synthetic_zero_volume(self):
        """Zero volume bars should not crash the engine."""
        bars = [_make_bar(i, volume=0) for i in range(30, 35)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert len(results.equity_curve) == 5

    def test_synthetic_extreme_volatility(self):
        """Large price swings in both directions."""
        prices = [4500, 4600, 4400, 4700, 4300, 4800]
        bars = [_make_bar(30 + i, close=p) for i, p in enumerate(prices)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert results.final_equity > 0

    def test_results_to_dict(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        d = results.to_dict()
        assert "final_equity" in d
        assert "provenance_hash" in d

    def test_equity_curve_recorded(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        strategy = FlatStrategy()
        engine = BacktestEngine(strategy=strategy, bars=bars)
        results = engine.run()
        assert len(results.equity_curve) == 5
        for point in results.equity_curve:
            assert "timestamp" in point
            assert "equity" in point
