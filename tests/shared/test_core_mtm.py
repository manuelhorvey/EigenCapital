import unittest
from unittest.mock import MagicMock
from paper_trading.asset_engine import AssetEngine
from paper_trading.entry.decision import PositionIntent


class TestCoreAssetMTM(unittest.TestCase):
    def setUp(self):
        # Mocking necessary components for AssetEngine
        self.ticker = "AAPL"
        self.name = "AAPL_Asset"
        self.contract = "EQUITY"
        self.initial_capital = 10000.0

        # Mock config
        mock_config = MagicMock()
        mock_config.position_size = 0.95
        mock_config.get.return_value = {}

        # Mock StateStore
        mock_store = MagicMock()

        # Mock contract
        mock_contract = MagicMock()
        mock_contract.features = ["feat1", "feat2"]

        # Initialize AssetEngine with mocked components
        from paper_trading.execution_context import ExecutionContext

        ctx = ExecutionContext(state_store=mock_store, engine_config=mock_config)
        with unittest.mock.patch("paper_trading.asset_engine.ImportanceStore"):
            with unittest.mock.patch("paper_trading.asset_engine.PSIMonitor"):
                with unittest.mock.patch("paper_trading.asset_engine.RegimeClassifier"):
                    with unittest.mock.patch("paper_trading.asset_engine.build_dynamic_sltp_from_config"):
                        with unittest.mock.patch("paper_trading.asset_engine.build_scale_out_from_config"):
                            self.asset = AssetEngine(
                                ticker=self.ticker,
                                name=self.name,
                                contract=mock_contract,
                                allocation=0.1,
                                config={},
                                initial_capital=self.initial_capital,
                                context=ctx,
                            )
        self.asset.peak_value = self.initial_capital
        self.asset.current_value = self.initial_capital

    def test_mtm_calculation(self):
        # 1. No position - mtm should equal current_value
        self.asset.current_price = 150.0
        self.assertEqual(self.asset.mtm_value, self.initial_capital)

        # 2. Open long position
        entry_price = 100.0
        intent = PositionIntent(
            side="long", entry_price=entry_price, entry_date="2026-05-24", stop_loss=90.0, take_profit=120.0, vol=0.02
        )
        self.asset.pos_mgr.open(intent)

        # 3. Price move up 10% (100 -> 110)
        # Position size is 0.95 by default in setup
        # Exposure multiplier is 1.0
        # Expected MTM = 10000 * (1 + 0.10 * 0.95 * 1.0) = 10950.0
        self.asset.current_price = 110.0
        expected_mtm = 10000.0 * (1 + 0.10 * 0.95 * 1.0)
        self.assertAlmostEqual(self.asset.mtm_value, expected_mtm)

        # 4. Price move down 5% (100 -> 95)
        # Expected MTM = 10000 * (1 + (-0.05) * 0.95 * 1.0) = 10000 * (1 - 0.0475) = 9525.0
        self.asset.current_price = 95.0
        expected_mtm = 10000.0 * (1 - 0.05 * 0.95 * 1.0)
        self.assertAlmostEqual(self.asset.mtm_value, expected_mtm)

    def test_get_metrics_mtm_consistency(self):
        # Open long position at 100
        self.asset.pos_mgr.open(
            PositionIntent(
                side="long", entry_price=100.0, entry_date="2026-05-24", stop_loss=90.0, take_profit=120.0, vol=0.02
            )
        )
        self.asset.current_price = 110.0

        # Mock get_config for get_metrics call
        mock_cfg = MagicMock()
        mock_cfg.position_size = 0.95

        with unittest.mock.patch("paper_trading.asset_engine.get_config", return_value=mock_cfg):
            metrics = self.asset.get_metrics()

        # Verify current_value in metrics is the MTM value
        expected_mtm = 10950.0
        self.assertEqual(metrics["current_value"], expected_mtm)
        self.assertEqual(metrics["mtm_value"], expected_mtm)
        self.assertEqual(metrics["settled_value"], self.initial_capital)


if __name__ == "__main__":
    unittest.main()
