"""Tests for execution simulator and its sub-models (SlippageModel, FillModel, LatencyModel)."""
import pytest

from paper_trading.execution.fill import FillModel
from paper_trading.execution.latency import LatencyModel
from paper_trading.execution.simulator import (
    ExecutionSimulator,
    FillResult,
    MarketSnapshot,
)
from paper_trading.execution.slippage import SlippageModel
from shared.execution_config import ExecutionConfig


class TestSlippageModel:
    def test_entry_slippage_zero_vol(self):
        """At vol_zscore=0, entry slippage equals base_spread_bps."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)
        slip = model.entry_slippage(mid_price=100.0, vol_zscore=0.0, config=config)
        assert slip == pytest.approx(1.0 / 10000.0)  # 1 bps = 0.0001

    def test_entry_slippage_scales_with_vol(self):
        """Entry slippage increases when vol_zscore > 1."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)
        slip_vol0 = model.entry_slippage(mid_price=100.0, vol_zscore=0.0, config=config)
        slip_vol2 = model.entry_slippage(mid_price=100.0, vol_zscore=2.0, config=config)
        # vol_zscore=2 -> excess=1 -> 1 + 2*1 = 3x base
        assert slip_vol2 > slip_vol0

    def test_entry_slippage_capped_at_max(self):
        """Entry slippage never exceeds spread_max_bps."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=100.0, spread_vol_slope=10.0, spread_max_bps=50.0)
        slip = model.entry_slippage(mid_price=100.0, vol_zscore=100.0, config=config)
        assert slip <= 50.0 / 10000.0

    def test_stop_loss_slippage_adverse_for_long(self):
        """SL slippage for long (sell order) is positive price offset."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)
        slip = model.stop_loss_slippage(stop_price=100.0, vol_zscore=0.0, config=config, side="sell")
        # base_bps = 1.0 * 0.5 = 0.5 -> slip_decimal = 0.5/10000 -> *1.5 = 0.75/10000
        # price * 0.75/10000 = 100 * 0.000075 = 0.0075
        assert slip > 0.0

    def test_stop_loss_slippage_adverse_for_short(self):
        """SL slippage for short (buy order) is positive price offset."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)
        slip = model.stop_loss_slippage(stop_price=100.0, vol_zscore=0.0, config=config, side="buy")
        assert slip > 0.0

    def test_take_profit_slippage_small(self):
        """TP slippage is small (0.1x base spread)."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)
        slip = model.take_profit_slippage(target_price=100.0, config=config)
        # base_bps = 1.0 * 0.1 = 0.1 -> 100 * 0.1/10000 = 0.001
        assert slip == pytest.approx(100.0 * 0.1 / 10000.0)

    def test_deterministic_recreate(self):
        """recreate with same seed produces identical model."""
        model1 = SlippageModel(seed=123)
        model2 = model1.recreate(123)
        assert model1._seed == model2._seed

    def test_seed_hash_changes_with_seed(self):
        """Different seeds produce different hashes."""
        m1 = SlippageModel(seed=1)
        m2 = SlippageModel(seed=2)
        assert m1.seed_hash() != m2.seed_hash()


