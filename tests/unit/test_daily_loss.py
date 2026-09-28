"""Daily Loss Tracker Tests — prove correct daily loss accounting.

Tests cover:
- Basic loss tracking
- Midnight rollover
- Process restart survival
- Persistence to disk
- Corrupted baseline handling
- Boundary conditions
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.daily_loss import DailyBaseline, DailyLossTracker


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def tracker(tmp_dir):
    return DailyLossTracker(
        max_daily_loss=250.0,
        persistence_dir=tmp_dir,
    )


class TestBasicLossTracking:
    """Basic daily loss calculations."""

    def test_no_loss(self, tracker):
        """No price change → zero daily loss."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=5000.0)
        assert tracker.daily_loss == 0.0
        assert tracker.daily_pnl == 0.0
        assert not tracker.is_daily_loss_breached

    def test_loss_tracking(self, tracker):
        """Loss is baseline - current (only positive losses counted)."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4800.0)
        assert tracker.daily_loss == 200.0
        assert tracker.daily_pnl == -200.0

    def test_profit_not_counted_as_loss(self, tracker):
        """Profit should not count as loss."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=5200.0)
        assert tracker.daily_loss == 0.0
        assert tracker.daily_pnl == 200.0

    def test_breach_detection(self, tracker):
        """Loss exceeding limit should be detected."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4700.0)
        assert tracker.is_daily_loss_breached
        assert tracker.daily_loss == 300.0

    def test_exactly_at_limit_not_breached(self, tracker):
        """Loss exactly at limit should NOT be breached (> not >=)."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4750.0)  # $250 loss = exactly at limit
        assert not tracker.is_daily_loss_breached

    def test_one_cent_over_breach(self, tracker):
        """Loss one cent over limit should breach."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4749.99)  # $250.01 loss
        assert tracker.is_daily_loss_breached

    def test_remaining_budget(self, tracker):
        """Remaining budget should decrease as loss increases."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4900.0)
        assert tracker.remaining_daily_loss_budget == 150.0

    def test_baseline_equity(self, tracker):
        """Baseline equity should be the initial equity."""
        tracker.initialize(broker_equity=5010.94)
        assert tracker.baseline_equity == 5010.94


class TestMidnightRollover:
    """Test that daily baseline resets at midnight."""

    def test_same_day_uses_same_baseline(self, tracker):
        """Multiple updates on the same day should use the same baseline."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4900.0)
        assert tracker.baseline_equity == 5000.0
        tracker.update(equity=4800.0)
        assert tracker.baseline_equity == 5000.0

    def test_new_day_creates_new_baseline(self, tracker):
        """When the date changes, a new baseline should be created."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4800.0)
        assert tracker.daily_loss == 200.0

        # Simulate new day by changing the tracker's internal date
        tracker._today_str()
        # Force a different date
        tracker._baseline = DailyBaseline(
            date_str="2020-01-01",  # Different day
            equity=5000.0,
            timestamp_utc="2020-01-01T00:00:00Z",
        )
        tracker.update(equity=4900.0)

        # New day → new baseline at current equity
        assert tracker.baseline_equity == 4900.0
        assert tracker.daily_loss == 0.0  # Fresh day


class TestRestartSurvival:
    """Test that baseline survives process restart."""

    def test_restart_same_day_preserves_baseline(self, tmp_dir):
        """Restarting on the same day should use the persisted baseline."""
        # First instance
        tracker1 = DailyLossTracker(max_daily_loss=250.0, persistence_dir=tmp_dir)
        tracker1.initialize(broker_equity=5000.0)
        tracker1.update(equity=4900.0)

        # Second instance (simulating restart)
        tracker2 = DailyLossTracker(max_daily_loss=250.0, persistence_dir=tmp_dir)
        tracker2.initialize(broker_equity=4900.0)

        # Should use the same baseline from first instance
        assert tracker2.baseline_equity == 5000.0
        assert tracker2.daily_loss == 100.0  # 5000 - 4900

    def test_restart_different_day_new_baseline(self, tmp_dir):
        """Restarting on a different day should create new baseline."""
        # First instance
        tracker1 = DailyLossTracker(max_daily_loss=250.0, persistence_dir=tmp_dir)
        tracker1.initialize(broker_equity=5000.0)

        # Manually write a baseline for a different day
        old_baseline = DailyBaseline(
            date_str="2020-01-01",
            equity=5000.0,
            timestamp_utc="2020-01-01T00:00:00Z",
        )
        old_hash = old_baseline.compute_hash()
        data = {
            "date_str": old_baseline.date_str,
            "equity": old_baseline.equity,
            "timestamp_utc": old_baseline.timestamp_utc,
            "hash": old_hash,
        }
        baseline_file = Path(tmp_dir) / "daily_baseline.json"
        with open(baseline_file, "w") as f:
            json.dump(data, f)

        # Second instance (different day)
        tracker2 = DailyLossTracker(max_daily_loss=250.0, persistence_dir=tmp_dir)
        tracker2.initialize(broker_equity=5100.0)

        # Should create new baseline at current equity
        assert tracker2.baseline_equity == 5100.0
        assert tracker2.daily_loss == 0.0


