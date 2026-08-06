from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from paper_trading.asset_engine import AssetEngine


def _make_asset(live_price):
    asset = AssetEngine.__new__(AssetEngine)
    asset.ticker = "EURUSD"
    asset._market_data = MagicMock()
    asset._market_data.get_realtime_price.return_value = live_price
    asset.current_price = 1.0000
    return asset


def test_refresh_price_frozen_when_market_closed():
    asset = _make_asset(live_price=1.2345)
    with patch("paper_trading.asset_engine.is_market_closed", return_value=True):
        asset.refresh_price()
    assert asset.current_price == 1.0000
    asset._market_data.get_realtime_price.assert_not_called()


def test_refresh_price_updates_when_market_open():
    asset = _make_asset(live_price=1.2345)
    with patch("paper_trading.asset_engine.is_market_closed", return_value=False):
        asset.refresh_price()
    asset._market_data.get_realtime_price.assert_called_once_with(asset.ticker)
    assert asset.current_price == 1.2345


def test_append_equity_history_skipped_when_market_closed():
    from paper_trading.services.engine_state_service import EngineStateService

    service = EngineStateService.__new__(EngineStateService)
    service.engine = MagicMock()
    service.engine.state_store = MagicMock()
    with patch("paper_trading.services.engine_state_service.is_market_closed", return_value=True):
        service._append_equity_history({"portfolio": {}, "assets": {}})
    service.engine.state_store.append_equity_history.assert_not_called()


def test_equity_history_includes_cash_buffer():
    from paper_trading.services.engine_state_service import EngineStateService

    engine = MagicMock()
    eng_a = MagicMock()
    eng_a.initial_capital = 90000.0 / 2
    eng_a.mtm_value = 45010.0
    engine.assets = {"A": eng_a, "B": eng_a}
    engine.state_store = MagicMock()
    service = EngineStateService.__new__(EngineStateService)
    service.engine = engine

    state = {
        "portfolio": {"total_value": 90020.0, "total_return": 0.02, "portfolio_drawdown": -0.01},
        "assets": {
            "A": {"metrics": {"mtm_value": 45010.0, "position": {"side": "long"}}},
            "B": {"metrics": {"mtm_value": 45010.0, "position": {"side": "short"}}},
        },
    }
    with (
        patch("paper_trading.services.engine_state_service.get_config") as mock_cfg,
        patch("paper_trading.services.engine_state_service.is_market_closed", return_value=False),
    ):
        mock_cfg.return_value = SimpleNamespace(capital=100000.0)
        service._append_equity_history(state)

    record = engine.state_store.append_equity_history.call_args[0][0]
    # deployed = 90000, cash buffer = 10000 -> portfolio_value lifts to ~100020
    assert record["portfolio_value"] == 100020.0
    assert record["portfolio_value"] > state["portfolio"]["total_value"]


def test_equity_history_no_cash_buffer_when_fully_deployed():
    from paper_trading.services.engine_state_service import EngineStateService

    engine = MagicMock()
    eng_a = MagicMock()
    eng_a.initial_capital = 50000.0
    eng_a.mtm_value = 50100.0
    engine.assets = {"A": eng_a, "B": eng_a}
    engine.state_store = MagicMock()
    service = EngineStateService.__new__(EngineStateService)
    service.engine = engine

    state = {
        "portfolio": {"total_value": 100200.0, "total_return": 0.01, "portfolio_drawdown": 0.0},
        "assets": {
            "A": {"metrics": {"mtm_value": 50100.0, "position": {"side": "long"}}},
            "B": {"metrics": {"mtm_value": 50100.0, "position": {"side": "long"}}},
        },
    }
    with (
        patch("paper_trading.services.engine_state_service.get_config") as mock_cfg,
        patch("paper_trading.services.engine_state_service.is_market_closed", return_value=False),
    ):
        mock_cfg.return_value = SimpleNamespace(capital=100000.0)
        service._append_equity_history(state)

    record = engine.state_store.append_equity_history.call_args[0][0]
    # deployed = 100000 == capital -> no cash buffer
    assert record["portfolio_value"] == 100200.0
