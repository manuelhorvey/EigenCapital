from unittest.mock import MagicMock

import pandas as pd
import pytest

from paper_trading.entry.decision import PositionSide, TradeDecision
from paper_trading.execution.decision_pipeline import (
    DecisionContext,
    manage_position,
)
from paper_trading.execution.stacking import (
    _compute_stack_size,
    _contract_size_from_ticker,
    _get_adx,
    _is_trending,
    _last_stack_entry_price,
    _position_unrealized_r,
    _projected_risk_for_stack,
    _should_stack,
    _stack_sl_price,
)
from paper_trading.position.protection import _update_position_protection
from eigencapital.domain.entities.position import PositionIntent, StackLayer

# ── Helpers ─────────────────────────────────────────────────────────────────


def _pos_long(entry=100.0, vol=0.02, size=0.02, layers=None):
    """Position with vol as SL distance pct, size as position notional."""
    if layers is None:
        layers = [StackLayer(entry_price=entry, size=size, timestamp="t0")]
    return PositionIntent(
        side=PositionSide.LONG,
        entry_price=entry,
        entry_date="2026-06-22",
        stop_loss=entry * (1 - vol),
        take_profit=entry * (1 + 2.5 * vol),
        vol=vol,
        layers=layers,
        base_entry_size=size,
    )


def _pos_short(entry=100.0, vol=0.02, size=0.02, layers=None):
    if layers is None:
        layers = [StackLayer(entry_price=entry, size=size, timestamp="t0")]
    return PositionIntent(
        side=PositionSide.SHORT,
        entry_price=entry,
        entry_date="2026-06-22",
        stop_loss=entry * (1 + vol),
        take_profit=entry * (1 - 2.5 * vol),
        vol=vol,
        layers=layers,
        base_entry_size=size,
    )


def _decision(signal="BUY", close=100.0, confidence=0.8):
    return TradeDecision(
        asset="TEST",
        signal=signal,
        label=2,
        confidence=confidence,
        prob_long=confidence,
        prob_short=1.0 - confidence - 0.1,
        prob_neutral=0.1,
        close_price=close,
        timestamp="2026-06-22T12:00:00",
        position_size=1.0,
    )


def _mock_engine(config=None, has_position=True, position=None, current_price=105.0):
    engine = MagicMock()
    engine.name = "TEST"
    engine.current_price = current_price
    engine.config = config or {}
    engine._bar_counter = 42
    engine._cycle_counter = 100
    engine._last_stop_out_cycle = None
    engine._pending_entries = {}
    engine._realized_volatility = 0.15
    engine._close_position = MagicMock(return_value=True)
    engine._close_all_positions = MagicMock(return_value=True)
    engine._can_enter = MagicMock(return_value=(True, "ok"))
    engine.capital_base = 100.0
    engine._open_position = MagicMock()
    engine.position_count = MagicMock(return_value=1 if has_position else 0)
    engine.all_position_dicts = MagicMock(return_value=[])

    # pos_mgr mock with linked position
    pos_mgr = MagicMock()
    pos_mgr.has_position.return_value = has_position
    pos_mgr.position = position
    pos_mgr.position_size = 1.0
    n_layers = len(position.layers) if position and position.layers else 0
    pos_mgr.stack_layer_count.return_value = max(0, n_layers - 1)  # real code excludes base layer
    pos_mgr.max_layers_reached.return_value = n_layers >= 3 if position else False
    pos_mgr.position_pnl.return_value = 5.0
    engine.pos_mgr = pos_mgr

    return engine


def _ctx(engine, decision=None, df=None, new_side=None, flip_allowed=True, current_side=None):
    if decision is None:
        decision = _decision()
    if df is None:
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    if current_side is None:
        current_side = new_side
    return DecisionContext(
        engine=engine,
        decision=decision,
        df=df,
        new_side=new_side,
        flip_allowed=flip_allowed,
        current_side=current_side,
    )


# ── _position_unrealized_r ──────────────────────────────────────────────────


