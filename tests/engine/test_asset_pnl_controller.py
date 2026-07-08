"""Tests for AssetPnlController using strict fake stubs (no MagicMock for numeric paths).

AssetPnlController is a numeric PnL controller that compares floats and
computes prices. Using MagicMock for `pos_mgr` causes silent arithmetic
failures (MagicMock > float → TypeError at runtime).

Pattern (Option C): use real FakePosMgr + FakeAsset classes that return
numeric values only. Only behavioral dependencies (callbacks, side-effects)
use MagicMock.

Live e2e trading exercises the full controller graph. These tests cover
the no-position path and helper early-exit paths, with deterministic
numeric fixtures.
"""
from unittest.mock import MagicMock

import pytest

from paper_trading.asset_pnl_controller import AssetPnlController


class FakePosition:
    """Real Position-intent-like stub for the no-position early-exit paths."""

    def __init__(self, side="long", entry_price=1.10):
        self.side = side
        self.entry_price = entry_price
        self.entry_date = "2024-01-01"
        self.stop_loss = entry_price * 0.99
        self.take_profit = entry_price * 1.01
        self.vol = 0.01
        # Layers/state needed by PositionManager
        self.layers: list = []
        self.base_entry_size = 0.0
        self.confidence = 0.0
        self.trade_id = ""
        self.breakeven_set = False
        self.risk_floor = 0.0
        self.peak_price = 0.0
        self.last_stack_bar_id = 0


class FakePosMgr:
    """Strict real-class stub for PositionManager — no MagicMock arithmetic.

    `has_position` returns the configured boolean; pos_mgr methods called
    by AssetPnlController return numeric defaults. Tuple values map to
    PropertyMock-style expectations.
    """

    def __init__(self, has_pos=False, position=None):
        self.position = position
        self._has_pos = has_pos
        self._position = position
        self.current_value = 10_000.0
        self.position_size = 1.0
        self.exposure_multiplier = 1.0

    def has_position(self):
        return self._has_pos

    def position_pnl(self, current_price):
        if self._position is None or current_price is None:
            return 0.0
        if self._position.entry_price <= 0:
            return 0.0
        return ((current_price - self._position.entry_price) / self._position.entry_price) * 100

    def compute_daily_pnl(self, *args, **kwargs):
        return 0.0


class FakeAsset:
    """Strict real-class stub for AssetEngine — no MagicMock fallback.

    Provides only the attributes/methods touched by update_pnl and its
    helper chain. The numeric `mtm_value` property returns the configured
    peak_value (or pos_mgr.current_value + pnl when has_pos is True).
    """

    def __init__(self, peak: float = 10_000.0, has_pos: bool = False):
        self.peak_value = peak
        self.initial_capital = peak
        self.current_value = peak
        self.current_price = 1.10
        self.config = {
            "max_holding_days": 30,
            "adaptive_exit": {"enabled": False},
            "dynamic_sltp": {"enabled": False},
        }
        self.reentry_positions: list = []
        self.reentry_trade_ids: list = []
        self.batches: dict = {}
        self._shadow_sltp = None
        self._tp_reconciled = False
        self._initial_sl = None
        # _settle_daily_pnl early-returns if signal_data is None or has <2 rows.
        self.signal_data = None
        self.trades: list = []
        self.daily_pnl_history: list[float] = []
        self.total_pnl = 0.0
        self._initial_settlement_done = True

        # Position manager — real fake, not MagicMock
        self._position = FakePosition() if has_pos else None
        self.pos_mgr = FakePosMgr(has_pos=has_pos, position=self._position)

        # Validity FSM stub — only used for state reads, never numeric
        self.validity_sm = MagicMock()
        self.validity_sm.current_state.value = "YELLOW"

    def _ensure_position_synced(self):
        """Class-level stub so the controller can call it without raising."""
        return None

    @property
    def mtm_value(self) -> float:
        """Real numeric property — no MagicMock fallback path."""
        if self.pos_mgr._has_pos and self._position is not None:
            pnl_pct = (self.current_price - self._position.entry_price) / self._position.entry_price
            return float(self.initial_capital * (1.0 + pnl_pct))
        return float(self.peak_value)


@pytest.fixture
def fake_asset_no_pos():
    return FakeAsset(peak=10_000.0, has_pos=False)


@pytest.fixture
def fake_asset_long():
    return FakeAsset(peak=11_000.0, has_pos=True)


class TestAssetPnlControllerInstantiation:
    def test_class_instantiable(self):
        ctrl = AssetPnlController(MagicMock())
        assert ctrl.asset is not None

    def test_class_has_update_pnl(self):
        ctrl = AssetPnlController(MagicMock())
        assert callable(ctrl.update_pnl)


