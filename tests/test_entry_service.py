from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from paper_trading.entry.decision import PositionSide
from paper_trading.services.entry_service import EntryService


@pytest.fixture
def mock_asset():
    asset = MagicMock()
    asset.name = "TEST"
    asset.current_price = 105.0
    asset.config = {}
    asset.price_data = pd.DataFrame({"close": np.linspace(100, 110, 50)})
    asset.validity_sm = MagicMock()
    asset.validity_sm.current_state.value = "GREEN"
    asset.governance = MagicMock()
    asset.governance._narrative_sl_mult = 1.0
    asset.governance._narrative_size_scalar = 1.0
    asset.governance._liquidity_sl_mult = 1.0
    asset.governance._liquidity_size_scalar = 1.0
    asset.sl_mult = 1.0
    asset.tp_mult = 2.0
    asset.regime_geometry = {}
    asset._entry_archetype = "UNKNOWN"
    asset._structure_detector = MagicMock()
    asset._entry_optimizer = MagicMock()
    asset.initial_capital = 100000
    asset.capital_base = 100000
    asset.current_value = 100000
    asset.pos_mgr.position_size = 0.95
    asset.pos_mgr.exposure_multiplier = 1.0
    asset.execution_bridge = None
    asset._attribution = MagicMock()
    asset._shadow_sltp = None
    asset._pending_entries = {}
    asset._sltp_engine = None
    asset._scale_out_engine = None
    asset._last_label = 0
    asset._last_confidence = 0.0
    asset._last_prob_long = 0.0
    asset._last_prob_short = 0.0
    asset._last_prob_neutral = 0.0
    asset._last_meta_proba = None
    asset._current_regime = "neutral"
    asset._last_entry_slippage = 0.0
    asset._last_policy_hash = ""
    asset._bars_at_entry = 0
    asset._entry_price = 0.0
    asset._regime_adjusted_entry = False
    asset._current_trade_id = None
    asset._cooldown_penalty = MagicMock(return_value=0.0)
    asset._last_stop_out_cycle = None
    asset._last_stop_out_side = None
    asset._last_signal_flip_cycle = 0
    asset._min_flip_interval_bars = 0
    asset._cycle_counter = 100
    asset._meta_size_multiplier = MagicMock(return_value=1.0)
    asset._cycle_drawdown_pct = 0.0
    asset._kelly_multiplier = 1.0
    asset._last_spread_bps = None
    asset._last_spread_time = 0.0
    asset.position = None
    asset.ticker = "TEST"
    return asset


# ═══════════════════════════════════════════════════════════════════════
# Existing test class — preserve unchanged
# ═══════════════════════════════════════════════════════════════════════


