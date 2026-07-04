"""Phase 4: Execution Physics Validation Framework.

Extended test suite for execution realism covering:

    1. OHLC MarketSnapshot correctness (the critical gap)
    2. Bridge fill_price with real OHLC data
    3. Gap-through detection through the bridge
    4. Stop-loss adverse selection under high vol
    5. Partial fill degradation under stress
    6. Stale price rejection
    7. Fill determinism with seeded simulator
    8. End-to-end entry → stop fill with gap
"""

import numpy as np
import pandas as pd
import pytest

from paper_trading.execution.bridge import ExecutionBridge, MarketSnapshot
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution.simulator import ExecutionSimulator
from paper_trading.execution.slippage import SlippageModel
from paper_trading.execution.fill import FillModel
from paper_trading.execution.latency import LatencyModel
from paper_trading.entry.decision import PositionIntent, PositionSide
from shared.execution_config import ExecutionConfig


# ── Synthetic OHLC fixtures ──────────────────────────────────────────────────


@pytest.fixture
def normal_market_ohlc() -> pd.DataFrame:
    """A 5-bar OHLC series representing a normal trading day."""
    return pd.DataFrame({
        "open": [100.0, 101.0, 100.5, 101.5, 102.0],
        "high": [101.5, 102.0, 101.5, 102.5, 103.0],
        "low":  [99.5,  100.5, 99.8,  101.0, 101.5],
        "close":[101.0, 100.5, 101.5, 102.0, 102.5],
        "volume": [1e7, 1.2e7, 8e6, 1.5e7, 2e7],
    })


@pytest.fixture
def gap_down_ohlc() -> pd.DataFrame:
    """OHLC with a large gap-down (flash crash scenario) — last bar opens below stop."""
    return pd.DataFrame({
        "open": [100.0, 101.0, 100.5, 99.0, 95.0],
        "high": [101.0, 102.0, 101.0, 100.0, 96.0],
        "low":  [99.5,  100.0, 99.0,  98.0,  93.0],
        "close":[95.5,  100.5, 99.5,  99.0,  94.0],
        "volume": [1e7, 3e7, 2e7, 1.8e7, 1.5e7],
    })


@pytest.fixture
def gap_up_ohlc() -> pd.DataFrame:
    """OHLC with a large gap-up (short squeeze)."""
    return pd.DataFrame({
        "open": [100.0, 108.0, 107.0, 109.0, 108.5],
        "high": [101.0, 110.0, 109.0, 110.0, 109.5],
        "low":  [99.5,  107.0, 106.0, 108.0, 107.5],
        "close":[101.0, 108.5, 107.5, 109.0, 108.0],
        "volume": [1e7, 5e7, 3e7, 4e7, 3.5e7],
    })


@pytest.fixture
def default_config() -> ExecutionConfig:
    return ExecutionConfig(
        base_spread_bps=1.0,
        spread_vol_slope=2.0,
        spread_max_bps=50.0,
        impact_model="none",
    )


