"""Tests for AssetPnlController."""
from unittest.mock import MagicMock

import pytest

from paper_trading.asset_pnl_controller import AssetPnlController


@pytest.fixture
def controller():
    return AssetPnlController(MagicMock())


class TestAssetPnlController:
    def test_update_pnl_no_position(self, controller):
        controller.update_pnl()
        assert controller.total_pnl == 0.0

    def test_update_pnl_with_position(self, controller):
        mock_pos = MagicMock()
        mock_pos.entry_price = 100.0
        mock_pos.side = "long"
        controller._current_price = 105.0
        controller.position = mock_pos
        controller.update_pnl()
        assert controller.total_pnl > 0

    def test_daily_settlement(self, controller):
        controller.update_pnl()
        controller.daily_settle()
        assert controller.daily_pnl >= 0