class TestPositionUnrealizedR:
    def test_long_positive(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        engine = _mock_engine(position=pos)
        ctx = _ctx(engine)
        r = _position_unrealized_r(ctx, 103.0)
        assert r == pytest.approx(1.5, rel=1e-3)  # (103-100)/(100*0.02)

    def test_long_negative(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        engine = _mock_engine(position=pos)
        ctx = _ctx(engine)
        r = _position_unrealized_r(ctx, 99.5)
        assert r == pytest.approx(-0.25, rel=1e-3)

    def test_short_positive(self):
        pos = _pos_short(entry=100.0, vol=0.02)
        engine = _mock_engine(position=pos)
        ctx = _ctx(engine)
        r = _position_unrealized_r(ctx, 98.0)
        assert r == pytest.approx(1.0, rel=1e-3)  # (100-98)/(100*0.02)

    def test_short_negative(self):
        pos = _pos_short(entry=100.0, vol=0.02)
        engine = _mock_engine(position=pos)
        ctx = _ctx(engine)
        r = _position_unrealized_r(ctx, 101.0)
        assert r == pytest.approx(-0.5, rel=1e-3)

    def test_zero_position_returns_zero(self):
        engine = _mock_engine(position=None, has_position=False)
        ctx = _ctx(engine)
        assert _position_unrealized_r(ctx, 100.0) == 0.0

    def test_zero_vol_returns_zero(self):
        pos = _pos_long(entry=100.0, vol=0.0)
        engine = _mock_engine(position=pos)
        ctx = _ctx(engine)
        assert _position_unrealized_r(ctx, 105.0) == 0.0


# ── _stack_sl_price ─────────────────────────────────────────────────────────


class TestStackSlPrice:
    def test_long_tightened(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        sl = _stack_sl_price(pos, current_price=102.0, stack_sl_tighten=0.5)
        expected = 102.0 * (1 - 0.02 * 0.5)
        assert sl == pytest.approx(expected, rel=1e-4)

    def test_short_tightened(self):
        pos = _pos_short(entry=100.0, vol=0.02)
        sl = _stack_sl_price(pos, current_price=98.0, stack_sl_tighten=0.3)
        expected = 98.0 * (1 + 0.02 * 0.3)
        assert sl == pytest.approx(expected, rel=1e-4)

    def test_no_tightening(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        sl = _stack_sl_price(pos, current_price=102.0, stack_sl_tighten=1.0)
        expected = 102.0 * (1 - 0.02)
        assert sl == pytest.approx(expected, rel=1e-4)

    def test_zero_tighten(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        sl = _stack_sl_price(pos, current_price=102.0, stack_sl_tighten=0.0)
        assert sl == 102.0  # no distance = at price


# ── _get_adx / _is_trending ────────────────────────────────────────────────


class TestGetAdx:
    def test_adx_present(self):
        df = pd.DataFrame({"adx": [30.0, 28.0, 26.0]})
        engine = _mock_engine()
        ctx = _ctx(engine, df=df)
        assert _get_adx(ctx) == 26.0

    def test_adx_nan_returns_none(self):
        df = pd.DataFrame({"adx": [float("nan")]})
        engine = _mock_engine()
        ctx = _ctx(engine, df=df)
        assert _get_adx(ctx) is None

    def test_adx_missing_column_returns_none(self):
        df = pd.DataFrame({"close": [100.0]})
        engine = _mock_engine()
        ctx = _ctx(engine, df=df)
        assert _get_adx(ctx) is None

    def test_empty_df_returns_none(self):
        df = pd.DataFrame({"adx": []})
        engine = _mock_engine()
        ctx = _ctx(engine, df=df)
        assert _get_adx(ctx) is None


class TestIsTrending:
    def test_trending_above_threshold(self):
        df = pd.DataFrame({"adx": [30.0]})
        engine = _mock_engine(config={"stacking": {"adx_threshold": 25}})
        ctx = _ctx(engine, df=df)
        assert _is_trending(ctx) is True

    def test_not_trending_below_threshold(self):
        df = pd.DataFrame({"adx": [20.0]})
        engine = _mock_engine(config={"stacking": {"adx_threshold": 25}})
        ctx = _ctx(engine, df=df)
        assert _is_trending(ctx) is False

    def test_fallback_on_missing_adx(self):
        df = pd.DataFrame({"close": [100.0]})
        engine = _mock_engine(config={"stacking": {}})
        ctx = _ctx(engine, df=df)
        assert _is_trending(ctx) is True  # fail-open

    def test_default_threshold_25(self):
        df = pd.DataFrame({"adx": [26.0]})
        engine = _mock_engine(config={"stacking": {}})
        ctx = _ctx(engine, df=df)
        assert _is_trending(ctx) is True

    def test_below_default_threshold(self):
        df = pd.DataFrame({"adx": [24.0]})
        engine = _mock_engine(config={"stacking": {}})
        ctx = _ctx(engine, df=df)
        assert _is_trending(ctx) is False


# ── _last_stack_entry_price ────────────────────────────────────────────────


class TestLastStackEntryPrice:
    def test_no_layers_returns_none(self):
        pos = _pos_long(layers=[])
        assert _last_stack_entry_price(pos) is None
        assert _last_stack_entry_price(pos) is None

    def test_returns_last_layer_entry(self):
        layers = [
            StackLayer(entry_price=101.0, size=0.5, timestamp="t1"),
            StackLayer(entry_price=102.0, size=0.3, timestamp="t2"),
        ]
        pos = _pos_long(layers=layers)
        assert _last_stack_entry_price(pos) == 102.0

    def test_none_position_returns_none(self):
        assert _last_stack_entry_price(None) is None


# ── _projected_risk_for_stack (IV-3) ───────────────────────────────────────


class TestProjectedRiskForStack:
    def test_long_projected_risk_lower_with_tighten(self):
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)  # sl=98, total_size=1.0
        engine = _mock_engine(position=pos)
        engine.current_price = 103.0
        engine.config = {"stacking": {"stack_sl_tighten": 0.5}}
        ctx = _ctx(engine)
        risk = _projected_risk_for_stack(ctx, stack_size=0.5)
        # existing_effective = stop_loss = 98.0 (one layer, no risk_floor)
        # stack_sl = 103 * (1 - 0.02*0.5) = 101.97
        # new_effective = max(98.0, 101.97) = 101.97
        # total_after = 1.0 + 0.5 = 1.5
        # projected = 1.5 * max(103 - 101.97, 0) = 1.5 * 1.03 = 1.545
        assert risk == pytest.approx(1.545, rel=1e-3)

    def test_no_position_returns_zero(self):
        engine = _mock_engine(position=None, has_position=False)
        engine.current_price = 103.0
        ctx = _ctx(engine)
        assert _projected_risk_for_stack(ctx, stack_size=0.5) == 0.0

    def test_no_current_price_returns_zero(self):
        pos = _pos_long()
        engine = _mock_engine(position=pos)
        engine.current_price = None
        ctx = _ctx(engine)
        assert _projected_risk_for_stack(ctx, stack_size=0.5) == 0.0


# ── _contract_size_from_ticker ─────────────────────────────────────────────


class TestContractSizeFromTicker:
    def test_fx_pair(self):
        assert _contract_size_from_ticker("AUDUSD=X") == 100_000
        assert _contract_size_from_ticker("EURJPY=X") == 100_000

    def test_gold_futures(self):
        assert _contract_size_from_ticker("GC=F") == 100.0

    def test_index_futures_nq_es(self):
        assert _contract_size_from_ticker("NQ=F") == 20.0
        assert _contract_size_from_ticker("ES=F") == 50.0

    def test_dow_index(self):
        assert _contract_size_from_ticker("^DJI") == 1.0

    def test_crypto(self):
        assert _contract_size_from_ticker("BTC-USD") == 1.0

    def test_fallback(self):
        assert _contract_size_from_ticker("SOMETHING_ELSE") == 1.0
        assert _contract_size_from_ticker("") == 1.0


# ── _compute_stack_size ────────────────────────────────────────────────────


class TestComputeStackSize:
    def test_first_layer_full_multiplier(self):
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0, layers=[])
        engine = _mock_engine(position=pos)
        engine.config = {
            "stacking": {
                "layer_multipliers": [0.8, 0.5, 0.3],
                "stack_target_vol": 0.15,
                "stack_vol_clamp": [0.3, 1.2],
                "size_cap": 1.0,
                "min_viable_position_pct": 0.0001,
                "min_stack_size_factor": 0.5,
                "stack_micro_threshold": 0.0,
            }
        }
        engine.capital_base = 100.0
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine._realized_volatility = 0.15
        size = _compute_stack_size(ctx=_ctx(engine))
        # base_entry_size=1.0, mult=0.8, vol_adj=1.0 (target/realized=1.0)
        # base = 1.0 * 0.8 * 1.0 = 0.8
        # size_cap = min(0.8, 1.0*1.0) = 0.8
        assert size == 0.8

    def test_second_layer_half_multiplier(self):
        layers = [StackLayer(entry_price=101.0, size=0.8, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0, layers=layers)
        engine = _mock_engine(position=pos)
        engine.config = {
            "stacking": {
                "layer_multipliers": [0.8, 0.5, 0.3],
                "stack_target_vol": 0.15,
                "stack_vol_clamp": [0.3, 1.2],
                "size_cap": 1.0,
                "min_viable_position_pct": 0.0001,
                "min_stack_size_factor": 0.5,
                "stack_micro_threshold": 0.0,
            }
        }
        engine.capital_base = 100.0
        engine.pos_mgr.stack_layer_count.return_value = 1
        engine._realized_volatility = 0.15
        size = _compute_stack_size(ctx=_ctx(engine))
        # base_entry_size=1.0, mult=0.5, vol_adj=1.0 → 0.5
        assert size == 0.5

    def test_clamps_to_size_cap(self):
        layers = [StackLayer(entry_price=101.0, size=0.8, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0, layers=layers)
        engine = _mock_engine(position=pos)
        engine.config = {
            "stacking": {
                "layer_multipliers": [0.8, 0.5, 0.3],
                "stack_target_vol": 0.15,
                "stack_vol_clamp": [0.3, 1.2],
                "size_cap": 0.3,
                "min_viable_position_pct": 0.0001,
                "min_stack_size_factor": 0.5,
                "stack_micro_threshold": 0.0,
            }
        }
        engine.capital_base = 100.0
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine._realized_volatility = 0.15
        size = _compute_stack_size(ctx=_ctx(engine))
        # base_entry_size=1.0, mult=0.8, vol_adj=1.0 → 0.8, cap=0.3*1.0=0.3
        assert size == 0.3

    def test_min_stack_factor_zero_disables_floor(self):
        """Regression 2026-07-08: when min_stack_size_factor=0 the obsolete
        USD-notional floor is bypassed entirely.  Producers used min_stack_factor=0.5
        with min_viable_position_pct × capital_base (USD) being compared to
        base_entry_size (lots/units) — a 3500x mismatch in production.
        """
        layers = [StackLayer(entry_price=101.0, size=0.008, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, size=0.01, layers=layers)
        engine = _mock_engine(position=pos)
        engine.config = {
            "stacking": {
                "layer_multipliers": [0.8, 0.5, 0.3],
                "stack_target_vol": 0.15,
                "stack_vol_clamp": [0.3, 1.2],
                "size_cap": 1.0,
                "min_viable_position_pct": 0.01,
                "min_stack_size_factor": 0.0,
                "stack_micro_threshold": 0.0,
            }
        }
        engine.capital_base = 7000.0
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine._realized_volatility = 0.15
        engine.ticker = "AUDUSD=X"
        size = _compute_stack_size(ctx=_ctx(engine))
        assert size == pytest.approx(0.008, rel=1e-3)

    def test_production_default_factor_matches_base(self):
        """With min_stack_size_factor=0.5 and proper unit conversion (notional
        → lots via _contract_size_from_ticker), the floor must NOT inflate
        stack_size above base_entry_size for any asset class.
        Uses realistic prices per asset so the lot conversion is valid.
        """
        test_cases = [
            # (asset_name, base_entry_size, ticker, entry_price, capital_base)
            ("AUDUSD", 0.01, "AUDUSD=X", 0.70, 7000.0),
            ("GC", 0.0162, "GC=F", 4144.0, 490.0),  # 7% of 7000
            ("BTCUSD", 0.02, "BTC-USD", 63146.0, 700.0),  # 10% of 7000
            ("^DJI", 0.01, "^DJI", 53261.0, 700.0),  # 10% of 7000
            ("EURJPY", 0.01, "EURJPY=X", 162.0, 7000.0),
        ]
        for asset_name, base_entry_size, ticker, entry_price, cap_base in test_cases:
            layers = [StackLayer(entry_price=entry_price, size=base_entry_size, timestamp="t1")]
            pos = _pos_long(entry=entry_price, vol=0.02, size=base_entry_size, layers=layers)
            engine = _mock_engine(position=pos, current_price=entry_price)
            engine.config = {
                "stacking": {
                    "layer_multipliers": [0.8, 0.5, 0.3],
                    "stack_target_vol": 0.15,
                    "stack_vol_clamp": [0.3, 1.2],
                    "size_cap": 1.0,
                    "min_viable_position_pct": 0.01,
                    "min_stack_size_factor": 0.5,
                    "stack_micro_threshold": 0.0,
                }
            }
            engine.capital_base = cap_base
            engine.pos_mgr.stack_layer_count.return_value = 0
            engine._realized_volatility = 0.15
            engine.ticker = ticker
            size = _compute_stack_size(ctx=_ctx(engine))
            expected = base_entry_size * 0.8
            assert size == pytest.approx(expected, rel=0.2), (
                f"{asset_name} ({ticker}): stack_size={size} != base*0.8={expected} — floor incorrectly dominating"
            )
            assert size <= base_entry_size * 1.0, (
                f"{asset_name} ({ticker}): stack_size {size} exceeds base_entry_size {base_entry_size}"
            )


# ── _should_stack — 8-gate approval ─────────────────────────────────────────


class TestShouldStack:
    def _make_context(
        self, position, config=None, df=None, current_price=105.0, decision=None, side=None, engine_mutate=None
    ):
        if config is None:
            config = {
                "stacking": {
                    "enabled": True,
                    "max_layers": 3,
                    "min_confidence": 0.60,
                    "min_stack_r": 0.5,
                    "stack_spacing_r": 0.5,
                    "adx_threshold": 25,
                    "stack_sl_tighten": 0.5,
                    "size_cap": 1.0,
                    "layer_multipliers": [0.8, 0.5, 0.3],
                    "stack_target_vol": 0.15,
                    "stack_vol_clamp": [0.3, 1.2],
                    "min_viable_position_pct": 0.0001,
                    "min_stack_size_factor": 0.5,
                    "stack_micro_threshold": 0.0,
                }
            }
        if df is None:
            df = pd.DataFrame({"adx": [30.0]})  # trending
        if decision is None:
            decision = _decision(close=current_price, confidence=0.80)
        if side is None:
            side = PositionSide.LONG
        engine = _mock_engine(position=position, config=config, current_price=current_price)
        engine.capital_base = 100.0
        n_layers = len(position.layers) if position else 0
        engine.pos_mgr.stack_layer_count.return_value = max(0, n_layers - 1)  # real code excludes base layer
        engine.pos_mgr.max_layers_reached.return_value = (
            n_layers >= config["stacking"]["max_layers"] if position else False
        )
        if engine_mutate:
            engine_mutate(engine)
        return _ctx(engine=engine, decision=decision, df=df, new_side=side)

    def test_all_gates_pass(self):
        # IV-3 needs meaningful existing size so tightened SL compensates the added notional
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)  # sl=98, total_size=1.0
        ctx = self._make_context(pos, current_price=105.0)
        assert _should_stack(ctx).should_stack is True

    def test_gate_iv4_min_r_fails(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_context(pos, current_price=100.3)  # only 0.15R
        assert _should_stack(ctx).should_stack is False

    def test_gate_max_layers_fails(self):
        layers = [StackLayer(entry_price=p, size=0.5, timestamp=f"t{i}") for i, p in enumerate([101, 102, 103])]
        pos = _pos_long(entry=100.0, vol=0.02, layers=layers)
        ctx = self._make_context(pos, current_price=105.0)
        assert _should_stack(ctx).should_stack is False

    def test_gate_confidence_fails(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_context(pos, current_price=105.0, decision=_decision(confidence=0.55))
        assert _should_stack(ctx).should_stack is False

    def test_gate_iv8_duplicate_bar_fails(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        pos.last_stack_bar_id = 42  # same as engine._bar_counter
        ctx = self._make_context(pos, current_price=105.0)
        assert _should_stack(ctx).should_stack is False

    def test_gate_iv5_spacing_fails(self):
        layers = [StackLayer(entry_price=104.5, size=0.5, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, layers=layers)
        ctx = self._make_context(pos, current_price=105.0)
        # last_entry=104.5, current=105.0, gap_r = |105-104.5|/(100*0.02) = 0.25 < 0.5
        assert _should_stack(ctx).should_stack is False

    def test_gate_iv5_spacing_passes_with_gap(self):
        layers = [StackLayer(entry_price=102.0, size=0.5, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0, layers=layers)
        ctx = self._make_context(pos, current_price=105.0)
        # last_entry=102.0, current=105.0, gap_r = |105-102|/(100*0.02) = 1.5 >= 0.5
        assert _should_stack(ctx).should_stack is True

    def test_gate_iv6_adx_fails(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        df = pd.DataFrame({"adx": [20.0]})
        ctx = self._make_context(pos, current_price=105.0, df=df)
        assert _should_stack(ctx).should_stack is False

    def test_gate_iv6_adx_passes_when_trending(self):
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        df = pd.DataFrame({"adx": [26.0]})
        ctx = self._make_context(pos, current_price=105.0, df=df)
        assert _should_stack(ctx).should_stack is True

    def test_gate_iv2_size_cap_fails(self):
        """IV-2: stack_size exceeds base_entry_size when size_cap > 1.0 permits it."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine.config["stacking"]["layer_multipliers"] = [1.5, 1.0, 0.5]
        ctx.engine.config["stacking"]["size_cap"] = 2.0
        ctx.engine._realized_volatility = 0.15
        assert _should_stack(ctx).should_stack is False
        # Actually size = 0.8 (layer_mult=0.8 * base_entry=1.0 * vol_adj=1.0) = 0.8
        # base_size = 0.1, so 0.8 > 0.1 -> IV-2 fails

    def test_no_price_returns_false(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_context(pos, current_price=0.0)
        assert _should_stack(ctx).should_stack is False

    def test_none_position_returns_false(self):
        ctx = self._make_context(None, side=PositionSide.LONG)
        # Guard: stack_layer_count on None position would raise, so force handle it
        engine = ctx.engine
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine.pos_mgr.max_layers_reached.return_value = False
        assert _should_stack(ctx).should_stack is False

    def test_gate_9_pending_entry_conflict_fails(self):
        """Gate 9: pending entry for same side blocks stacking."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine._pending_entries = {"long": MagicMock()}
        assert _should_stack(ctx).should_stack is False

    def test_gate_9_no_pending_entry_passes(self):
        """Gate 9: no pending entry does not block stacking."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine._pending_entries = {}
        assert _should_stack(ctx).should_stack is True

    def test_gate_10_stopout_cooldown_fails(self):
        """Gate 10: recent cross-side stopout within cooldown blocks stacking."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine._cycle_counter = 100
        ctx.engine._last_stop_out_cycle = 99  # 1 cycle ago, cooldown=1
        ctx.engine.config["stopout_cross_side_cooldown_cycles"] = 3
        assert _should_stack(ctx).should_stack is False

    def test_gate_10_stopout_cooldown_expired_passes(self):
        """Gate 10: stopout cooldown expired allows stacking."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine._cycle_counter = 100
        ctx.engine._last_stop_out_cycle = 96  # 4 cycles ago, cooldown=3
        ctx.engine.config["stopout_cross_side_cooldown_cycles"] = 3
        assert _should_stack(ctx).should_stack is True

    def test_gate_10_no_stopout_passes(self):
        """Gate 10: no stopout history allows stacking."""
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        ctx = self._make_context(pos, current_price=105.0)
        ctx.engine._last_stop_out_cycle = None
        assert _should_stack(ctx).should_stack is True


# ── _update_position_protection ────────────────────────────────────────────


class TestUpdatePositionProtection:
    def _make_ctx(self, position, config=None, current_price=105.0):
        if config is None:
            config = {
                "stacking": {
                    "breakeven_threshold_r": 0.5,
                    "trail_activate_r": 1.0,
                    "trail_distance_r": 0.5,
                    "trail_step_r": 0.25,
                }
            }
        engine = _mock_engine(position=position, config=config, current_price=current_price)
        return _ctx(engine)

    def test_breakeven_activates_at_threshold(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        # Use a config that trails after breakeven activates
        ctx = self._make_ctx(pos, current_price=101.0)  # 0.5R == breakeven_threshold
        assert pos.breakeven_set is False
        _update_position_protection(ctx)
        assert pos.breakeven_set is True
        # At 1.0R, trail_activate is also 1.0 — not triggered here since 0.5R < 1.0
        assert pos.risk_floor == pos.avg_price  # 100.0

    def test_breakeven_not_activated_below_threshold(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_ctx(pos, current_price=100.3)  # 0.15R < 0.5
        _update_position_protection(ctx)
        assert pos.breakeven_set is False

    def test_breakeven_only_activates_once(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_ctx(pos, current_price=103.0)
        _update_position_protection(ctx)
        assert pos.breakeven_set is True
        risk_floor = pos.risk_floor
        # Second call at same price should not change anything
        _update_position_protection(ctx)
        assert pos.risk_floor == risk_floor

    def test_trailing_stop_on_long(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        pos.peak_price = 108.0  # HWM
        ctx = self._make_ctx(pos, current_price=108.0)  # at peak, 4.0R >= trail_activate=1.0
        _update_position_protection(ctx)
        # Trail distance = trail_distance_r * avg_price * vol = 0.5 * 100 * 0.02 = 1.0
        # new_floor = current_price - trail_distance = 108.0 - 1.0 = 107.0
        expected_floor = 108.0 - 0.5 * 100.0 * 0.02
        assert pos.risk_floor == pytest.approx(expected_floor, rel=1e-4)

    def test_trailing_stop_on_short(self):
        pos = _pos_short(entry=100.0, vol=0.02)
        pos.peak_price = 95.0  # LWM for short
        ctx = self._make_ctx(pos, current_price=95.0)
        _update_position_protection(ctx)
        # Trail distance = trail_distance_r * avg_price * vol = 0.5 * 100 * 0.02 = 1.0
        # new_floor = current_price + trail_distance = 95.0 + 1.0 = 96.0
        expected_floor = 95.0 + 0.5 * 100.0 * 0.02
        assert pos.risk_floor == pytest.approx(expected_floor, rel=1e-4)

    def test_trailing_does_not_tighten_below_activation(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        pos.peak_price = 102.0
        ctx = self._make_ctx(pos, current_price=102.0)  # 1.0R == trail_activate, at peak
        _update_position_protection(ctx)
        # peak_to_current_r = 0 (at peak), so trail should activate
        assert pos.risk_floor > 0

    def test_no_position_does_nothing(self):
        ctx = self._make_ctx(None)
        _update_position_protection(ctx)  # should not raise

    def test_peak_price_tracking_long(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        ctx = self._make_ctx(pos, current_price=106.0)
        _update_position_protection(ctx)
        assert pos.peak_price == 106.0
        ctx2 = self._make_ctx(pos, current_price=104.0)
        _update_position_protection(ctx2)
        assert pos.peak_price == 106.0  # HWM preserved

    def test_peak_price_tracking_short(self):
        pos = _pos_short(entry=100.0, vol=0.02)
        ctx = self._make_ctx(pos, current_price=97.0)
        _update_position_protection(ctx)
        assert pos.peak_price == 97.0
        ctx2 = self._make_ctx(pos, current_price=99.0)
        _update_position_protection(ctx2)
        assert pos.peak_price == 97.0  # LWM preserved


# ── manage_position — stacking path ─────────────────────────────────────────


class TestManagePositionStacking:
    def test_same_side_stacking_enabled_and_approved(self):
        pos = _pos_long(entry=100.0, vol=0.02, size=1.0)
        config = {
            "max_positions_per_asset": 1,
            "stacking": {
                "enabled": True,
                "dry_run": True,
                "max_layers": 3,
                "min_confidence": 0.60,
                "min_stack_r": 0.5,
                "stack_spacing_r": 0.5,
                "adx_threshold": 25,
                "stack_sl_tighten": 0.5,
                "size_cap": 1.0,
                "layer_multipliers": [0.8, 0.5, 0.3],
                "stack_target_vol": 0.15,
                "stack_vol_clamp": [0.3, 1.2],
                "min_viable_position_pct": 0.01,
                "min_stack_size_factor": 0.5,
                "stack_micro_threshold": 0.0,
            },
        }
        engine = _mock_engine(position=pos, config=config, current_price=105.0)
        engine.capital_base = 100.0
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine.pos_mgr.max_layers_reached.return_value = False
        df = pd.DataFrame({"adx": [30.0]})
        ctx = _ctx(
            engine,
            decision=_decision(close=105.0, confidence=0.80),
            df=df,
            new_side=PositionSide.LONG,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        engine._open_position.assert_not_called()  # dry_run

    def test_same_side_stacking_enabled_but_rejected(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        config = {
            "stacking": {
                "enabled": True,
                "max_layers": 3,
                "min_stack_r": 0.5,
            },
            "max_positions_per_asset": 1,
        }
        engine = _mock_engine(position=pos, config=config, current_price=100.3)  # only 0.15R
        engine.pos_mgr.stack_layer_count.return_value = 0
        engine.pos_mgr.max_layers_reached.return_value = False
        ctx = _ctx(
            engine,
            decision=_decision(close=100.3, confidence=0.80),
            new_side=PositionSide.LONG,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        assert engine._close_position.called is False

    def test_same_side_suppress_when_disabled(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        config = {"stacking": {"enabled": False}, "max_positions_per_asset": 1}
        engine = _mock_engine(position=pos, config=config, current_price=105.0)
        ctx = _ctx(
            engine,
            new_side=PositionSide.LONG,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        assert engine._close_position.called is False

    def test_opposite_side_flip_clears_layers(self):
        layers = [StackLayer(entry_price=102.0, size=0.5, timestamp="t1")]
        pos = _pos_long(entry=100.0, vol=0.02, layers=layers)
        config = {"profit_lock_threshold_pct": 15.0}
        engine = _mock_engine(position=pos, config=config, current_price=105.0)
        engine.pos_mgr.stack_layer_count.return_value = 1
        ctx = _ctx(
            engine,
            decision=_decision(signal="SELL", close=105.0),
            new_side=PositionSide.SHORT,
            flip_allowed=True,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.SHORT
        engine._close_all_positions.assert_called_once()

    def test_profit_lock_blocks_opposite_flip(self):
        pos = _pos_long(entry=100.0, vol=0.02)
        config = {"profit_lock_threshold_pct": 10.0}
        engine = _mock_engine(position=pos, config=config, current_price=105.0)
        engine.pos_mgr.position_pnl.return_value = 15.0  # above threshold
        ctx = _ctx(
            engine,
            decision=_decision(signal="SELL", close=105.0),
            new_side=PositionSide.SHORT,
            flip_allowed=True,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()