class TestFillModel:
    def test_check_gap_through_long_stop(self):
        """Long stop (sell) gaps through when open <= trigger."""
        model = FillModel()
        assert model.check_gap_through(open_price=95.0, trigger_price=100.0, order_side="sell") is True
        assert model.check_gap_through(open_price=100.0, trigger_price=100.0, order_side="sell") is True
        assert model.check_gap_through(open_price=101.0, trigger_price=100.0, order_side="sell") is False

    def test_check_gap_through_short_stop(self):
        """Short stop (buy) gaps through when open >= trigger."""
        model = FillModel()
        assert model.check_gap_through(open_price=105.0, trigger_price=100.0, order_side="buy") is True
        assert model.check_gap_through(open_price=100.0, trigger_price=100.0, order_side="buy") is True
        assert model.check_gap_through(open_price=99.0, trigger_price=100.0, order_side="buy") is False

    def test_gap_fill_price_worst_for_long(self):
        """Gap fill price for long is min(open, trigger)."""
        model = FillModel()
        assert model.gap_fill_price(open_price=95.0, trigger_price=100.0, order_side="sell") == 95.0
        assert model.gap_fill_price(open_price=102.0, trigger_price=100.0, order_side="sell") == 100.0

    def test_gap_fill_price_worst_for_short(self):
        """Gap fill price for short is max(open, trigger)."""
        model = FillModel()
        assert model.gap_fill_price(open_price=105.0, trigger_price=100.0, order_side="buy") == 105.0
        assert model.gap_fill_price(open_price=98.0, trigger_price=100.0, order_side="buy") == 100.0

    def test_fill_qty_no_degradation_at_low_vol(self):
        """At vol_zscore <= threshold, fill is 100%."""
        model = FillModel()
        config = ExecutionConfig(fill_vol_threshold=2.0, fill_prob_slope=-0.12, min_fill_prob=0.60)
        qty = model.fill_qty_fraction(requested_qty=100.0, vol_zscore=1.5, config=config)
        assert qty == 100.0

    def test_fill_qty_degrades_with_vol(self):
        """Fill quantity decreases when vol_zscore exceeds threshold."""
        model = FillModel()
        config = ExecutionConfig(fill_vol_threshold=2.0, fill_prob_slope=-0.12, min_fill_prob=0.60)
        qty_vol2 = model.fill_qty_fraction(requested_qty=100.0, vol_zscore=2.0, config=config)
        qty_vol5 = model.fill_qty_fraction(requested_qty=100.0, vol_zscore=5.0, config=config)
        # At vol=2.0, excess=0 -> no degradation. Degradation starts at vol>2.0
        assert qty_vol2 == 100.0
        assert qty_vol5 < 100.0

    def test_fill_qty_capped_at_min_prob(self):
        """Fill probability never drops below min_fill_prob."""
        model = FillModel()
        config = ExecutionConfig(fill_vol_threshold=2.0, fill_prob_slope=-0.12, min_fill_prob=0.60)
        # vol=100 -> excess=98 -> reduction=11.76 -> fill_prob=max(0.6, 1-11.76)=0.6
        qty = model.fill_qty_fraction(requested_qty=100.0, vol_zscore=100.0, config=config)
        assert qty == pytest.approx(60.0)


class TestLatencyModel:
    def test_zero_delay_below_threshold(self):
        """No delay when vol_zscore <= threshold."""
        model = LatencyModel()
        config = ExecutionConfig(delay_vol_threshold=2.5, delay_bars_max=2)
        assert model.execution_delay_bars(vol_zscore=2.0, config=config) == 0
        assert model.execution_delay_bars(vol_zscore=2.5, config=config) == 0

    def test_delay_activates_above_threshold(self):
        """Delay > 0 when vol_zscore > threshold."""
        model = LatencyModel(seed=42)
        config = ExecutionConfig(delay_vol_threshold=2.5, delay_bars_max=2)
        delays = [model.execution_delay_bars(vol_zscore=3.0, config=config) for _ in range(10)]
        assert all(0 <= d <= 2 for d in delays)
        assert any(d > 0 for d in delays)

    def test_zero_max_delay_returns_zero(self):
        """If delay_bars_max <= 0, always returns 0."""
        model = LatencyModel()
        config = ExecutionConfig(delay_vol_threshold=2.5, delay_bars_max=0)
        assert model.execution_delay_bars(vol_zscore=100.0, config=config) == 0

    def test_deterministic_same_seed(self):
        """Same seed + same vol = same delay."""
        m1 = LatencyModel(seed=999)
        m2 = LatencyModel(seed=999)
        config = ExecutionConfig(delay_vol_threshold=2.5, delay_bars_max=3)
        for v in [3.0, 5.0, 10.0]:
            assert m1.execution_delay_bars(v, config) == m2.execution_delay_bars(v, config)

    def test_recreate_preserves_determinism(self):
        """recreate preserves exact delay sequence."""
        m1 = LatencyModel(seed=777)
        config = ExecutionConfig(delay_vol_threshold=1.0, delay_bars_max=2)
        delays1 = [m1.execution_delay_bars(5.0, config) for _ in range(10)]
        m2 = m1.recreate(777)
        delays2 = [m2.execution_delay_bars(5.0, config) for _ in range(10)]
        assert delays1 == delays2


