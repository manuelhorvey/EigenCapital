"""Shadow tracker / persistence tests (brief Sections 12, 14, 17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eigencapital.shadow.portfolio.tracker import (
    PROTECTED_R4_EVIDENCE_FILES,
    ShadowDecisionRecorder,
    ShadowPositionTracker,
)


class TestRecorderGuards:
    def test_refuses_protected_r4_files(self, tmp_path: Path):
        """Shadow evidence must never write into the frozen R4 namespaces."""
        for name in PROTECTED_R4_EVIDENCE_FILES:
            with pytest.raises(PermissionError):
                ShadowDecisionRecorder._append(tmp_path / name, {"event": "x"})

    def test_protected_set_is_exact(self):
        assert {
            "decisions.jsonl",
            "order_intents.jsonl",
            "risk_gate_audit.jsonl",
            "shadow_decisions.jsonl",
        } == PROTECTED_R4_EVIDENCE_FILES

    def test_decision_round_trip(self, tmp_path: Path):
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        decision = _fake_decision()
        path = recorder.record_decision(decision)
        assert Path(path).name == "shadow_portfolio_decisions.jsonl"
        records = recorder.read_decisions()
        assert len(records) == 1
        assert records[0]["schema"] == "shadow_portfolio_decision"
        assert records[0]["signal_date"] == "2026-01-01"

    def test_outcome_round_trip(self, tmp_path: Path):
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        path = recorder.record_outcome({"signal_date": "2026-01-01", "symbol": "AUDUSD"})
        assert Path(path).name == "shadow_portfolio_outcomes.jsonl"
        assert len(recorder.read_outcomes()) == 1

    def test_isolated_namespace_untouched(self, tmp_path: Path):
        """Recording shadow evidence must not create/modify R4 evidence files."""
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        recorder.record_decision(_fake_decision())
        files = {p.name for p in tmp_path.iterdir()}
        assert files == {"shadow_portfolio_decisions.jsonl"}


class TestOutcomeMath:
    def _make(self, tmp_path: Path, equity: float = 5100.0) -> ShadowPositionTracker:
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        return ShadowPositionTracker(recorder, equity=equity)

    def test_long_pnl_and_r(self, tmp_path: Path):
        tracker = self._make(tmp_path)
        tracker.open_cycle(
            selected_symbols=["AUDUSD"],
            weights={"AUDUSD": 0.1},
            prices={"AUDUSD": 100.0},
            atr_pct={"AUDUSD": 0.01},
            cycle_id="C1",
            signal_date="2026-01-01",
            entry_time="2026-01-01",
        )
        outcomes = tracker.close_positions(["AUDUSD"], {"AUDUSD": 110.0}, "2026-01-02", "C1", "2026-01-02")
        assert len(outcomes) == 1
        o = outcomes[0]
        assert o["shadow_entry"] == 100.0
        assert o["shadow_exit"] == 110.0
        assert o["shadow_size"] == pytest.approx(510.0)  # |w| · equity
        assert o["shadow_pnl"] == pytest.approx(51.0)  # +10% · 510
        assert o["shadow_r"] == pytest.approx(10.0)  # 10% / 1%
        assert o["shadow_stop"] is None
        assert o["exit_reason"] == "rotated_out"

    def test_short_pnl(self, tmp_path: Path):
        tracker = self._make(tmp_path)
        tracker.open_cycle(
            selected_symbols=["EURUSD"],
            weights={"EURUSD": -0.2},
            prices={"EURUSD": 100.0},
            atr_pct={"EURUSD": 0.01},
            cycle_id="C1",
            signal_date="2026-01-01",
            entry_time="2026-01-01",
        )
        outcomes = tracker.close_positions(["EURUSD"], {"EURUSD": 95.0}, "2026-01-02", "C1", "2026-01-02")
        assert outcomes[0]["shadow_pnl"] == pytest.approx(51.0)  # +5% · 1020

    def test_close_only_selected_symbols(self, tmp_path: Path):
        tracker = self._make(tmp_path)
        tracker.open_cycle(
            selected_symbols=["AUDUSD", "EURUSD"],
            weights={"AUDUSD": 0.1, "EURUSD": 0.1},
            prices={"AUDUSD": 100.0, "EURUSD": 100.0},
            atr_pct={"AUDUSD": 0.01, "EURUSD": 0.01},
            cycle_id="C1",
            signal_date="2026-01-01",
            entry_time="2026-01-01",
        )
        outcomes = tracker.close_positions(["AUDUSD"], {"AUDUSD": 105.0}, "2026-01-02", "C1", "2026-01-02")
        assert len(outcomes) == 1
        assert outcomes[0]["symbol"] == "AUDUSD"
        assert set(tracker.open_positions()) == {"EURUSD"}

    def test_close_all_at_end(self, tmp_path: Path):
        tracker = self._make(tmp_path)
        tracker.open_cycle(
            selected_symbols=["AUDUSD"],
            weights={"AUDUSD": 0.1},
            prices={"AUDUSD": 100.0},
            atr_pct={"AUDUSD": 0.01},
            cycle_id="C1",
            signal_date="2026-01-01",
            entry_time="2026-01-01",
        )
        outcomes = tracker.close_all({"AUDUSD": 90.0}, "2026-01-10", "C1", "2026-01-10")
        assert outcomes[0]["exit_reason"] == "end_of_observation"
        assert outcomes[0]["shadow_pnl"] == pytest.approx(-51.0)
        assert tracker.open_positions() == {}

    def test_missing_price_leaves_position_open(self, tmp_path: Path):
        tracker = self._make(tmp_path)
        tracker.open_cycle(
            selected_symbols=["AUDUSD"],
            weights={"AUDUSD": 0.1},
            prices={"AUDUSD": 100.0},
            atr_pct={"AUDUSD": 0.01},
            cycle_id="C1",
            signal_date="2026-01-01",
            entry_time="2026-01-01",
        )
        outcomes = tracker.close_positions(["AUDUSD"], {}, "2026-01-02", "C1", "2026-01-02")
        assert outcomes == []
        assert "AUDUSD" in tracker.open_positions()

    def test_rotation_lifecycle(self, tmp_path: Path):
        """Position held while selected, realized when rotated out."""
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        tracker = ShadowPositionTracker(recorder, equity=5100.0)
        tracker.open_cycle(
            ["AUDUSD"],
            {"AUDUSD": 0.1},
            {"AUDUSD": 100.0},
            {"AUDUSD": 0.01},
            "C1",
            "2026-01-01",
            "2026-01-01",
        )
        # Next cycle: AUDUSD rotated out, EURUSD enters.
        tracker.open_cycle(
            ["EURUSD"],
            {"EURUSD": 0.1},
            {"EURUSD": 102.0},
            {"EURUSD": 0.01},
            "C2",
            "2026-01-08",
            "2026-01-08",
        )
        exits = [s for s in tracker.open_positions() if s not in {"EURUSD"}]
        outcomes = tracker.close_positions(exits, {"AUDUSD": 103.0}, "2026-01-08", "C2", "2026-01-08")
        assert [o["symbol"] for o in outcomes] == ["AUDUSD"]
        assert set(tracker.open_positions()) == {"EURUSD"}
        assert len(recorder.read_outcomes()) == 1


class TestNoLookaheadAtTracker:
    def test_tracker_sees_only_caller_supplied_data(self, tmp_path: Path):
        """The tracker holds no data of its own; outcomes depend only on the
        prices the caller passes at close time."""
        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        tracker_a = ShadowPositionTracker(recorder, equity=5100.0)
        tracker_b = ShadowPositionTracker(recorder, equity=5100.0)
        for t in (tracker_a, tracker_b):
            t.open_cycle(
                ["AUDUSD"],
                {"AUDUSD": 0.1},
                {"AUDUSD": 100.0},
                {"AUDUSD": 0.01},
                "C1",
                "2026-01-01",
                "2026-01-01",
            )
        # Same future close → identical PnL; different close → different PnL.
        a = tracker_a.close_all({"AUDUSD": 110.0}, "2026-01-02", "C1", "2026-01-02")
        b = tracker_b.close_all({"AUDUSD": 120.0}, "2026-01-02", "C1", "2026-01-02")
        assert a[0]["shadow_pnl"] == pytest.approx(51.0)
        assert b[0]["shadow_pnl"] == pytest.approx(102.0)


def _fake_decision():
    class _FakeDecision:
        def to_dict(self):
            return {
                "cycle_id": "R4S-2026-01-01",
                "decision_timestamp": "2026-01-01T00:00:00+00:00",
                "signal_date": "2026-01-01",
                "status": "SELECTED",
                "status_reason": "test",
                "candidates": [],
                "baseline": {"symbols": [], "weights": {}, "metrics": {}},
                "selected": {"symbols": [], "weights": {}, "metrics": {}},
                "quality_by_n": {},
                "edge_metrics": {},
                "correlation": {"available": False},
                "selector_version": "test",
                "config_hash": "x" * 64,
            }

    return _FakeDecision()


def test_protected_files_json_dump_parity(tmp_path: Path):
    """json.dumps default=str keeps every shadow record serializable."""
    recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
    recorder.record_decision(_fake_decision())
    with open(tmp_path / "shadow_portfolio_decisions.jsonl") as f:
        line = f.readline()
    assert json.loads(line)["schema"] == "shadow_portfolio_decision"
