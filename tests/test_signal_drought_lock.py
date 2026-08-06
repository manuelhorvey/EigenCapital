from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz

from paper_trading.asset_engine import AssetEngine

ET = pytz.timezone("US/Eastern")


def _make_engine():
    engine = AssetEngine.__new__(AssetEngine)
    engine.name = "NQ"
    engine.ticker = "NQ=F"
    engine._market_data = MagicMock()

    # A fresh 6mo dataframe whose last bar is recent, so a stale
    # `last_signal_date` can be advanced and the drought gate cleared.
    idx = pd.date_range(end=datetime.now(tz=ET).date(), periods=130, freq="B")
    hist = pd.DataFrame(
        {
            "Close": [29500.0] * len(idx),
            "High": [29600.0] * len(idx),
            "Low": [29400.0] * len(idx),
            "Open": [29450.0] * len(idx),
            "Volume": [1000] * len(idx),
        },
        index=idx,
    )
    engine._market_data.get_historical.return_value = hist
    g = MagicMock()
    g._liquidity_halted = False
    engine.governance = g
    engine.halt_config = {"drawdown": -0.15, "monthly_pf": 0.0, "signal_drought": 30}
    engine.prob_history = []
    engine._last_psi_drift = None
    engine._metrics = {
        "drawdown": 0,
        "current_value": 100_000,
        "current_price": 29500.0,
        "position": None,
        "meta_inference": {},
        "feature_stability": {},
    }
    return engine


@patch("paper_trading.asset_engine.is_market_closed", return_value=False)
@patch("paper_trading.asset_engine.GovernanceService.check_halt_conditions")
def test_drought_refresh_triggered_when_stale(mock_governance, mock_closed):
    # last_sale_date frozen months ago -> would-be drought self-lock
    stale_date = datetime.now(tz=ET).date() - timedelta(days=217)
    engine = _make_engine()
    mock_governance.return_value = {"halted": True, "drought_ok": True}
    engine.last_signal_date = pd.Timestamp(stale_date)
    engine.check_halt_conditions(metrics=engine._metrics)
    # refresh ran and pushed the signal date forward toward the live bar
    fresh = pd.Timestamp(engine.last_signal_date).date()
    assert (datetime.now(tz=ET).date() - fresh).days <= 30
    # finished through governance with the refreshed date
    args, kwargs = mock_governance.call_args
    assert kwargs["last_signal_date"] is engine.last_signal_date


@patch("paper_trading.asset_engine.is_market_closed", return_value=False)
@patch("paper_trading.asset_engine.GovernanceService.check_halt_conditions")
def test_drought_refresh_throttled(mock_governance, mock_closed):
    stale_date = datetime.now(tz=ET).date() - timedelta(days=217)
    engine = _make_engine()
    mock_governance.return_value = {"halted": True, "drought_ok": True}
    engine.last_signal_date = pd.Timestamp(stale_date)
    engine._last_signal_date_live_refresh = 1e12  # future timestamp -> skip
    engine.check_halt_conditions(metrics=engine._metrics)
    # throttled: signal date untouched
    assert engine.last_signal_date.date() == stale_date


@patch("paper_trading.asset_engine.is_market_closed", return_value=True)
@patch("paper_trading.asset_engine.GovernanceService.check_halt_conditions")
def test_drought_refresh_skipped_when_market_closed(mock_governance, mock_closed):
    stale_date = datetime.now(tz=ET).date() - timedelta(days=217)
    engine = _make_engine()
    mock_governance.return_value = {"halted": True, "drought_ok": True}
    engine.last_signal_date = pd.Timestamp(stale_date)
    engine.check_halt_conditions(metrics=engine._metrics)
    assert engine.last_signal_date.date() == stale_date


@patch("paper_trading.asset_engine.is_market_closed", return_value=False)
@patch("paper_trading.asset_engine.GovernanceService.check_halt_conditions")
def test_drought_fresh_date_not_refreshed(mock_governance, mock_closed):
    # recent signal date -> no drought, no refresh needed
    fresh_date = datetime.now(tz=ET).date() - timedelta(days=5)
    engine = _make_engine()
    mock_governance.return_value = {"halted": False, "drought_ok": True}
    engine.last_signal_date = pd.Timestamp(fresh_date)
    engine._last_signal_date_live_refresh = 0.0
    # if refresh ran it would advance the date; assert it did NOT
    engine.check_halt_conditions(metrics=engine._metrics)
    assert engine.last_signal_date.date() == fresh_date