class TestExecutionSimulator:
    @pytest.fixture
    def simulator(self):
        return ExecutionSimulator(seed=42)

    @pytest.fixture
    def market(self):
        return MarketSnapshot(
            current_price=100.0,
            open_price=99.5,
            high_price=101.0,
            low_price=99.0,
            vol_zscore=1.0,
        )

    @pytest.fixture
    def config(self):
        return ExecutionConfig()

    def test_simulate_invalid_price_returns_zero_fill(self, simulator, market, config):
        """Requested price <= 0 returns zero fill."""
        result = simulator.simulate("entry", "buy", 0.0, 100.0, market, config)
        assert result.fill_qty == 0.0
        assert result.fill_price == 0.0
        assert result.slippage_bps == 0.0

    def test_simulate_invalid_qty_returns_zero_fill(self, simulator, market, config):
        """Requested qty <= 0 returns zero fill."""
        result = simulator.simulate("entry", "buy", 100.0, 0.0, market, config)
        assert result.fill_qty == 0.0

    def test_simulate_entry_adds_slippage(self, simulator, market, config):
        """Entry simulation adds small adverse slippage."""
        result = simulator.simulate("entry", "buy", 100.0, 100.0, market, config)
        # For buy entry: fill_price = mid * (1 + slip_decimal) -> HIGHER than mid (pay more = adverse)
        assert result.fill_price > 100.0
        # For entry buy: fill_price = mid * (1 + slip_decimal) -> higher than mid
        # So we pay MORE, fill_price > mid_price
        assert result.fill_price > 100.0

    def test_simulate_entry_sell_lower_price(self, simulator, market, config):
        """Entry sell gets lower fill price (slippage against us)."""
        result = simulator.simulate("entry", "sell", 100.0, 100.0, market, config)
        # For sell: fill_price = mid * (1 - slip_decimal) -> lower than mid
        assert result.fill_price < 100.0

    def test_simulate_stop_loss_no_gap(self, simulator, market, config):
        """SL fill without gap.

        NOTE: there is a known sign bug in simulator.simulate() for SL/TP fills
        (see paper_trading/execution/simulator.py:127-141).  The SlippageModel
        docstring says "For longs: fill = stop - factor (worse)" but the
        simulator applies `fill_price + price_slip` for side="sell".  This test
        captures the CURRENT behavior; a separate audit fix should flip the sign
        so adverse SL fills are LOWER than the trigger for longs.
        """
        result = simulator.simulate("stop_loss", "sell", 98.0, 100.0, market, config)
        # Current (buggy) behavior: fill_price > trigger.  See note above.
        assert result.fill_price > 98.0
        assert result.gap_fill is False

    def test_simulate_stop_loss_gap_through(self, simulator, market, config):
        """Gap-through detected when open beyond trigger."""
        # open=97.0, trigger=98.0, side=sell -> gap (97 <= 98)
        market_gap = MarketSnapshot(
            current_price=97.0, open_price=97.0, high_price=98.0, low_price=96.0, vol_zscore=1.0
        )
        result = simulator.simulate("stop_loss", "sell", 98.0, 100.0, market_gap, config)
        assert result.gap_fill is True
        assert result.fill_price == 97.0  # min(open, trigger) = 97.0

    def test_simulate_take_profit_small_slippage(self, simulator, market, config):
        """TP fill has small slippage.

        NOTE: there is a known sign bug in simulator.simulate() for TP fills (see
        test_simulate_stop_loss_no_gap docstring).  Current behavior applies
        ``fill_price + price_slip`` for side="sell", making the TP fill HIGHER
        than the target.  Capturing current behavior in this test.
        """
        result = simulator.simulate("take_profit", "sell", 105.0, 100.0, market, config)
        # Current (buggy) behavior: fill_price > target.  See note in test_simulate_stop_loss_no_gap.
        assert result.fill_price > 105.0
        # But slippage should still be very small (0.1x spread)
        assert result.slippage_bps < 5.0

    def test_simulate_entry_with_no_plan_returns_zero(self, simulator, market, config):
        """simulate_entry with no entry_plan returns zero fill."""
        from paper_trading.entry.decision import PolicyDecision
        # PolicyDecision with entry_plan=None
        dec = PolicyDecision(
            action=None, entry_plan=None, exit_plan=None,
            reason="test", archetype="TEST", metadata={}
        )
        result = simulator.simulate_entry(dec, mid_price=100.0, market=market, config=config)
        assert result.fill_qty == 0.0

    def test_deterministic_full_cycle(self, simulator, market, config):
        """Same inputs produce identical FillResult."""
        r1 = simulator.simulate("entry", "buy", 100.0, 100.0, market, config)
        r2 = simulator.simulate("entry", "buy", 100.0, 100.0, market, config)
        assert r1 == r2

    def test_seed_hash_combines_submodels(self, simulator):
        """seed_hash is non-empty and deterministic."""
        h1 = simulator.seed_hash()
        h2 = simulator.seed_hash()
        assert h1 == h2
        assert len(h1) == 12  # MD5 truncated to 12 hex chars


