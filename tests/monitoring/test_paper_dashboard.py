"""Tests for monitoring/paper_dashboard — dashboard report generation functions."""

from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from monitoring.paper_dashboard import (
    check_halts,
    compute_pnl_correlation,
    compute_rolling_pf,
)


def _make_state(overrides: dict = None):
    state = {
        "portfolio": {
            "total_value": 100000.0,
            "total_return": 1.25,
            "days_running": 60,
            "execution_state": "ACTIVE",
        },
        "halt_conditions": {
            "drawdown": -0.15,
            "signal_drought": 30,
        },
        "assets": {},
    }
    if overrides:
        _deep_update(state, overrides)
    return state


def _deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            _deep_update(d[k], v)
        else:
            d[k] = v


def _make_asset(name: str, overrides: dict = None) -> dict:
    asset = {
        "halt": {"halted": False, "reasons": []},
        "metrics": {
            "total_return": 0.0,
            "current_value": 0.0,
            "drawdown": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "n_trades": 0,
            "last_signal_date": None,
            "trade_log": [],
        },
        "last_signal": {"signal": "FLAT", "confidence": 0.0},
    }
    if overrides:
        _deep_update(asset, overrides)
    return asset


class TestCheckHalts:
    def test_no_halts_when_clear(self):
        state = _make_state()
        flags = check_halts(state, pd.DataFrame())
        assert flags == []

    def test_detects_halted_asset(self):
        state = _make_state(
            {
                "assets": {
                    "EURUSD": _make_asset(
                        "EURUSD",
                        {
                            "halt": {"halted": True, "reasons": ["drawdown"]},
                        },
                    ),
                },
            }
        )
        flags = check_halts(state, pd.DataFrame())
        assert len(flags) == 1
        assert flags[0]["type"] == "engine_halt"
        assert flags[0]["asset"] == "EURUSD"

    def test_detects_execution_halt(self):
        state = _make_state({"portfolio": {"execution_state": "HALTED"}})
        flags = check_halts(state, pd.DataFrame())
        assert any(f["type"] == "execution_state" for f in flags)

    def test_detects_signal_drought(self):
        """Signal drought is detected when last_signal_date is far in the past."""
        state = _make_state(
            {
                "assets": {
                    "NZDJPY": _make_asset(
                        "NZDJPY",
                        {
                            "metrics": {"last_signal_date": "2026-01-01"},
                        },
                    ),
                },
            }
        )
        # Patch datetime at module level so both now() and strptime() work
        import monitoring.paper_dashboard as pd_mod

        with patch.object(pd_mod, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 7)
            mock_dt.strptime = datetime.strptime  # keep real strptime
            flags = check_halts(state, pd.DataFrame())
        drought = [f for f in flags if f["type"] == "drought_warning"]
        assert len(drought) == 1
        assert drought[0]["asset"] == "NZDJPY"

    def test_skips_recent_signals(self):
        """Recent signals within the early warning threshold are not flagged."""
        state = _make_state(
            {
                "assets": {
                    "NZDJPY": _make_asset(
                        "NZDJPY",
                        {
                            "metrics": {"last_signal_date": "2026-07-06"},
                        },
                    ),
                },
            }
        )
        import monitoring.paper_dashboard as pd_mod

        with patch.object(pd_mod, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 7)
            mock_dt.strptime = datetime.strptime
            flags = check_halts(state, pd.DataFrame())
        drought = [f for f in flags if f["type"] == "drought_warning"]
        assert len(drought) == 0

    def test_handles_missing_metrics(self):
        state = _make_state(
            {
                "assets": {
                    "BTC": _make_asset("BTC", {"metrics": {}}),
                },
            }
        )
        flags = check_halts(state, pd.DataFrame())
        assert flags == []

    def test_handles_missing_asset(self):
        state = _make_state()
        flags = check_halts(state, pd.DataFrame())
        assert flags == []


class TestComputePnlCorrelation:
    def test_returns_none_with_few_data_points(self):
        hist = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        assert compute_pnl_correlation(hist) is None

    def test_returns_none_without_required_columns(self):
        hist = pd.DataFrame({"A": range(10), "B": range(10)})
        assert compute_pnl_correlation(hist) is None

    def test_returns_correlation_with_xlf_btc_columns(self):
        """compute_pnl_correlation looks for columns named 'XLF', 'BTC', 'NZDJPY'."""
        rng = np.random.RandomState(42)
        hist = pd.DataFrame(
            {
                "XLF": rng.randn(20),
                "BTC": rng.randn(20),
                "NZDJPY": rng.randn(20),
            }
        )
        corr = compute_pnl_correlation(hist)
        assert corr is not None
        assert corr.shape == (3, 3)


class TestComputeRollingPf:
    def test_returns_none_with_few_trades(self):
        state = _make_state(
            {
                "assets": {
                    "BTC": _make_asset(
                        "BTC",
                        {
                            "metrics": {"trade_log": [{"pnl": 1}]},
                        },
                    ),
                },
            }
        )
        result = compute_rolling_pf(state)
        assert result.get("BTC") is None

    def test_computes_profit_factor_with_sufficient_trades(self):
        state = _make_state(
            {
                "assets": {
                    "BTC": _make_asset(
                        "BTC",
                        {
                            "metrics": {
                                "trade_log": [{"pnl": 10}] * 10 + [{"pnl": -5}] * 10,
                            },
                        },
                    ),
                },
            }
        )
        result = compute_rolling_pf(state)
        assert result.get("BTC") is not None
        assert result["BTC"] == pytest.approx(2.0, abs=0.1)

    def test_handles_zero_losses(self):
        """When all recent trades profit, profit_factor returns None (no losses)."""
        state = _make_state(
            {
                "assets": {
                    "BTC": _make_asset(
                        "BTC",
                        {
                            "metrics": {
                                "trade_log": [{"pnl": 10}] * 30,
                            },
                        },
                    ),
                },
            }
        )
        result = compute_rolling_pf(state)
        assert result.get("BTC") is None

    def test_returns_none_for_nonexistent_asset(self):
        state = _make_state()
        result = compute_rolling_pf(state)
        assert all(v is None for v in result.values())