class TestAssetPnlControllerNoPositionPath:
    def test_mtm_value_returns_float_no_position(self, fake_asset_no_pos):
        ctrl = AssetPnlController(fake_asset_no_pos)
        assert isinstance(ctrl.mtm_value, float)
        assert ctrl.mtm_value == 10_000.0

    def test_update_pnl_no_position_does_not_raise(self, fake_asset_no_pos):
        ctrl = AssetPnlController(fake_asset_no_pos)
        ctrl.update_pnl()

    def test_update_pnl_no_position_does_not_modify_peak(self, fake_asset_no_pos):
        ctrl = AssetPnlController(fake_asset_no_pos)
        before = fake_asset_no_pos.peak_value
        ctrl.update_pnl()
        # peak_value stays at 10_000.0 since mtm == peak
        assert fake_asset_no_pos.peak_value == before


class TestAssetPnlControllerHelpers:
    def test_track_running_excursion_no_position_no_raise(self, fake_asset_no_pos):
        """No position → early return in excursion tracker. No exception."""
        ctrl = AssetPnlController(fake_asset_no_pos)
        ctrl._track_running_excursion(fake_asset_no_pos)

    def test_reconcile_position_tp_when_disabled(self, fake_asset_no_pos):
        """dynamic_sltp off in config → early return, no exception."""
        ctrl = AssetPnlController(fake_asset_no_pos)
        ctrl._reconcile_position_tp(fake_asset_no_pos)


class TestPosMgrStubContract:
    """Verify the FakePosMgr numeric contract — addresses the original failure.

    Before: MagicMock for pos_mgr → arithmetic failures (MagicMock > float).
    After: FakePosMgr returns numeric defaults → deterministic behavior.
    """

    def test_pos_mgr_has_position_returns_bool(self, fake_asset_no_pos):
        assert isinstance(fake_asset_no_pos.pos_mgr.has_position(), bool)
        assert fake_asset_no_pos.pos_mgr.has_position() is False

    def test_pos_mgr_position_pnl_returns_float(self, fake_asset_no_pos):
        result = fake_asset_no_pos.pos_mgr.position_pnl(1.10)
        assert isinstance(result, float)

    def test_mtm_value_no_compare_to_mock(self, fake_asset_no_pos):
        # Direct exercise of the previous failure path
        ctrl = AssetPnlController(fake_asset_no_pos)
        mtm = ctrl.mtm_value
        # The line that failed in the original bug: mtm > peak_value
        result = mtm > fake_asset_no_pos.peak_value
        assert isinstance(result, bool)


class TestSetCapitalBase:
    """Regression: set_capital_base must shift initial_capital, current_value,
    and peak_value on both the asset and pos_mgr by the rebalance delta.

    Before the fix, only current_value was adjusted — initial_capital and
    peak_value stayed at their old values, causing false drawdown spikes
    and inflated return metrics after rebalancing.
    """

    @staticmethod
    def _init_state(asset, value: float = 10_000.0):
        """Set the 7 fields that set_capital_base adjusts to one value."""
        asset.capital_base = value
        asset.initial_capital = value
        asset.current_value = value
        asset.peak_value = value
        asset.pos_mgr.initial_capital = value
        asset.pos_mgr.current_value = value
        asset.pos_mgr.peak_value = value

    def test_adjusts_all_fields_by_delta_downward(self):
        """Capital reduction: delta = -$2,000, all fields shift by same amount."""
        asset = FakeAsset(peak=10_000.0)
        ctrl = AssetPnlController(asset)
        self._init_state(asset, 10_000.0)

        ctrl.set_capital_base(8_000.0)  # delta = -2,000

        assert asset.capital_base == 8_000.0
        assert asset.initial_capital == 8_000.0
        assert asset.current_value == 8_000.0
        assert asset.peak_value == 8_000.0
        assert asset.pos_mgr.initial_capital == 8_000.0
        assert asset.pos_mgr.current_value == 8_000.0
        assert asset.pos_mgr.peak_value == 8_000.0

    def test_adjusts_all_fields_by_delta_upward(self):
        """Capital increase: delta = +$3,000, all fields shift by same amount."""
        asset = FakeAsset(peak=10_000.0)
        ctrl = AssetPnlController(asset)
        self._init_state(asset, 10_000.0)

        ctrl.set_capital_base(13_000.0)  # delta = +3,000

        assert asset.capital_base == 13_000.0
        assert asset.initial_capital == 13_000.0
        assert asset.current_value == 13_000.0
        assert asset.peak_value == 13_000.0
        assert asset.pos_mgr.initial_capital == 13_000.0
        assert asset.pos_mgr.current_value == 13_000.0
        assert asset.pos_mgr.peak_value == 13_000.0

    def test_zero_delta_no_change(self):
        """Calling set_capital_base with the same value is a no-op."""
        asset = FakeAsset(peak=10_000.0)
        ctrl = AssetPnlController(asset)
        self._init_state(asset, 10_000.0)

        ctrl.set_capital_base(10_000.0)  # delta = 0

        assert asset.capital_base == 10_000.0
        assert asset.initial_capital == 10_000.0
        assert asset.current_value == 10_000.0
        assert asset.peak_value == 10_000.0
        assert asset.pos_mgr.initial_capital == 10_000.0
        assert asset.pos_mgr.current_value == 10_000.0
        assert asset.pos_mgr.peak_value == 10_000.0
