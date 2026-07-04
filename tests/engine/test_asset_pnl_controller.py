"""Smoke tests for AssetPnlController — verifies module imports and class exists."""
import pytest

from paper_trading.asset_pnl_controller import AssetPnlController


class TestAssetPnlControllerImports:
    def test_class_instantiable(self):
        """AssetPnlController should accept an asset reference."""
        # Use a MagicMock to avoid full asset graph wiring for this smoke test
        from unittest.mock import MagicMock
        ctrl = AssetPnlController(MagicMock())
        assert ctrl.asset is not None

    def test_class_has_update_pnl(self):
        from unittest.mock import MagicMock
        ctrl = AssetPnlController(MagicMock())
        assert callable(getattr(ctrl, "update_pnl", None))

    def test_class_has_daily_settle(self):
        from unittest.mock import MagicMock
        ctrl = AssetPnlController(MagicMock())
        # daily_settle is internal — verify via _settle_daily_pnl method
        assert callable(getattr(ctrl, "_settle_daily_pnl", None))