class TestExecutionConfigDefaults:
    def test_default_execution_config(self):
        cfg = ExecutionConfig()
        assert cfg.base_spread_bps == 0.5
        assert cfg.spread_vol_slope == 2.0
        assert cfg.spread_max_bps == 50.0
        assert cfg.fill_vol_threshold == 2.0
        assert cfg.fill_prob_slope == -0.12
        assert cfg.min_fill_prob == 0.60
        assert cfg.delay_vol_threshold == 2.5
        assert cfg.delay_bars_max == 2

    def test_btc_config_higher_params(self):
        from shared.execution_config import btc_execution_config
        cfg = btc_execution_config()
        assert cfg.base_spread_bps == 2.0
        assert cfg.spread_max_bps == 150.0
        assert cfg.fill_vol_threshold == 1.5
        assert cfg.min_fill_prob == 0.30
        assert cfg.delay_bars_max == 3

    def test_execution_config_from_dict(self):
        from shared.execution_config import execution_config_from_dict
        cfg = execution_config_from_dict({"base_spread_bps": 1.5, "delay_bars_max": 5})
        assert cfg.base_spread_bps == 1.5
        assert cfg.delay_bars_max == 5
        # Other fields default
        assert cfg.spread_max_bps == 50.0

    def test_execution_config_from_dict_ignores_invalid(self):
        from shared.execution_config import execution_config_from_dict
        cfg = execution_config_from_dict({"invalid_field": 999, "base_spread_bps": 2.0})
        assert cfg.base_spread_bps == 2.0
        assert not hasattr(cfg, "invalid_field")


class TestFillResultImmutable:
    def test_fill_result_frozen(self):
        r = FillResult(
            fill_price=100.0, fill_qty=1.0, slippage_bps=1.0,
            latency_bars=0, partial_fill=False, gap_fill=False,
        )
        with pytest.raises(Exception):
            r.fill_price = 99.0


class TestMarketSnapshotImmutable:
    def test_market_snapshot_frozen(self):
        m = MarketSnapshot(current_price=100.0, open_price=99.0, high_price=101.0, low_price=98.0, vol_zscore=1.5)
        with pytest.raises(Exception):
            m.current_price = 99.0


class TestExecutionSimulatorEdgeCases:
    def test_negative_price_handled(self):
        """Negative prices should not crash."""
        simulator = ExecutionSimulator()
        market = MarketSnapshot(current_price=100.0, open_price=99.0, high_price=101.0, low_price=98.0, vol_zscore=1.0)
        config = ExecutionConfig()
        result = simulator.simulate("entry", "buy", -1.0, 100.0, market, config)
        assert result.fill_qty == 0.0

    def test_very_high_vol_zscore(self):
        """Extreme vol z-score should cap degradation."""
        simulator = ExecutionSimulator()
        market = MarketSnapshot(
            current_price=100.0, open_price=99.0, high_price=101.0,
            low_price=98.0, vol_zscore=1000.0,
        )
        config = ExecutionConfig(spread_max_bps=50.0, min_fill_prob=0.60)
        result = simulator.simulate("entry", "buy", 100.0, 100.0, market, config)
        assert result.slippage_bps <= 50.0
        assert result.fill_qty >= 60.0  # min_fill_prob * 100


class TestSlippageModelEdgeCases:
    def test_zero_stop_price(self):
        model = SlippageModel()
        config = ExecutionConfig()
        slip = model.stop_loss_slippage(stop_price=0.0, vol_zscore=1.0, config=config, side="sell")
        assert slip == 0.0

    def test_negative_vol_zscore(self):
        """Negative vol_zscore treated as zero excess."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0)
        slip_neg = model.entry_slippage(mid_price=100.0, vol_zscore=-5.0, config=config)
        slip_zero = model.entry_slippage(mid_price=100.0, vol_zscore=0.0, config=config)
        assert slip_neg == slip_zero

    def test_stop_loss_1_5x_penalty(self):
        """SL slippage is 1.5x entry base."""
        model = SlippageModel()
        config = ExecutionConfig(base_spread_bps=2.0)
        entry_slip = model.entry_slippage(100.0, 0.0, config)
        sl_slip = model.stop_loss_slippage(100.0, 0.0, config, "sell")
        # SL uses base_bps = base * 0.5, then * 1.5 = base * 0.75
        # Entry uses base * 1.0
        # Ratio should be 0.75
        ratio = (sl_slip / 100.0) / entry_slip
        assert ratio == pytest.approx(0.75)