class TestPersistence:
    """Test that baseline persists to disk."""

    def test_baseline_saved_to_disk(self, tracker, tmp_dir):
        """Baseline should be saved to disk after initialization."""
        tracker.initialize(broker_equity=5010.94)
        baseline_file = Path(tmp_dir) / "daily_baseline.json"
        assert baseline_file.exists()

        with open(baseline_file) as f:
            data = json.load(f)
        assert data["equity"] == 5010.94
        assert data["date_str"] == tracker._today_str()

    def test_baseline_hash_integrity(self, tracker, tmp_dir):
        """Baseline hash should be verifiable."""
        tracker.initialize(broker_equity=5010.94)
        baseline_file = Path(tmp_dir) / "daily_baseline.json"

        with open(baseline_file) as f:
            data = json.load(f)

        baseline = DailyBaseline(
            date_str=data["date_str"],
            equity=data["equity"],
            timestamp_utc=data["timestamp_utc"],
        )
        assert data["hash"] == baseline.compute_hash()

    def test_corrupted_baseline_treated_as_missing(self, tmp_dir):
        """Corrupted baseline file should be treated as missing."""
        baseline_file = Path(tmp_dir) / "daily_baseline.json"
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        with open(baseline_file, "w") as f:
            f.write("not valid json {{{")

        tracker = DailyLossTracker(max_daily_loss=250.0, persistence_dir=tmp_dir)
        tracker.initialize(broker_equity=5000.0)

        # Should create new baseline
        assert tracker.baseline_equity == 5000.0


class TestForceReset:
    """Test force reset (e.g., after reconnect)."""

    def test_force_reset_new_baseline(self, tracker):
        """Force reset should create new baseline at given equity."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4800.0)
        assert tracker.daily_loss == 200.0

        tracker.force_reset(equity=4900.0)
        assert tracker.baseline_equity == 4900.0
        assert tracker.daily_loss == 0.0


class TestDiagnostics:
    """Test diagnostic output."""

    def test_to_dict(self, tracker):
        """to_dict should contain all relevant fields."""
        tracker.initialize(broker_equity=5000.0)
        tracker.update(equity=4900.0)
        d = tracker.to_dict()
        assert "baseline_date" in d
        assert "baseline_equity" in d
        assert "current_equity" in d
        assert "daily_loss" in d
        assert "is_breached" in d
        assert "remaining_budget" in d
        assert d["daily_loss"] == 100.0


def _freeze_clock(monkeypatch, instant_utc: datetime) -> None:
    """Freeze daily_loss's view of now to a fixed UTC instant (C-5 tests)."""

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant_utc.replace(tzinfo=None)
            return instant_utc.astimezone(tz)

    monkeypatch.setattr("eigencapital.live.daily_loss.datetime", _FrozenDateTime)


