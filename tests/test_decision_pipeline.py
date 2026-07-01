from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from paper_trading.entry.decision import PositionSide, SignalType, TradeDecision
from paper_trading.execution.decision_pipeline import (
    DecisionContext,
    DEFAULT_STAGES,
    apply_adx_entry_gate,
    apply_bar_jump_suppression,
    apply_confidence_gate,
    apply_first_cycle_suppression,
    apply_kelly_sizing,
    apply_risk_off_suppression,
    apply_sell_only_filter,
    apply_session_gate,
    apply_signal_hysteresis,
    apply_spread_gate,
    build_entry_artifacts,
    manage_position,
    resolve_signal,
    route_execution_policy,
    run_decision_pipeline,
    store_prediction_metadata,
    update_prob_history,
    update_regime_bar_counter,
)
from quorrin.domain.entities.position import PositionIntent, StackLayer


def _mock_engine(current_price=100.0, config=None, pnl=5.0, has_position=True, name="TEST"):
    engine = MagicMock()
    engine.name = name
    engine.current_price = current_price
    engine.config = config or {}
    engine.pos_mgr.has_position.return_value = has_position
    engine.pos_mgr.current_side.return_value = None
    engine.pos_mgr.position_pnl.return_value = pnl
    engine.pos_mgr.stack_layer_count.return_value = 0
    engine._close_position = MagicMock(return_value=True)
    engine._can_enter.return_value = (True, "ok")
    engine.pos_mgr.position = (
        PositionIntent(
            side=PositionSide.LONG,
            entry_price=current_price or 100.0,
            entry_date="2026-06-22",
            stop_loss=(current_price or 100.0) * 0.98,
            take_profit=(current_price or 100.0) * 1.05,
            vol=0.02,
            layers=[StackLayer(entry_price=current_price or 100.0, size=0.02, timestamp="t0")],
            base_entry_size=0.02,
        )
        if has_position
        else None
    )
    engine._cycle_counter = 10
    engine._signal_chain = []
    engine._wal_writer = None
    engine._model_hash = "testhash1234"
    engine._last_gates_trace = {}
    engine._suppress_until = 0.0
    engine._risk_off = False
    engine._last_spread_bps = None
    engine._last_spread_time = 0.0
    engine._spread_tier = "fx_cross"
    engine._evaluate_flip_gate.return_value = (True, "ok")
    engine._calibration_applied = False
    engine._current_regime = "neutral"
    engine._last_regime_label = "neutral"
    engine._regime_bar_counter = 0
    engine.prob_history = []
    engine._log_confidence_buckets = MagicMock()
    return engine


def _decision(signal="BUY"):
    return TradeDecision(
        asset="TEST",
        signal=signal,
        label=2,
        confidence=80.0,
        prob_long=0.80,
        prob_short=0.10,
        prob_neutral=0.10,
        close_price=100.0,
        timestamp="2026-06-17",
        position_size=1.0,
    )


def _ctx(engine=None, decision=None, new_side=None, df=None):
    if engine is None:
        engine = _mock_engine()
    if decision is None:
        decision = _decision()
    if df is None:
        df = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]})
    return DecisionContext(
        engine=engine,
        decision=decision,
        df=df,
        new_side=new_side,
        current_side=engine.pos_mgr.current_side(),
    )


# ═══════════════════════════════════════════════════════════════════════
# Existing test class — preserve
# ═══════════════════════════════════════════════════════════════════════


