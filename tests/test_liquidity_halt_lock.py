from unittest.mock import MagicMock, patch

import pandas as pd

from paper_trading.asset_engine import AssetEngine


def _make_engine():
    engine = AssetEngine.__new__(AssetEngine)
    engine.name = "TEST"
    engine.ticker = "EURUSD"
    engine._market_data = MagicMock()
    hist = pd.DataFrame(
        {
            "Close": [100.0] * 80,
            "High": [100.0] * 80,
            "Low": [99.0] * 80,
            "Open": [99.5] * 80,
            "Volume": [1000] * 80,
        }
    )
    engine._market_data.get_historical.return_value = hist
    g = MagicMock()
    g._liquidity_halted = True
    engine.governance = g
    engine.halt_config = {"drawdown": -0.15, "monthly_pf": 0.0, "signal_drought": 30}
    engine.last_signal_date = None
    engine.prob_history = []
    engine._last_psi_drift = None
    engine._metrics = {
        "drawdown": 0,
        "current_value": 100_000,
        "current_price": 100.0,
        "position": None,
        "meta_inference": {},
        "feature_stability": {},
    }
    return engine


@patch("paper_trading.asset_engine.is_market_closed", return_value=False)
def test_liquidity_refresh_triggered_when_halted(mock_closed):
    engine = _make_engine()
    engine.check_halt_conditions(metrics=engine._metrics)
    engine.governance.refresh_liquidity.assert_called_once()


@patch("paper_trading.asset_engine.is_market_closed", return_value=False)
def test_liquidity_refresh_throttled(mock_closed):
    engine = _make_engine()
    engine._last_liquidity_live_refresh = 1e12  # future timestamp -> skip
    engine.check_halt_conditions(metrics=engine._metrics)
    engine.governance.refresh_liquidity.assert_not_called()


@patch("paper_trading.asset_engine.is_market_closed", return_value=True)
def test_liquidity_refresh_skipped_when_market_closed(mock_closed):
    engine = _make_engine()
    engine.check_halt_conditions(metrics=engine._metrics)
    engine.governance.refresh_liquidity.assert_not_called()
