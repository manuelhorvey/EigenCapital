"""Tests for ``paper_trading/ops/tracer.py`` — trace logging functions."""

import json
from unittest.mock import patch

import pytest

import paper_trading.ops.tracer as tracer_mod


@pytest.fixture
def trace_path(tmp_path):
    """Set TRACE_LOG_PATH to tmp_path and return the path."""
    path = tmp_path / "trace.jsonl"
    with patch.object(tracer_mod, "TRACE_LOG_PATH", str(path)):
        yield path


class TestTraceDecision:
    def test_writes_decision_entry(self, trace_path):
        tracer_mod.trace_decision(
            asset="EURUSD",
            features={"close": 1.0500, "mom_5": 0.01},
            proba=[0.1, 0.2, 0.7],
            threshold=0.45,
            signal="BUY",
            confidence=70.0,
            pos_size=0.5,
            close_price=1.0500,
            current_side=None,
            halt_flags={"halted": False, "reasons": []},
        )
        assert trace_path.exists()
        lines = trace_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "decision"
        assert entry["asset"] == "EURUSD"
        assert entry["signal"] == "BUY"

    def test_includes_optional_fields(self, trace_path):
        tracer_mod.trace_decision(
            asset="GBPUSD",
            features={},
            proba=[0.3, 0.2, 0.5],
            threshold=0.45,
            signal="FLAT",
            confidence=50.0,
            pos_size=0.0,
            close_price=1.2500,
            current_side="long",
            halt_flags={"halted": True, "reasons": ["drawdown"]},
            current_price=1.2510,
            regime_long_prob=0.5,
            feature_hash="abc",
            model_hash="def",
        )
        entry = json.loads(trace_path.read_text().strip())
        assert entry["current_position_side"] == "long"
        assert entry["halted"] is True
        assert entry["regime_long_prob"] == 0.5


class TestTraceExit:
    def test_writes_exit_entry(self, trace_path):
        tracer_mod.trace_exit(
            asset="EURUSD",
            exit_price=1.0600,
            reason="TP",
            realized_r=2.5,
            bars_held=10,
        )
        entry = json.loads(trace_path.read_text().strip())
        assert entry["event"] == "exit"
        assert entry["exit_reason"] == "TP"
        assert entry["realized_r"] == 2.5


class TestTraceDiagnosticReport:
    def test_writes_report(self, trace_path):
        tracer_mod.trace_diagnostic_report({"key": "val", "num": 42})
        entry = json.loads(trace_path.read_text().strip())
        assert entry["event"] == "shadow_diagnostic"
        assert entry["key"] == "val"


class TestShadowCompare:
    def _count_lines(self, path):
        if not path.exists():
            return 0
        return len(path.read_text().strip().split("\n")) if path.read_text().strip() else 0

    def _read_last_entry(self, path):
        text = path.read_text().strip()
        lines = text.split("\n")
        return json.loads(lines[-1])

    def test_shadow_compare_signal_match(self, trace_path):
        tracer_mod.shadow_compare_signal(
            asset="EURUSD",
            proba_produced=[0.1, 0.2, 0.7],
            wrapper_signal="BUY",
            wrapper_confidence=70.0,
            original_signal="BUY",
            original_confidence=70.0,
        )
        # No mismatch written when signals match
        assert self._count_lines(trace_path) == 0

    def test_shadow_compare_signal_mismatch(self, trace_path):
        tracer_mod.shadow_compare_signal(
            asset="EURUSD",
            proba_produced=[0.1, 0.2, 0.7],
            wrapper_signal="BUY",
            wrapper_confidence=70.0,
            original_signal="SELL",
            original_confidence=70.0,
        )
        entry = self._read_last_entry(trace_path)
        assert entry["event"] == "shadow_mismatch"

    def test_shadow_compare_pnl(self, trace_path):
        tracer_mod.shadow_compare_pnl(asset="EURUSD", wrapper_pnl=100.0, original_pnl=100.0)
        assert self._count_lines(trace_path) == 0

        tracer_mod.shadow_compare_pnl(asset="EURUSD", wrapper_pnl=100.0, original_pnl=101.0)
        entry = self._read_last_entry(trace_path)
        assert entry["event"] == "shadow_pnl_mismatch"

    def test_shadow_compare_sizing(self, trace_path):
        tracer_mod.shadow_compare_sizing(asset="EURUSD", wrapper_size=0.5, original_size=0.5)
        assert self._count_lines(trace_path) == 0

        tracer_mod.shadow_compare_sizing(asset="EURUSD", wrapper_size=0.5, original_size=0.6)
        entry = self._read_last_entry(trace_path)
        assert entry["event"] == "shadow_sizing_mismatch"

    def test_shadow_compare_sltp(self, trace_path):
        tracer_mod.shadow_compare_sltp(
            asset="EURUSD",
            label_sl=1.0400,
            label_tp=1.0700,
            runtime_sl=1.0400,
            runtime_tp=1.0700,
            entry_price=1.0500,
        )
        assert self._count_lines(trace_path) == 0

        tracer_mod.shadow_compare_sltp(
            asset="EURUSD",
            label_sl=1.0400,
            label_tp=1.0700,
            runtime_sl=1.0300,
            runtime_tp=1.0800,
            entry_price=1.0500,
        )
        entry = self._read_last_entry(trace_path)
        assert entry["event"] == "shadow_sltp_change"
