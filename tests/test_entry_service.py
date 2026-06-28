from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from paper_trading.services.entry_service import EntryService


@pytest.fixture
def mock_asset():
    asset = MagicMock()
    asset.name = "TEST"
    asset.current_price = 105.0
    asset.config = {}
    # price_data for tb_vol
    prices = np.linspace(100, 110, 50)
    asset.price_data = pd.DataFrame({"close": prices}, index=pd.RangeIndex(50))
    # validity
    asset.validity_sm = MagicMock()
    asset.validity_sm.current_state.value = "GREEN"
    # governance
    asset.governance = MagicMock()
    asset.governance._narrative_sl_mult = 1.0
    asset.governance._narrative_size_scalar = 1.0
    asset.governance._liquidity_sl_mult = 1.0
    asset.governance._liquidity_size_scalar = 1.0
    # sltp
    asset.sl_mult = 1.0
    asset.tp_mult = 2.0
    asset.regime_geometry = {}
    asset._entry_archetype = "UNKNOWN"
    asset._structure_detector = MagicMock()
    asset._entry_optimizer = MagicMock()
    # sizing
    asset.initial_capital = 100000
    asset.capital_base = 100000
    asset.current_value = 100000
    asset.pos_mgr.position_size = 0.95
    asset.pos_mgr.exposure_multiplier = 1.0
    # paper path (no mt5)
    asset.execution_bridge = None
    # attribution
    asset._attribution = MagicMock()
    asset._shadow_sltp = None
    asset._pending_entries = {}
    asset._sltp_engine = None
    asset._scale_out_engine = None
    # metadata
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
    return asset


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
