"""Tests for monitoring/weekly_report — weekly report generation functions."""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from monitoring.weekly_report import (
    check_vol_regime,
    log_vol_baseline,
    load_state,
    load_history,
)


class TestLoadState:
    def test_returns_none_when_no_state(self):
        with patch("monitoring.weekly_report.STATE_PATH", "/nonexistent/state.json"):
            assert load_state() is None

    def test_loads_state(self, tmp_path):
        import json

        state = {"portfolio": {"total_value": 100000}}
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps(state))
        with patch("monitoring.weekly_report.STATE_PATH", str(state_path)):
            result = load_state()
            assert result is not None
            assert result["portfolio"]["total_value"] == 100000


class TestLoadHistory:
    def test_returns_empty_when_no_file(self):
        with patch("monitoring.weekly_report.HISTORY_PATH", "/nonexistent/history.parquet"):
            df = load_history()
            assert df.empty

    def test_loads_history(self, tmp_path):
        hist = pd.DataFrame({"date": ["2026-01-01"], "portfolio_value": [100000]})
        hist_path = tmp_path / "history.parquet"
        hist.to_parquet(hist_path)
        with patch("monitoring.weekly_report.HISTORY_PATH", str(hist_path)):
            result = load_history()
            assert not result.empty
            assert result["portfolio_value"].iloc[0] == 100000


class TestCheckVolRegime:
    def test_runs_without_error(self):
        """With healthy vol ratio, check_vol_regime returns True."""
        with patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol:
            mock_vol.return_value = 0.01
            result = check_vol_regime()
            assert isinstance(result, bool)

    def test_returns_true_when_all_vols_healthy(self):
        """When every ticker's live vol matches its training vol (ratio=1.0), returns True."""
        with (
            patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol,
            patch("monitoring.weekly_report.TRAIN_VOLS", {"XLF": 0.01, "BTC": 0.01, "NZDJPY": 0.01}),
        ):
            mock_vol.return_value = 0.01
            result = check_vol_regime()
            assert result is True

    def test_handles_missing_vol(self):
        """When compute_live_ewm_vol returns None for some tickers, the
        function skips those entries. With all tickers returning None,
        all_healthy stays True (vacuously)."""
        with patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol:
            mock_vol.return_value = None
            result = check_vol_regime()
            assert result is True  # vacuously true when all tickers skipped

    def test_detects_vol_mismatch(self):
        """A vol ratio outside healthy thresholds returns False."""
        with patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol:
            mock_vol.return_value = 0.0005  # far below training vol for all tickers
            result = check_vol_regime()
            assert result is False


class TestLogVolBaseline:
    def test_writes_log_file(self, tmp_path):
        log_path = tmp_path / "paper_trade_log.md"
        with (
            patch("monitoring.weekly_report.TRADE_LOG_PATH", str(log_path)),
            patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol,
        ):
            mock_vol.return_value = 0.01
            log_vol_baseline()

        assert os.path.exists(log_path)
        content = log_path.read_text()
        assert "Vol Regime Baseline" in content

    def test_appends_to_existing_file(self, tmp_path):
        log_path = tmp_path / "paper_trade_log.md"
        log_path.write_text("# Existing log\n")
        with (
            patch("monitoring.weekly_report.TRADE_LOG_PATH", str(log_path)),
            patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol,
        ):
            mock_vol.return_value = 0.01
            log_vol_baseline()

        content = log_path.read_text()
        assert "Existing log" in content
        assert "Vol Regime Baseline" in content

    def test_handles_missing_vol_gracefully(self, tmp_path):
        log_path = tmp_path / "paper_trade_log.md"
        with (
            patch("monitoring.weekly_report.TRADE_LOG_PATH", str(log_path)),
            patch("monitoring.weekly_report.compute_live_ewm_vol") as mock_vol,
            patch("monitoring.weekly_report.TRAIN_VOLS", {"XLF": 0.01, "BTC": 0.01, "NZDJPY": 0.01}),
        ):
            mock_vol.return_value = None
            log_vol_baseline()
            content = log_path.read_text()
            # Should still write file even when all tickers return None
            assert "Vol Regime Baseline" in content