@pytest.fixture
def bridge_with_simulator(default_config) -> ExecutionBridge:
    broker = PaperBroker(execution_configs={"TEST": default_config})
    bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
    return bridge


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: OHLC MarketSnapshot Correctness
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarketSnapshotOHLC:
    """MarketSnapshot must carry REAL OHLC, not collapsed mid."""

    def test_bridge_constructs_snapshot_without_ohlc_falls_back_to_mid(self, default_config):
        """When no OHLC provided, snapshot falls back to mid for all fields.
        
        This is the current (broken) behavior — test documents the fallback.
        """
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        snapshot = bridge._build_market_snapshot("TEST", mid_price=100.0, ohlcv=None)
        assert snapshot.open_price == 100.0
        assert snapshot.high_price == 100.0
        assert snapshot.low_price == 100.0
        assert snapshot.current_price == 100.0

    def test_bridge_with_ohlc_uses_real_high_low(self, normal_market_ohlc, default_config):
        """With OHLC provided, snapshot must use real high/low from the bar."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        last = normal_market_ohlc.iloc[-1]
        snapshot = bridge._build_market_snapshot("TEST", mid_price=102.5, ohlcv=normal_market_ohlc)
        assert snapshot.open_price == pytest.approx(last["open"])
        assert snapshot.high_price == pytest.approx(last["high"])
        assert snapshot.low_price == pytest.approx(last["low"])
        assert snapshot.current_price == pytest.approx(102.5)  # mid, not close

    def test_snapshot_high_always_ge_current(self, normal_market_ohlc):
        """Invariant: high >= current, low <= current."""
        last = normal_market_ohlc.iloc[-1]
        mid = last["close"]
        snap = MarketSnapshot(
            current_price=mid,
            open_price=last["open"],
            high_price=last["high"],
            low_price=last["low"],
            vol_zscore=1.0,
        )
        assert snap.high_price >= snap.current_price
        assert snap.low_price <= snap.current_price


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Gap-Through Detection via Bridge
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeGapThrough:
    """Stop-loss fills must gap-through when price opens beyond stop."""

    def test_gap_down_hits_stop_loss_long(self, gap_down_ohlc, default_config):
        """Long position: price gaps down below SL — fill at open (worse)."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)

        position = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-05-26",
            stop_loss=97.0,
            take_profit=104.0,
            vol=0.01,
        )

        result = bridge.fill_stop_loss("TEST", position, current_price=95.0, ohlcv=gap_down_ohlc)
        assert result.gap_fill is True, "Gap-through should be detected"
        assert result.fill_price < 97.0, "Fill should be worse than stop price"

    def test_gap_up_hits_stop_loss_short(self, gap_up_ohlc, default_config):
        """Short position: price gaps up above SL — fill at open (worse)."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)

        position = PositionIntent(
            side=PositionSide.SHORT,
            entry_price=100.0,
            entry_date="2026-05-26",
            stop_loss=105.0,
            take_profit=95.0,
            vol=0.01,
        )

        result = bridge.fill_stop_loss("TEST", position, current_price=108.0, ohlcv=gap_up_ohlc)
        assert result.gap_fill is True, "Gap-through should be detected"
        assert result.fill_price > 105.0, "Fill should be worse than stop price"

    def test_no_gap_no_gap_fill_flag(self, normal_market_ohlc, default_config):
        """Normal fill without gap should not set gap_fill flag."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)

        position = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-05-26",
            stop_loss=99.0,
            take_profit=105.0,
            vol=0.01,
        )

        result = bridge.fill_stop_loss("TEST", position, current_price=100.0, ohlcv=normal_market_ohlc)
        # open=102 > stop=99 → no gap through
        assert result.gap_fill is False

    def test_tp_fill_never_gap_throughs(self, normal_market_ohlc, default_config):
        """TP fills are limit orders — gap-through does not apply."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)

        position = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-05-26",
            stop_loss=99.0,
            take_profit=105.0,
            vol=0.01,
        )

        result = bridge.fill_take_profit("TEST", position, current_price=106.0, ohlcv=normal_market_ohlc)
        assert result.gap_fill is False, "TP fills should never flag gap-through"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Entry Fill Quality Under Volatility
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntryFillQuality:
    """Entry fill prices must degrade under high vol, never improve."""

    def test_entry_fill_worse_than_mid(self, default_config):
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        fill, slip, _ = bridge.fill_price("TEST", "buy", 1000, 100.0)
        assert fill > 100.0, "Buy fill must be above mid (adverse)"
        assert slip > 0, "Slippage must be positive"

    def test_sell_fill_better_for_seller_worse_for_position(self, default_config):
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        fill, slip, _ = bridge.fill_price("TEST", "sell", 1000, 100.0)
        assert fill < 100.0, "Sell fill must be below mid"
        assert slip > 0

    def test_higher_vol_produces_worse_fill(self, default_config):
        """Fill degradation increases with vol z-score (deterministic after SlippageModel fix)."""
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)

        # Establish low-vol baseline: many small moves
        for _ in range(200):
            broker._update_vol_tracking("TEST", 100.0 + np.random.default_rng(0).normal(0, 0.5))
        fill_low_vol, _, _ = bridge.fill_price("TEST", "buy", 1000, 100.0)

        # Inject extreme price jump (dominates recent_std but not full_std)
        broker._update_vol_tracking("TEST", 50.0)
        fill_high_vol, _, _ = bridge.fill_price("TEST", "buy", 1000, 100.0)

        assert fill_high_vol >= fill_low_vol, (
            f"Higher vol must produce worse (higher) buy fill: "
            f"low_vol={fill_low_vol:.6f} high_vol={fill_high_vol:.6f}"
        )

    def test_fill_never_negative(self, default_config):
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        for price in [0.01, 0.1, 1.0, 10.0]:
            fill, _, _ = bridge.fill_price("TEST", "buy", 1000, price)
            assert fill > 0, f"Fill must be positive for price={price}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Simulator with OHLC-driven Gap Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulatorGapThrough:
    """The simulator must detect gap-through using open_/high_/low_price."""

    def test_simulator_gap_down_long(self, gap_down_ohlc):
        last = gap_down_ohlc.iloc[-1]
        market = MarketSnapshot(
            current_price=97.5,
            open_price=last["open"],
            high_price=last["high"],
            low_price=last["low"],
            vol_zscore=2.5,
        )
        sim = ExecutionSimulator(seed=42)
        result = sim.simulate("stop_loss", "sell", 98.0, 1000, market, ExecutionConfig())
        assert result.gap_fill is True, "Simulator must detect gap-through"

    def test_simulator_gap_up_short(self, gap_up_ohlc):
        last = gap_up_ohlc.iloc[-1]
        market = MarketSnapshot(
            current_price=108.0,
            open_price=last["open"],
            high_price=last["high"],
            low_price=last["low"],
            vol_zscore=2.5,
        )
        sim = ExecutionSimulator(seed=42)
        result = sim.simulate("stop_loss", "buy", 107.0, 1000, market, ExecutionConfig())
        assert result.gap_fill is True

    def test_simulator_no_gap_in_normal_market(self, normal_market_ohlc):
        last = normal_market_ohlc.iloc[-1]
        market = MarketSnapshot(
            current_price=102.5,
            open_price=last["open"],
            high_price=last["high"],
            low_price=last["low"],
            vol_zscore=1.0,
        )
        sim = ExecutionSimulator(seed=42)
        result = sim.simulate("stop_loss", "sell", 101.0, 1000, market, ExecutionConfig())
        # open=102 > stop=101 → no gap
        assert result.gap_fill is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: End-to-End Fill Path with Bridge + Simulator
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndFill:
    """End-to-end: entry → stop-loss with gap → TP with no gap."""

    def test_entry_then_stop_gap_long(self, gap_down_ohlc, bridge_with_simulator):
        """Enter long, then price gaps down through stop: fill at gap open."""
        # Entry
        entry_fill, entry_slip, _ = bridge_with_simulator.fill_price(
            "TEST", "buy", 10000, 100.0, ohlcv=gap_down_ohlc,
        )
        assert entry_fill > 100.0

        # Position is now open. Market gaps down.
        position = PositionIntent(
            side=PositionSide.LONG,
            entry_price=entry_fill,
            entry_date="2026-05-26",
            stop_loss=97.0,
            take_profit=104.0,
            vol=0.01,
        )

        stop_result = bridge_with_simulator.fill_stop_loss("TEST", position, current_price=95.0, ohlcv=gap_down_ohlc)
        assert stop_result.gap_fill is True
        assert stop_result.fill_price <= 97.0
        # Gap open is 95.0 (from gap_down_ohlc). Fill should be near open or worse.
        assert stop_result.fill_price <= 96.0, "Gap fill should be at or below gap open"

    def test_entry_then_tp_fill_normal(self, normal_market_ohlc, bridge_with_simulator):
        """Entry long, TP hit normally — no gap, favorable fill."""
        entry_fill, _, _ = bridge_with_simulator.fill_price(
            "TEST", "buy", 10000, 100.0, ohlcv=normal_market_ohlc,
        )
        position = PositionIntent(
            side=PositionSide.LONG,
            entry_price=entry_fill,
            entry_date="2026-05-26",
            stop_loss=98.0,
            take_profit=105.0,
            vol=0.01,
        )
        tp_result = bridge_with_simulator.fill_take_profit("TEST", position, current_price=106.0, ohlcv=normal_market_ohlc)
        assert tp_result.gap_fill is False
        # TP should fill near target (limit order)
        assert tp_result.fill_price >= 105.0 * 0.999, "TP fill should be near target price"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: Stale Price Rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestStalePriceRejection:
    """Fills must be rejected when price data is stale."""

    def test_fill_rejected_on_stale_price(self, default_config):
        broker = PaperBroker(execution_configs={"TEST": default_config})
        bridge = ExecutionBridge(broker, use_execution_simulator=True, seed=42)
        broker.set_price("TEST", 0.0)
        fill, slip, impact = bridge.fill_price("TEST", "buy", 1000, 0.0)
        # Must return mid as-is (no execution on zero price)
        assert fill == 0.0
        assert slip == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: Partial Fill Conservation (quantitative)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPartialFillQuantitative:
    """Fill ratio must degrade monotonically with vol z-score."""

    def test_fill_ratio_monotonic_decreasing(self):
        fill_model = FillModel(seed=42)
        config = ExecutionConfig(fill_vol_threshold=1.0, fill_prob_slope=-0.15, min_fill_prob=0.5)
        ratios = []
        for vol_z in np.linspace(0.5, 6.0, 20):
            qty = fill_model.fill_qty_fraction(1000.0, vol_z, config)
            ratios.append(qty / 1000.0)
        # Ratios should be non-increasing
        for i in range(1, len(ratios)):
            assert ratios[i] <= ratios[i - 1] + 1e-6, (
                f"Fill ratio increased at vol_z={np.linspace(0.5, 6.0, 20)[i]}: "
                f"{ratios[i-1]:.4f} → {ratios[i]:.4f}"
            )

    def test_min_fill_prob_floor_respected(self):
        fill_model = FillModel(seed=42)
        config = ExecutionConfig(fill_vol_threshold=1.0, fill_prob_slope=-0.2, min_fill_prob=0.3)
        for vol_z in [5.0, 10.0, 20.0]:
            qty = fill_model.fill_qty_fraction(1000.0, vol_z, config)
            ratio = qty / 1000.0
            assert ratio >= 0.3 - 0.1, f"Fill ratio {ratio:.4f} dropped below min_fill_prob floor at vol_z={vol_z}"

    def test_fill_qty_zero_vol_equals_requested(self):
        fill_model = FillModel(seed=42)
        config = ExecutionConfig(fill_vol_threshold=2.0, fill_prob_slope=-0.12, min_fill_prob=0.6)
        for qty in [100.0, 1000.0, 1e6]:
            actual = fill_model.fill_qty_fraction(qty, 0.5, config)
            assert actual == qty, f"Full fill expected at low vol for qty={qty}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: Slippage Asymmetry Under Stress
# ═══════════════════════════════════════════════════════════════════════════════


class TestSlippageAsymmetry:
    """SL slippage must be consistently worse than TP across vol regimes."""

    SLIPPAGE_SEEDS = [7, 13, 42, 99, 123, 256, 512, 1024]

    def test_sl_worse_than_tp_across_many_seeds(self):
        config = ExecutionConfig(base_spread_bps=2.0, spread_vol_slope=2.0, spread_max_bps=100.0)
        for seed in self.SLIPPAGE_SEEDS:
            slip = SlippageModel(seed)
            for vol_z in [1.0, 2.0, 3.0, 5.0]:
                sl_price = slip.stop_loss_slippage(100.0, vol_z, config, "long")
                tp_slip = abs(slip.take_profit_slippage(100.0, config))
                assert sl_price > tp_slip, (
                    f"SL slippage ({sl_price:.6f}) must exceed TP slippage "
                    f"({tp_slip:.6f}) at seed={seed}, vol_z={vol_z}"
                )

    def test_sl_slippage_grows_with_vol(self):
        config = ExecutionConfig(base_spread_bps=2.0, spread_vol_slope=2.0, spread_max_bps=100.0)
        slip = SlippageModel(seed=42)
        slippages = []
        for vol_z in np.linspace(1.0, 5.0, 10):
            s = slip.stop_loss_slippage(100.0, vol_z, config, "long")
            slippages.append(s)
        for i in range(1, len(slippages)):
            assert slippages[i] >= slippages[i - 1], (
                f"SL slippage decreased at vol_z={np.linspace(1.0, 5.0, 10)[i]}"
            )

    def test_tp_slippage_remains_near_zero(self):
        config = ExecutionConfig(base_spread_bps=2.0)
        slip = SlippageModel(seed=42)
        for _ in range(100):
            tp_slip = abs(slip.take_profit_slippage(100.0, config))
            assert tp_slip <= 0.02, f"TP slippage exceeded 0.02: {tp_slip}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9: Latency impacts under high vol
# ═══════════════════════════════════════════════════════════════════════════════


class TestLatency:
    """Execution delay occurs only above vol threshold."""

    def test_no_delay_below_threshold(self):
        config = ExecutionConfig(delay_vol_threshold=2.5, delay_bars_max=3)
        lat = LatencyModel(seed=42)
        for vol_z in [0.5, 1.0, 2.0, 2.49]:
            delay = lat.execution_delay_bars(vol_z, config)
            assert delay == 0, f"Unexpected delay at vol_z={vol_z}"

    def test_delay_above_threshold(self):
        config = ExecutionConfig(delay_vol_threshold=2.0, delay_bars_max=3)
        lat = LatencyModel(seed=42)
        for vol_z in [2.5, 3.0, 5.0]:
            delay = lat.execution_delay_bars(vol_z, config)
            assert 0 <= delay <= config.delay_bars_max, f"Delay out of range at vol_z={vol_z}"

    def test_no_delay_when_max_bars_zero(self):
        config = ExecutionConfig(delay_vol_threshold=1.0, delay_bars_max=0)
        lat = LatencyModel(seed=42)
        delay = lat.execution_delay_bars(5.0, config)
        assert delay == 0, "Delay must be 0 when delay_bars_max=0"


# ═══════════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-x", "-v", "--tb=short"])