class TestProfitLockGate:
    def test_blocks_flip_when_pnl_exceeds_threshold(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()

    def test_allows_flip_when_pnl_below_threshold(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=5.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_called_once()

    def test_allows_flip_when_no_position_exists(self):
        engine = _mock_engine(has_position=False)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_not_called()

    def test_noop_when_new_side_matches_current(self):
        engine = _mock_engine(pnl=20.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.LONG
        manage_position(ctx)
        assert ctx.new_side is None

    def test_noop_when_new_side_is_none(self):
        engine = _mock_engine(pnl=20.0)
        ctx = _ctx(engine=engine, new_side=None)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side is None

    def test_default_threshold_15_percent(self):
        engine = _mock_engine(config={}, pnl=20.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side is None

    def test_allows_flip_when_pnl_below_default(self):
        engine = _mock_engine(config={}, pnl=10.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_proceeds_when_current_price_is_none(self):
        engine = _mock_engine(current_price=None, config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_proceeds_when_current_price_is_zero(self):
        engine = _mock_engine(current_price=0.0, config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_respects_per_asset_threshold_override(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 25.0}, pnl=20.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_blocked_flip_does_not_enter_new_position(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# New test classes for remaining stages
# ═══════════════════════════════════════════════════════════════════════


class TestResolveSignal:
    def test_buy_maps_to_long(self):
        ctx = _ctx(decision=_decision("BUY"))
        resolve_signal(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_sell_maps_to_short(self):
        ctx = _ctx(decision=_decision("SELL"))
        resolve_signal(ctx)
        assert ctx.new_side == PositionSide.SHORT

    def test_hold_maps_to_none(self):
        ctx = _ctx(decision=_decision("HOLD"))
        resolve_signal(ctx)
        assert ctx.new_side is None


class TestStorePredictionMetadata:
    def test_stores_metadata_on_engine(self):
        engine = _mock_engine()
        ctx = _ctx(engine=engine)
        store_prediction_metadata(ctx)
        assert engine._last_label == 2
        assert engine._last_confidence == 80.0
        assert engine._last_prob_long == 0.80
        assert engine._entry_archetype is not None


class TestApplyConfidenceGate:
    def test_blocks_when_below_min_confidence(self):
        engine = _mock_engine(config={"min_confidence": 90.0})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_confidence_gate(ctx)
        assert ctx.new_side is None

    def test_allows_when_above_min_confidence(self):
        engine = _mock_engine(config={"min_confidence": 50.0})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_confidence_gate(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_noop_when_new_side_none(self):
        ctx = _ctx(new_side=None)
        apply_confidence_gate(ctx)
        assert ctx.new_side is None


class TestApplySignalHysteresis:
    def test_blocks_flip_when_insufficient_agreement(self):
        engine = _mock_engine()
        engine._signal_chain = [PositionSide.SHORT, PositionSide.SHORT, PositionSide.SHORT]
        engine.pos_mgr.has_position.return_value = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        apply_signal_hysteresis(ctx)
        assert ctx.new_side is None

    def test_allows_flip_when_sufficient_agreement(self):
        engine = _mock_engine()
        engine._signal_chain = [PositionSide.LONG, PositionSide.LONG, PositionSide.LONG]
        engine.pos_mgr.has_position.return_value = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.SHORT
        apply_signal_hysteresis(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_skips_hysteresis_no_position(self):
        engine = _mock_engine(has_position=False)
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        ctx.current_side = PositionSide.LONG
        apply_signal_hysteresis(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_noop_when_new_side_none(self):
        ctx = _ctx(new_side=None)
        apply_signal_hysteresis(ctx)
        assert ctx.new_side is None


class TestApplySellOnlyFilter:
    @patch("paper_trading.execution.decision_pipeline.get_sell_only_assets", return_value=frozenset({"TEST"}))
    def test_suppresses_buy_on_sell_only_asset(self, mock_soa):
        engine = _mock_engine(name="TEST")
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_sell_only_filter(ctx)
        assert ctx.new_side is None

    @patch("paper_trading.execution.decision_pipeline.get_sell_only_assets", return_value=frozenset({"TEST"}))
    def test_allows_sell_on_sell_only_asset(self, mock_soa):
        engine = _mock_engine(name="TEST")
        ctx = _ctx(engine=engine, new_side=PositionSide.SHORT)
        apply_sell_only_filter(ctx)
        assert ctx.new_side == PositionSide.SHORT

    @patch("paper_trading.execution.decision_pipeline.get_sell_only_assets", return_value=frozenset({"OTHER"}))
    def test_noop_on_non_sell_only_asset(self, mock_soa):
        engine = _mock_engine(name="EURUSD")
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_sell_only_filter(ctx)
        assert ctx.new_side == PositionSide.LONG

    @patch("paper_trading.execution.decision_pipeline.get_sell_only_assets", return_value=frozenset({"TEST"}))
    def test_force_closes_existing_long(self, mock_soa):
        engine = _mock_engine(name="TEST", current_price=100.0)
        engine.pos_mgr.has_position.return_value = True
        engine.pos_mgr.current_side.return_value = PositionSide.LONG
        ctx = _ctx(engine=engine, new_side=PositionSide.SHORT)
        apply_sell_only_filter(ctx)
        engine._close_position.assert_called_once()


class TestApplyBarJumpSuppression:
    def test_suppresses_when_suppress_until_active(self, monkeypatch):
        monkeypatch.setattr("paper_trading.execution.decision_pipeline.time.time", lambda: 500.0)
        engine = _mock_engine()
        engine._suppress_until = 1000.0
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_bar_jump_suppression(ctx)
        assert ctx.new_side is None

    def test_no_suppression_when_expired(self, monkeypatch):
        monkeypatch.setattr("paper_trading.execution.decision_pipeline.time.time", lambda: 2000.0)
        engine = _mock_engine()
        engine._suppress_until = 1000.0
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_bar_jump_suppression(ctx)
        assert ctx.new_side == PositionSide.LONG


class TestApplyRiskOffSuppression:
    def test_suppresses_audusd_when_risk_off(self):
        engine = _mock_engine(name="AUDUSD")
        engine._risk_off = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_risk_off_suppression(ctx)
        assert ctx.new_side is None

    def test_no_suppression_when_not_audusd(self):
        engine = _mock_engine(name="EURUSD")
        engine._risk_off = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_risk_off_suppression(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_no_suppression_when_risk_off_false(self):
        engine = _mock_engine(name="AUDUSD")
        engine._risk_off = False
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_risk_off_suppression(ctx)
        assert ctx.new_side == PositionSide.LONG


class TestApplySpreadGate:
    @patch("paper_trading.config_manager.get_config")
    @patch("paper_trading.execution.decision_pipeline.time.time", return_value=2000.0)
    def test_blocks_when_spread_exceeds_threshold(self, mock_time, mock_get_config):
        mock_get_config.return_value = MagicMock(defaults={"spread_gate": {"enabled": True}})
        engine = _mock_engine()
        engine._last_spread_bps = 25.0
        engine._last_spread_time = 1990.0
        engine._spread_tier = "fx_cross"
        engine._cycle_counter = 1000
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_spread_gate(ctx)
        assert ctx.new_side is None

    @patch("paper_trading.config_manager.get_config")
    @patch("paper_trading.execution.decision_pipeline.time.time", return_value=2000.0)
    def test_allows_when_spread_within_threshold(self, mock_time, mock_get_config):
        mock_get_config.return_value = MagicMock(defaults={"spread_gate": {"enabled": True}})
        engine = _mock_engine()
        engine._last_spread_bps = 5.0
        engine._last_spread_time = 1990.0
        engine._spread_tier = "fx_major"
        engine._cycle_counter = 1000
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_spread_gate(ctx)
        assert ctx.new_side == PositionSide.LONG

    @patch("paper_trading.config_manager.get_config")
    @patch("paper_trading.execution.decision_pipeline.time.time", return_value=2000.0)
    def test_observe_mode_does_not_block(self, mock_time, mock_get_config):
        mock_get_config.return_value = MagicMock(defaults={"spread_gate": {"enabled": True}})
        engine = _mock_engine()
        engine._last_spread_bps = 100.0
        engine._last_spread_time = 1990.0
        engine._spread_tier = "fx_cross"
        engine._cycle_counter = 5
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_spread_gate(ctx)
        assert ctx.new_side == PositionSide.LONG  # observe mode doesn't block


class TestApplySessionGate:
    def test_blocks_outside_session_window(self, monkeypatch):
        monkeypatch.setattr(
            "paper_trading.execution.decision_pipeline.datetime",
            MagicMock(now=lambda tz: MagicMock(hour=2)),
        )
        engine = _mock_engine()
        engine._spread_tier = "fx_major"
        engine._cycle_counter = 1000
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_session_gate(ctx)
        assert ctx.new_side is None

    def test_observe_mode_does_not_block(self, monkeypatch):
        monkeypatch.setattr(
            "paper_trading.execution.decision_pipeline.datetime",
            MagicMock(now=lambda tz: MagicMock(hour=2)),
        )
        engine = _mock_engine()
        engine._spread_tier = "fx_major"
        engine._cycle_counter = 5
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_session_gate(ctx)
        assert ctx.new_side == PositionSide.LONG  # observe

    def test_noop_when_new_side_none(self):
        ctx = _ctx(new_side=None)
        apply_session_gate(ctx)
        assert ctx.new_side is None


class TestApplyAdxEntryGate:
    def test_blocks_when_adx_below_threshold(self):
        engine = _mock_engine(config={"adx_entry_gate": {"enabled": True, "adx_threshold": 20, "observe_only": False}})
        df = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [15.0]})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG, df=df)
        apply_adx_entry_gate(ctx)
        assert ctx.new_side is None

    def test_allows_when_adx_above_threshold(self):
        engine = _mock_engine(config={"adx_entry_gate": {"enabled": True, "adx_threshold": 20, "observe_only": False}})
        df = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG, df=df)
        apply_adx_entry_gate(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_noop_when_gate_disabled(self):
        engine = _mock_engine(config={"adx_entry_gate": {"enabled": False}})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_adx_entry_gate(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_observe_does_not_block(self):
        engine = _mock_engine(config={"adx_entry_gate": {"enabled": True, "observe_only": True}})
        df = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [15.0]})
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG, df=df)
        apply_adx_entry_gate(ctx)
        assert ctx.new_side == PositionSide.LONG


class TestApplyFirstCycleSuppression:
    def test_aborts_on_cycle_0(self):
        engine = _mock_engine()
        engine._cycle_counter = 0
        ctx = _ctx(engine=engine)
        apply_first_cycle_suppression(ctx)
        assert ctx.abort is True

    def test_aborts_on_cycle_1(self):
        engine = _mock_engine()
        engine._cycle_counter = 1
        ctx = _ctx(engine=engine)
        apply_first_cycle_suppression(ctx)
        assert ctx.abort is True

    def test_no_abort_on_cycle_2(self):
        engine = _mock_engine()
        engine._cycle_counter = 2
        ctx = _ctx(engine=engine)
        apply_first_cycle_suppression(ctx)
        assert ctx.abort is False


class TestApplyKellySizing:
    def test_skips_when_kelly_not_enabled(self):
        engine = _mock_engine(config={"kelly": {"enabled": False}})
        engine._calibration_applied = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_kelly_sizing(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_skips_when_calibration_not_applied(self):
        engine = _mock_engine(config={"kelly": {"enabled": True}})
        engine._calibration_applied = False
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        apply_kelly_sizing(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_blocks_when_kelly_multiplier_zero(self):
        engine = _mock_engine(config={"kelly": {"enabled": True}})
        engine._calibration_applied = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        with patch("shared.kelly.compute_kelly_multiplier", return_value=0.0):
            apply_kelly_sizing(ctx)
        assert ctx.new_side is None

    def test_sets_kelly_multiplier_when_positive(self):
        engine = _mock_engine(config={"kelly": {"enabled": True}})
        engine._calibration_applied = True
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        with patch("shared.kelly.compute_kelly_multiplier", return_value=0.5):
            apply_kelly_sizing(ctx)
        assert engine._kelly_multiplier == 0.5
        assert ctx.new_side == PositionSide.LONG


class TestUpdateRegimeBarCounter:
    def test_resets_on_regime_change(self):
        engine = _mock_engine()
        engine._current_regime = "trending"
        engine._last_regime_label = "ranging"
        ctx = _ctx(engine=engine)
        update_regime_bar_counter(ctx)
        assert engine._regime_bar_counter == 1
        assert engine._last_regime_label == "trending"

    def test_increments_on_same_regime(self):
        engine = _mock_engine()
        engine._current_regime = "trending"
        engine._last_regime_label = "trending"
        engine._regime_bar_counter = 5
        ctx = _ctx(engine=engine)
        update_regime_bar_counter(ctx)
        assert engine._regime_bar_counter == 6


class TestUpdateProbHistory:
    def test_appends_and_caps(self):
        engine = _mock_engine()
        engine.prob_history = []
        ctx = _ctx(engine=engine)
        update_prob_history(ctx)
        assert len(engine.prob_history) == 1
        assert engine.prob_history[0]["signal"] == "BUY"


class TestBuildEntryArtifacts:
    def test_entry_action_dynamic(self):
        engine = _mock_engine()
        engine._structure_detector = MagicMock()
        engine._structure_detector.detect.return_value = MagicMock()
        engine._entry_optimizer = MagicMock()
        engine._entry_optimizer.evaluate.return_value = "ENTER"
        engine._tb_vol = MagicMock(return_value=0.01)
        engine.validity_sm = MagicMock()
        engine.validity_sm.current_state.value = "GREEN"
        engine.regime_geometry = {}
        engine.governance = MagicMock()
        engine.governance._narrative_sl_mult = 1.0
        engine.governance._narrative_size_scalar = 1.0
        engine.governance._liquidity_sl_mult = 1.0
        engine.governance._liquidity_size_scalar = 1.0
        engine.sl_mult = 1.0
        engine.tp_mult = 2.0
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        build_entry_artifacts(ctx)
        assert engine._entry_action == "ENTER"


class TestRouteExecutionPolicy:
    def test_skips_when_new_side_none(self):
        engine = _mock_engine()
        ctx = _ctx(engine=engine, new_side=None)
        route_execution_policy(ctx)

    def test_calls_open_position_on_enter(self):
        engine = _mock_engine()
        engine._structure = MagicMock()
        engine._entry_action = "ENTER"
        engine._tp_geo = MagicMock()
        engine._deferred_entry = None
        engine._execution_policy = MagicMock()
        engine._execution_policy.handle.return_value = MagicMock(action="ENTER", reason="ok", entry_plan=None, exit_plan=None)
        engine._open_position = MagicMock()
        engine.position = None
        ctx = _ctx(engine=engine, new_side=PositionSide.LONG)
        route_execution_policy(ctx)
        engine._open_position.assert_called_once()


class TestRunDecisionPipeline:
    def test_returns_buy_when_long(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        engine._wal_writer = MagicMock()
        result = run_decision_pipeline(engine, _decision("BUY"), pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]}))
        assert result == "BUY"

    def test_returns_sell_when_short(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        engine._wal_writer = MagicMock()
        result = run_decision_pipeline(engine, _decision("SELL"), pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]}))
        assert result == "SELL"

    def test_returns_none_when_flat(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        engine._wal_writer = MagicMock()
        result = run_decision_pipeline(engine, _decision("HOLD"), pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]}))
        assert result is None

    def test_aborts_on_first_cycle(self):
        engine = _mock_engine()
        engine._cycle_counter = 0
        engine._wal_writer = MagicMock()
        result = run_decision_pipeline(engine, _decision("BUY"), pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]}))
        assert result is None

    def test_writes_wal_decision_output(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        engine._wal_writer = MagicMock()
        run_decision_pipeline(engine, _decision("BUY"), pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "adx": [25.0]}))
        assert engine._wal_writer.write.called
        call_args = engine._wal_writer.write.call_args[0]
        assert call_args[0] == "decision_output"

    def test_custom_stages(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        calls = []

        def tracking_stage(ctx):
            calls.append(1)

        run_decision_pipeline(engine, _decision("BUY"), pd.DataFrame(), stages=[tracking_stage])
        assert len(calls) == 1

    def test_abort_stops_pipeline(self):
        engine = _mock_engine()
        engine._cycle_counter = 10
        calls = []

        def abort_stage(ctx):
            ctx.abort = True

        def should_not_run(ctx):
            calls.append(1)

        run_decision_pipeline(engine, _decision("BUY"), pd.DataFrame(), stages=[abort_stage, should_not_run])
        assert len(calls) == 0


class TestDefaultStages:
    def test_default_stages_are_callable(self):
        for stage in DEFAULT_STAGES:
            assert callable(stage)

    def test_default_stages_has_expected_count(self):
        assert len(DEFAULT_STAGES) == 22