class TestEntryPriceDeviationGate:
    def test_skips_entry_when_deviation_exceeds_threshold(self, mock_asset):
        mock_asset.current_price = 105.0
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_not_called()

    def test_allows_entry_when_deviation_within_threshold(self, mock_asset):
        mock_asset.current_price = 101.0
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()

    def test_allows_entry_when_current_price_is_none(self, mock_asset):
        mock_asset.current_price = None
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()

    def test_allows_entry_when_current_price_is_zero(self, mock_asset):
        mock_asset.current_price = 0.0
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()

    def test_default_threshold_is_two_percent(self, mock_asset):
        mock_asset.current_price = 103.0
        mock_asset.config = {}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_not_called()

    def test_allows_entry_at_threshold_boundary(self, mock_asset):
        mock_asset.current_price = 100.5
        mock_asset.config = {"max_entry_slippage_pct": 1.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()

    def test_skips_entry_just_above_threshold_boundary(self, mock_asset):
        mock_asset.current_price = 101.01
        mock_asset.config = {"max_entry_slippage_pct": 1.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_not_called()

    def test_respects_per_asset_config_override(self, mock_asset):
        mock_asset.current_price = 103.0
        mock_asset.config = {"max_entry_slippage_pct": 5.0}
        service = EntryService()
        service.open_position("long", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()

    def test_short_side_deviation_uses_absolute_value(self, mock_asset):
        mock_asset.current_price = 95.0
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("short", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_not_called()

    def test_short_side_within_threshold_allows_entry(self, mock_asset):
        mock_asset.current_price = 99.0
        mock_asset.config = {"max_entry_slippage_pct": 2.0}
        service = EntryService()
        service.open_position("short", 100.0, "2026-06-17", mock_asset)
        mock_asset.pos_mgr.open.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# New test classes for untested EntryService methods
# ═══════════════════════════════════════════════════════════════════════


class TestEffectiveCapital:
    def test_clamps_growth_at_3x(self):
        svc = EntryService()
        result = svc.effective_capital(initial_capital=100000, capital_base=100000, current_value=500000)
        assert result == 300000

    def test_no_growth_when_value_equals_initial(self):
        svc = EntryService()
        result = svc.effective_capital(initial_capital=100000, capital_base=100000, current_value=100000)
        assert result == 100000

    def test_returns_capital_base_when_initial_zero(self):
        svc = EntryService()
        result = svc.effective_capital(initial_capital=0, capital_base=50000, current_value=100000)
        assert result == 50000

    def test_partial_growth(self):
        svc = EntryService()
        result = svc.effective_capital(initial_capital=100000, capital_base=100000, current_value=150000)
        assert result == 150000


class TestTbVol:
    def test_returns_vol(self):
        svc = EntryService()
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(100)))
        vol = svc.tb_vol(close)
        assert vol > 0
        assert not np.isnan(vol)

    def test_fallback_on_nan(self):
        svc = EntryService()
        close = pd.Series([100.0] * 5)
        vol = svc.tb_vol(close, vol_lookback=21)
        assert vol == 0.01


class TestDrawdownTaper:
    def test_full_size_when_above_start_dd(self):
        svc = EntryService()
        result = svc.drawdown_taper(-0.02, start_dd=-0.05, end_dd=-0.15, min_size=0.5)
        assert result == 1.0

    def test_min_size_when_below_end_dd(self):
        svc = EntryService()
        result = svc.drawdown_taper(-0.20, start_dd=-0.05, end_dd=-0.15, min_size=0.5)
        assert result == 0.5

    def test_linear_interpolation(self):
        svc = EntryService()
        result = svc.drawdown_taper(-0.10, start_dd=-0.05, end_dd=-0.15, min_size=0.5)
        assert 0.5 < result < 1.0


class TestCompositeSizeScalar:
    def test_multiplies_all_components(self, mock_asset):
        svc = EntryService()
        with patch("paper_trading.services.entry_service.compute_effective_multipliers", return_value=(1.0, 2.0, 0.8)):
            result = svc.composite_size_scalar(
                1.5,
                validity_state="GREEN",
                sl_mult=1.0,
                tp_mult=2.0,
                regime_geometry={},
                governance=mock_asset.governance,
                pos_mgr=mock_asset.pos_mgr,
                meta_size_multiplier=0.9,
                drawdown_taper=0.85,
            )
        expected = 0.95 * 1.0 * 1.5 * 0.9 * 0.8 * 0.85
        assert result == pytest.approx(expected)


class TestComputeNotional:
    def test_multiplication(self):
        svc = EntryService()
        result = svc.compute_notional(100000.0, 0.02)
        assert result == 2000.0

    def test_zero_capital(self):
        svc = EntryService()
        result = svc.compute_notional(0.0, 0.02)
        assert result == 0.0


class TestSizingConfig:
    def test_returns_config_when_no_bridge(self, mock_asset):
        svc = EntryService()
        close = pd.Series([100.0, 101.0])
        result = svc.sizing_config(
            close,
            execution_bridge=None,
            ticker="TEST",
            config={"some_key": 42},
            effective_capital_val=100000,
            size_scalar_val=0.02,
        )
        assert result == {"some_key": 42}

    def test_adds_impact_bps_with_bridge(self, mock_asset):
        svc = EntryService()
        close = pd.Series([100.0, 101.0])
        bridge = MagicMock()
        bridge.estimate_impact_bps.return_value = 1.5
        result = svc.sizing_config(
            close,
            execution_bridge=bridge,
            ticker="TEST",
            config={"some_key": 42},
            effective_capital_val=100000,
            size_scalar_val=0.02,
        )
        assert result["impact_bps"] == 1.5
        assert result["some_key"] == 42


class TestCanEnter:
    def test_cross_side_stopout_cooldown(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=95, last_stop_out_side="short",
            config={"stopout_cross_side_cooldown_cycles": 10},
            cooldown_penalty_func=lambda s: 0.0,
            pending_entries={},
            cycle_counter=100,
            last_signal_flip_cycle=0, min_flip_interval_bars=0,
        )
        assert ok is False
        assert "cooldown" in reason

    def test_same_cycle_stopout_lock(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=100, last_stop_out_side="long",
            config={"stopout_cross_side_cooldown_cycles": 0},
            cooldown_penalty_func=lambda s: 0.0,
            pending_entries={},
            cycle_counter=100,
            last_signal_flip_cycle=0, min_flip_interval_bars=0,
        )
        assert ok is False
        assert "same_cycle" in reason

    def test_cooldown_penalty(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=None, last_stop_out_side=None,
            config={},
            cooldown_penalty_func=lambda s: 3.0,
            pending_entries={},
            cycle_counter=100,
            last_signal_flip_cycle=0, min_flip_interval_bars=0,
        )
        assert ok is False
        assert "cooldown" in reason

    def test_pending_entry_exists(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=None, last_stop_out_side=None,
            config={},
            cooldown_penalty_func=lambda s: 0.0,
            pending_entries={"long": MagicMock()},
            cycle_counter=100,
            last_signal_flip_cycle=0, min_flip_interval_bars=0,
        )
        assert ok is False
        assert "pending_entry" in reason

    def test_signal_flip_cooldown(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=None, last_stop_out_side=None,
            config={},
            cooldown_penalty_func=lambda s: 0.0,
            pending_entries={},
            cycle_counter=100,
            last_signal_flip_cycle=98, min_flip_interval_bars=5,
        )
        assert ok is False
        assert "flip_cooldown" in reason

    def test_allows_entry_when_no_gates_active(self, mock_asset):
        svc = EntryService()
        ok, reason = svc.can_enter(
            "long", 100.0,
            last_stop_out_cycle=None, last_stop_out_side=None,
            config={},
            cooldown_penalty_func=lambda s: 0.0,
            pending_entries={},
            cycle_counter=100,
            last_signal_flip_cycle=90, min_flip_interval_bars=5,
        )
        assert ok is True
        assert reason == "ok"


class TestValidatePriceVol:
    def test_returns_none_when_nan_vol(self, mock_asset):
        svc = EntryService()
        data = pd.DataFrame({"close": [100.0] * 10})
        with patch("paper_trading.services.entry_service.estimate_ewm_vol", return_value=np.nan):
            vol, price = svc._validate_price_vol(mock_asset, data, 100.0)
        assert vol is None

    def test_returns_none_when_nan_entry_price(self, mock_asset):
        svc = EntryService()
        data = pd.DataFrame({"close": [100.0] * 10})
        with patch("paper_trading.services.entry_service.estimate_ewm_vol", return_value=0.01):
            vol, price = svc._validate_price_vol(mock_asset, data, np.nan)
        assert vol is None

    def test_returns_none_when_entry_price_zero(self, mock_asset):
        svc = EntryService()
        data = pd.DataFrame({"close": [100.0] * 10})
        with patch("paper_trading.services.entry_service.estimate_ewm_vol", return_value=0.01):
            vol, price = svc._validate_price_vol(mock_asset, data, 0.0)
        assert vol is None


class TestValidateSltpInvariants:
    def test_passes_with_valid_params(self, mock_asset):
        svc = EntryService()
        tp_geo = MagicMock()
        tp_geo.tp_distance = 10.0
        result = svc._validate_sltp_invariants(
            mock_asset, "long", 100.0, 95.0, 110.0, sl_dist=5.0, sl_mult=1.0, tp_mult=2.0, tp_geo=tp_geo,
        )
        assert result is True

    def test_fails_when_rr_below_min(self, mock_asset):
        svc = EntryService()
        tp_geo = MagicMock()
        tp_geo.tp_distance = 1.0
        result = svc._validate_sltp_invariants(
            mock_asset, "long", 100.0, 95.0, 101.0, sl_dist=5.0, sl_mult=1.0, tp_mult=2.0, tp_geo=tp_geo,
        )
        assert result is False


class TestSubmitToBroker:
    def test_returns_early_when_no_bridge(self, mock_asset):
        svc = EntryService()
        mock_asset.execution_bridge = None
        result = svc._submit_to_broker(mock_asset, "long", 100.0, 95.0, 110.0, "GREEN")
        assert result == (100.0, 0.0, None)

    def test_paper_path_calls_sizing_chain(self, mock_asset):
        svc = EntryService()
        bridge = MagicMock()
        bridge._is_real_broker = False
        bridge.fill_price.return_value = (100.5, 0.5, None)
        mock_asset.execution_bridge = bridge
        with patch("shared.sizing_chain.SizingChain.compute") as mock_sc:
            mock_sc.return_value = MagicMock(
                is_viable=True, quantity=0.02, notional=2000, chain_breakdown={},
                effective_cap=100000, size_scalar_applied=0.02, drawdown_taper=1.0,
                position_cap=15000, risk_cap_used=1000,
            )
            result = svc._submit_to_broker(mock_asset, "long", 100.0, 95.0, 110.0, "GREEN")
        assert result[0] == 100.5


class TestComputeStopLoss:
    def test_long_side_static(self, mock_asset):
        svc = EntryService()
        close = pd.Series([100.0, 101.0])
        sl = svc._compute_stop_loss(mock_asset, close, PositionSide.LONG, 100.0, 1.0, 2.0, 0.01)
        assert sl == pytest.approx(100.0 * (1 - 0.01 * 1.0))

    def test_short_side_static(self, mock_asset):
        svc = EntryService()
        close = pd.Series([100.0, 101.0])
        sl = svc._compute_stop_loss(mock_asset, close, PositionSide.SHORT, 100.0, 1.0, 2.0, 0.01)
        assert sl == pytest.approx(100.0 * (1 + 0.01 * 1.0))


class TestComputeTakeProfit:
    def test_uses_existing_tp_geo(self, mock_asset):
        svc = EntryService()
        tp_geo = MagicMock()
        tp_geo.tp_distance = 5.0
        result_geo, final_tp = svc._compute_take_profit(mock_asset, None, PositionSide.LONG, 100.0, 95.0, tp_geo, "GREEN")
        assert final_tp == 105.0

    def test_clamps_negative_tp(self, mock_asset):
        svc = EntryService()
        with patch("paper_trading.entry.tp_compiler.compute_take_profit") as mock_ctp:
            mock_ctp.return_value = MagicMock(tp_distance=-100.0)
            result_geo, final_tp = svc._compute_take_profit(mock_asset, None, PositionSide.LONG, 100.0, 95.0, None, "GREEN")
        assert final_tp > 0


class TestComputeMt5Qty:
    def _make_bridge(self, broker=None):
        if broker is None:
            broker = MagicMock()
        bridge = MagicMock()
        bridge._is_real_broker = True
        bridge.broker = broker
        return bridge

    def _make_broker(self, equity=106.24, min_viable_qty=1000.0):
        broker = MagicMock()
        broker.get_account_summary.return_value = MagicMock(portfolio_value=equity)
        broker.current_mt5_drawdown_pct = MagicMock(return_value=0.0)
        broker.min_viable_qty = MagicMock(return_value=min_viable_qty)
        broker.get_current_price = MagicMock(return_value=1.0)
        return broker

    def test_returns_zero_when_no_broker(self, mock_asset):
        svc = EntryService()
        bridge = MagicMock()
        bridge._is_real_broker = True
        bridge.broker = None
        mock_asset.execution_bridge = bridge
        qty = svc._compute_mt5_qty(mock_asset, 100.0, 95.0)
        assert qty == 0.0

    def test_returns_zero_when_equity_zero(self, mock_asset):
        svc = EntryService()
        broker = self._make_broker(equity=0.0)
        mock_asset.execution_bridge = self._make_bridge(broker)
        qty = svc._compute_mt5_qty(mock_asset, 100.0, 95.0)
        assert qty == 0.0

    # ── 4-mode truth table: mt5_enable_max_risk_per_trade_pct × mt5_bypass_risk_cap_at_min_lot ──
    #
    # | enable | bypass | Expected behaviour                                                  |
    # | ------ | ------ | ------------------------------------------------------------------ |
    # | false  | true   | Risk cap disabled entirely; bump fires to min lot.                 |
    # | false  | false  | Risk cap disabled entirely; bump fires to min lot (bypass ignored).|
    # | true   | true   | Risk cap enabled, but min lot bypassed — bump still fires.          |
    # | true   | false  | Risk cap fully enforced, bump blocked — qty stays at sized value.   |

    def test_mode_enable_false_bypass_true(self, mock_asset):
        """Risk cap disabled (inf), bump fires → qty = min_viable_qty."""
        svc = EntryService()
        mock_asset.config = {
            "mt5_enable_max_risk_per_trade_pct": False,
            "mt5_bypass_risk_cap_at_min_lot": True,
        }
        mock_asset.ticker = "GBPUSD=X"
        broker = self._make_broker(equity=106.24, min_viable_qty=1000.0)
        mock_asset.execution_bridge = self._make_bridge(broker)
        qty = svc._compute_mt5_qty(mock_asset, 1.3332, 1.3239)
        # Risk cap = inf → sizing chain returns full equity notional.
        # Sized qty = 106.24 / 1.3332 ≈ 79.7 < 1000 → bump to 1000.
        assert qty == 1000.0

    def test_mode_enable_false_bypass_false(self, mock_asset):
        """Risk cap disabled, bypass=false ignored → bump fires → qty = min_viable_qty."""
        svc = EntryService()
        mock_asset.config = {
            "mt5_enable_max_risk_per_trade_pct": False,
            "mt5_bypass_risk_cap_at_min_lot": False,
        }
        mock_asset.ticker = "GBPUSD=X"
        broker = self._make_broker(equity=106.24, min_viable_qty=1000.0)
        mock_asset.execution_bridge = self._make_bridge(broker)
        qty = svc._compute_mt5_qty(mock_asset, 1.3332, 1.3239)
        # Risk cap = inf, bypass=false but risk cap is disabled so it's ignored.
        # Sized qty ≈ 79.7 < 1000 → bump to 1000.
        assert qty == 1000.0

    def test_mode_enable_true_bypass_true(self, mock_asset):
        """Risk cap enabled (10%), bypass=true → bump fires (no cap conflict at this equity)."""
        svc = EntryService()
        mock_asset.config = {
            "mt5_enable_max_risk_per_trade_pct": True,
            "mt5_max_risk_per_trade_pct": 10.0,
            "mt5_bypass_risk_cap_at_min_lot": True,
        }
        mock_asset.ticker = "GBPUSD=X"
        broker = self._make_broker(equity=106.24, min_viable_qty=1000.0)
        mock_asset.execution_bridge = self._make_bridge(broker)
        qty = svc._compute_mt5_qty(mock_asset, 1.3332, 1.3239)
        # Risk cap = 10% → max_risk_usd = $10.62.
        # For GBPUSD with sl=0.0093: risk_usd = 0.0093 * (106.24/1.3332) = $0.74
        # $0.74 < $10.62 → cap doesn't bind → notional = $106.24
        # Sized qty = 106.24 / 1.3332 ≈ 79.7 < 1000 → bypass=true → bump to 1000.
        assert qty == 1000.0

    def test_mode_enable_true_bypass_false(self, mock_asset):
        """Risk cap enabled (10%), bypass=false → bump blocked, qty stays at sized value."""
        svc = EntryService()
        mock_asset.config = {
            "mt5_enable_max_risk_per_trade_pct": True,
            "mt5_max_risk_per_trade_pct": 10.0,
            "mt5_bypass_risk_cap_at_min_lot": False,
        }
        mock_asset.ticker = "GBPUSD=X"
        broker = self._make_broker(equity=106.24, min_viable_qty=1000.0)
        mock_asset.execution_bridge = self._make_bridge(broker)
        qty = svc._compute_mt5_qty(mock_asset, 1.3332, 1.3239)
        # Risk cap = 10%, bypass=false.
        # risk_usd = $0.74 < $10.62 → cap doesn't bind at this equity level.
        # Sized qty = 79.7 < 1000 but bypass=false → no bump.
        # Returns the sized qty (≈79.7), NOT bumped to min_viable=1000.
        assert 79.0 < qty < 80.0  # sized qty, not bumped


class TestPollPendingEntries:
    def test_noop_when_no_pending(self, mock_asset):
        svc = EntryService()
        df = pd.DataFrame({"close": [100.0]})
        mock_asset._pending_entries = {}
        svc.poll_pending_entries(df, mock_asset)

    def test_cancels_on_stale_spread(self, mock_asset):
        svc = EntryService()
        df = pd.DataFrame({"close": [100.0]})
        entry = MagicMock()
        entry.is_active = True
        mock_asset._pending_entries = {"long": entry}
        mock_asset._last_spread_bps = 10.0
        mock_asset._last_spread_time = 1.0
        mock_asset.pos_mgr.has_position.return_value = False
        with patch("paper_trading.services.entry_service.time.time", return_value=1000.0):
            with patch("paper_trading.execution.gate_constants.SPREAD_GATE_STALENESS_SECS", 300):
                svc.poll_pending_entries(df, mock_asset)
        assert mock_asset._pending_entries == {}

    def test_cancels_on_profit_lock(self, mock_asset):
        svc = EntryService()
        df = pd.DataFrame({"close": [100.0]})
        entry = MagicMock()
        entry.is_active = True
        mock_asset._pending_entries = {"long": entry}
        mock_asset.current_price = 110.0
        mock_asset.pos_mgr.has_position.return_value = True
        mock_asset.pos_mgr.position_pnl.return_value = 20.0
        mock_asset._last_spread_bps = 5.0
        mock_asset._last_spread_time = 1000.0
        mock_asset.config = {"profit_lock_threshold_pct": 15.0}
        svc.poll_pending_entries(df, mock_asset)
        assert mock_asset._pending_entries == {}

    def test_cancels_sell_only_buy(self, mock_asset):
        svc = EntryService()
        df = pd.DataFrame({"close": [100.0]})
        entry = MagicMock()
        entry.is_active = True
        entry.decision = MagicMock()
        mock_asset._pending_entries = {"long": entry}
        mock_asset.name = "CADCHF"
        mock_asset.pos_mgr.has_position.return_value = False
        with patch("paper_trading.execution.gate_constants.get_sell_only_assets", return_value=frozenset({"CADCHF"})):
            svc.poll_pending_entries(df, mock_asset)
        assert mock_asset._pending_entries == {}


class TestCancelAllPending:
    def test_cancels_all_and_clears(self, mock_asset):
        svc = EntryService()
        e1 = MagicMock()
        e2 = MagicMock()
        mock_asset._pending_entries = {"long": e1, "short": e2}
        svc._cancel_all_pending(mock_asset, reason="test")
        assert mock_asset._pending_entries == {}
        e1.cancel.assert_called_once_with(reason="test")
        e2.cancel.assert_called_once_with(reason="test")


class TestResolveValidityState:
    def test_returns_green_when_validity_sm_green(self, mock_asset):
        svc = EntryService()
        state = svc._resolve_validity_state(mock_asset)
        assert state == "GREEN"

    def test_fallback_to_yellow_when_no_validity_sm(self, mock_asset):
        svc = EntryService()
        mock_asset.validity_sm = None
        state = svc._resolve_validity_state(mock_asset)
        assert state == "YELLOW"