class TestDSTTransitions:
    """C-5 regression: the daily boundary must follow the IANA zone's local
    calendar date across DST transitions — a fixed UTC offset drifts by an
    hour when the zone switches between standard time and DST."""

    def test_berlin_spring_forward_boundary(self, tmp_dir, monkeypatch):
        """Berlin local midnight 2025-03-30 = 2025-03-29T23:00Z (CET, UTC+1)."""
        tracker = DailyLossTracker(persistence_dir=tmp_dir, tz_name="Europe/Berlin")

        _freeze_clock(monkeypatch, datetime(2025, 3, 29, 22, 59, tzinfo=UTC))
        assert tracker._today_str() == "2025-03-29"
        _freeze_clock(monkeypatch, datetime(2025, 3, 29, 23, 0, tzinfo=UTC))
        assert tracker._today_str() == "2025-03-30"

        # 2025-03-30T01:00Z is the transition instant (02:00 CET → 03:00 CEST)
        _freeze_clock(monkeypatch, datetime(2025, 3, 30, 1, 0, tzinfo=UTC))
        assert tracker._today_str() == "2025-03-30"

    def test_berlin_summer_midnight_uses_dst_offset(self, tmp_dir, monkeypatch):
        """Under CEST (UTC+2) local midnight is 22:00Z. A fixed +01:00 offset
        (the C-5 bug) would still report the previous date at that instant."""
        tracker = DailyLossTracker(persistence_dir=tmp_dir, tz_name="Europe/Berlin")
        instant = datetime(2025, 6, 30, 22, 0, tzinfo=UTC)

        _freeze_clock(monkeypatch, instant - timedelta(minutes=1))
        assert tracker._today_str() == "2025-06-30"
        _freeze_clock(monkeypatch, instant)
        assert tracker._today_str() == "2025-07-01"

        static_offset_date = (instant + timedelta(hours=1)).strftime("%Y-%m-%d")
        assert static_offset_date == "2025-06-30"  # fixed offset fails here

    def test_berlin_autumn_fallback_boundary(self, tmp_dir, monkeypatch):
        """Berlin local midnight 2025-10-26 = 2025-10-25T22:00Z (still CEST)."""
        tracker = DailyLossTracker(persistence_dir=tmp_dir, tz_name="Europe/Berlin")

        _freeze_clock(monkeypatch, datetime(2025, 10, 25, 21, 59, tzinfo=UTC))
        assert tracker._today_str() == "2025-10-25"
        _freeze_clock(monkeypatch, datetime(2025, 10, 25, 22, 0, tzinfo=UTC))
        assert tracker._today_str() == "2025-10-26"

        # 2025-10-26T01:00Z = 02:00 CET after fallback (03:00 → 02:00);
        # the repeated local hour must not shift the date
        _freeze_clock(monkeypatch, datetime(2025, 10, 26, 1, 0, tzinfo=UTC))
        assert tracker._today_str() == "2025-10-26"

    def test_new_york_spring_summer_autumn_boundaries(self, tmp_dir, monkeypatch):
        """New York: EST midnight = 05:00Z, EDT midnight = 04:00Z."""
        tracker = DailyLossTracker(persistence_dir=tmp_dir, tz_name="America/New_York")
        cases = [
            # Spring forward 2025-03-09 (EST → EDT at 07:00Z)
            (datetime(2025, 3, 9, 4, 59, tzinfo=UTC), "2025-03-08"),
            (datetime(2025, 3, 9, 5, 0, tzinfo=UTC), "2025-03-09"),
            # Mid-summer: EDT midnight is 04:00Z — a fixed UTC-5 offset
            # (the C-5 bug) would still say 2025-06-30 here
            (datetime(2025, 7, 1, 3, 59, tzinfo=UTC), "2025-06-30"),
            (datetime(2025, 7, 1, 4, 0, tzinfo=UTC), "2025-07-01"),
            # Autumn back 2025-11-02 (EDT → EST at 06:00Z, after midnight)
            (datetime(2025, 11, 2, 3, 59, tzinfo=UTC), "2025-11-01"),
            (datetime(2025, 11, 2, 4, 0, tzinfo=UTC), "2025-11-02"),
        ]
        for instant, expected in cases:
            _freeze_clock(monkeypatch, instant)
            assert tracker._today_str() == expected, instant

    def test_dst_rollover_rebaselines_and_persists_local_date(self, tmp_dir, monkeypatch):
        """Rollover and persistence keys must use the zone-aware local date."""
        tracker = DailyLossTracker(
            max_daily_loss=250.0,
            persistence_dir=tmp_dir,
            tz_name="Europe/Berlin",
        )
        baseline_file = Path(tmp_dir) / "daily_baseline.json"

        _freeze_clock(monkeypatch, datetime(2025, 6, 30, 21, 59, tzinfo=UTC))
        tracker.initialize(broker_equity=5000.0)
        assert tracker.baseline_date == "2025-06-30"
        persisted = json.loads(baseline_file.read_text())
        assert persisted["date_str"] == "2025-06-30"

        # 22:00Z = local midnight under CEST → rollover resets baseline
        _freeze_clock(monkeypatch, datetime(2025, 6, 30, 22, 0, tzinfo=UTC))
        tracker.update(equity=4900.0)
        assert tracker.baseline_date == "2025-07-01"
        assert tracker.baseline_equity == 4900.0
        assert tracker.daily_loss == 0.0
        persisted = json.loads(baseline_file.read_text())
        assert persisted["date_str"] == "2025-07-01"

        # force_reset keys off the same zone-aware local date
        tracker.force_reset(equity=4800.0)
        assert tracker.baseline_date == "2025-07-01"
        persisted = json.loads(baseline_file.read_text())
        assert persisted["date_str"] == "2025-07-01"
        assert tracker.daily_loss == 0.0
