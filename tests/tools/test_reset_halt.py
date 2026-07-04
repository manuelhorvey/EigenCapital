"""Tests for tools/reset_halt.py — emergency halt reset CLI."""

import json
import os
import tempfile
from unittest.mock import patch

from tools.reset_halt import clear_halt_in_state, read_halt_state


def _dummy_state(
    emergency_halt: bool = True,
    reason: str = "drawdown",
    detail: str = "dd=-0.97",
    peak: float = 75000.0,
) -> dict:
    return {
        "emergency_halt": emergency_halt,
        "halt_reason": reason,
        "halt_detail": detail,
        "peak_portfolio_value": peak,
        "breaker_daily_pnl": [],
        "portfolio": {"total_value": 74000.0, "portfolio_peak_value": 74961.65},
    }


# ── read_halt_state ─────────────────────────────────────────────────


def test_read_halt_state_missing_file():
    """Missing state.json returns None."""
    with patch("tools.reset_halt.STATE_PATH", "/nonexistent/state.json"):
        assert read_halt_state() is None


def test_read_halt_state_present():
    """Reads halt fields from a valid state.json."""
    state = _dummy_state()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with patch("tools.reset_halt.STATE_PATH", tmp):
            result = read_halt_state()
            assert result is not None
            assert result["emergency_halt"] is True
            assert result["halt_reason"] == "drawdown"
            assert result["halt_detail"] == "dd=-0.97"
            assert result["peak_portfolio_value"] == 75000.0
            assert result["breaker_daily_pnl"] == []
    finally:
        os.unlink(tmp)


def test_read_halt_state_no_halt():
    """No emergency halt returns False."""
    state = _dummy_state(emergency_halt=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with patch("tools.reset_halt.STATE_PATH", tmp):
            result = read_halt_state()
            assert result is not None
            assert result["emergency_halt"] is False
    finally:
        os.unlink(tmp)


# ── clear_halt_in_state ──────────────────────────────────────────────


def test_clear_halt_in_state():
    """Clears emergency_halt, halt_reason, and halt_detail."""
    state = _dummy_state()
    result = clear_halt_in_state(state)
    assert result["emergency_halt"] is False
    assert result["halt_reason"] == ""
    assert result["halt_detail"] == ""
    # Other fields preserved
    assert result["peak_portfolio_value"] == 75000.0


def test_clear_halt_in_state_noop():
    """Clearing an already-clear state is a no-op."""
    state = _dummy_state(emergency_halt=False)
    result = clear_halt_in_state(state)
    assert result["emergency_halt"] is False
    assert result["halt_reason"] == ""


# ── Integration: dry-run vs apply ────────────────────────────────────


def test_dry_run_does_not_write(capsys):
    """Without --apply, state.json is unchanged."""
    state = _dummy_state()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with patch("tools.reset_halt.STATE_PATH", tmp), patch("sys.argv", ["reset_halt.py"]):
            from tools.reset_halt import main

            main()  # dry-run returns normally, no SystemExit
        # File unchanged
        with open(tmp) as f:
            data = json.load(f)
        assert data["emergency_halt"] is True
        assert data["halt_reason"] == "drawdown"
    finally:
        os.unlink(tmp)


def test_apply_clears_halt():
    """With --apply, halt fields are cleared in state.json."""
    state = _dummy_state()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with patch("tools.reset_halt.STATE_PATH", tmp), patch("sys.argv", ["reset_halt.py", "--apply"]):
            from tools.reset_halt import main

            main()
        with open(tmp) as f:
            data = json.load(f)
        assert data["emergency_halt"] is False
        assert data["halt_reason"] == ""
        assert data["halt_detail"] == ""
        assert data["peak_portfolio_value"] == 75000.0  # unchanged
    finally:
        os.unlink(tmp)


def test_apply_with_peak_update():
    """With --apply --peak N, peak_portfolio_value is updated."""
    state = _dummy_state()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with (
            patch("tools.reset_halt.STATE_PATH", tmp),
            patch("sys.argv", ["reset_halt.py", "--apply", "--peak", "77000"]),
        ):
            from tools.reset_halt import main

            main()
        with open(tmp) as f:
            data = json.load(f)
        assert data["emergency_halt"] is False
        assert data["peak_portfolio_value"] == 77000.0
    finally:
        os.unlink(tmp)


def test_apply_already_clear_noop():
    """--apply on an already-clear state is a no-op."""
    state = _dummy_state(emergency_halt=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state, f)
        tmp = f.name
    try:
        with patch("tools.reset_halt.STATE_PATH", tmp), patch("sys.argv", ["reset_halt.py", "--apply"]):
            from tools.reset_halt import main

            main()
        with open(tmp) as f:
            data = json.load(f)
        assert data["emergency_halt"] is False
    finally:
        os.unlink(tmp)
