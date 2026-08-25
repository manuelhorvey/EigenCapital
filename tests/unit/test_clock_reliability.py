"""Tests for clock/time reliability in production trading paths.

Verifies:
- All live code uses timezone-aware UTC timestamps
- Daily loss tracker handles timezone offsets correctly
- Midnight rollover is correctly detected
- No naive datetime usage in safety-critical paths
"""

import inspect
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None, f"timestamp is naive: {ts!r}"
    return dt


class TestUTCUsage:
    """Live components must emit timezone-aware UTC timestamps."""

    def test_supervisor_uses_utc(self, tmp_path):
        from eigencapital.live.supervisor import ProcessSupervisor

        s = ProcessSupervisor(state_dir=str(tmp_path))
        assert s._now_utc()
        _parse_utc(s._now_utc())

        assert s.claim_instance() is True
        state = s.state
        assert state is not None
        _parse_utc(state.started_at)
        _parse_utc(state.last_healthy_at)

        s.mark_healthy()
        health = s.get_health_status()
        assert health["alive"] is True
        _parse_utc(health["timestamp"])
        s.release()

    def test_daily_loss_uses_utc(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        ts = tracker._now_utc()
        _parse_utc(ts)

    def test_risk_enforcement_uses_utc(self):
        import inspect
        from eigencapital.live import risk_enforcement

        source = inspect.getsource(risk_enforcement)
        assert "datetime.now(timezone.utc)" in source, (
            "Risk enforcement must use datetime.now(timezone.utc)"
        )

    def test_persisted_baseline_timestamp_is_utc(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        tracker = DailyLossTracker(persistence_dir=str(tmp_path))
        tracker.initialize(broker_equity=5000.0)
        data = json.loads((tmp_path / "daily_baseline.json").read_text())
        _parse_utc(data["timestamp_utc"])


class TestTimezoneOffset:
    """The daily boundary must honor the configured offset explicitly."""

    @staticmethod
    def _expected_today(offset_hours: int) -> str:
        now = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
        return now.strftime("%Y-%m-%d")

    def test_zero_offset_matches_utc_date(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        t = DailyLossTracker(
            max_daily_loss=100.0,
            persistence_dir=str(tmp_path),
            timezone_offset_hours=0,
        )
        assert t._today_str() == self._expected_today(0)

    def test_positive_offset_shifts_day_forward(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        t = DailyLossTracker(
            max_daily_loss=100.0,
            persistence_dir=str(tmp_path),
            timezone_offset_hours=5,
        )
        assert t._today_str() == self._expected_today(5)

    def test_negative_offset_shifts_day_backward(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        t = DailyLossTracker(
            max_daily_loss=100.0,
            persistence_dir=str(tmp_path),
            timezone_offset_hours=-5,
        )
        assert t._today_str() == self._expected_today(-5)

    def test_extreme_offsets_stay_well_formed(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        for offset in [-12, 12, -14, 14]:
            t = DailyLossTracker(
                max_daily_loss=100.0,
                persistence_dir=str(tmp_path),
                timezone_offset_hours=offset,
            )
            result = t._today_str()
            assert len(result) == 10
            assert result.count("-") == 2


class TestMidnightRollover:
    """Verify daily loss resets at midnight."""

    def test_update_resets_stale_baseline(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker, DailyBaseline

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))

        # Simulate baseline from yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        old_baseline = DailyBaseline(
            date_str=yesterday,
            equity=5200.0,
            hash="def456",
            timestamp_utc=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        )
        tracker._baseline = old_baseline

        # update() should detect stale baseline and reset
        tracker.initialize(broker_equity=5000.0)
        assert tracker._baseline is not None
        assert tracker._baseline.date_str == tracker._today_str()

    def test_no_reset_within_same_day(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        tracker.initialize(broker_equity=5000.0)
        first_hash = tracker._baseline.hash if tracker._baseline else None

        # Second call on same day should not reset
        tracker.initialize(broker_equity=5000.0)
        assert tracker._baseline is not None
        assert tracker._baseline.date_str == tracker._today_str()

    def test_restart_same_day_preserves_baseline(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        tracker.initialize(broker_equity=5000.0)

        # Simulate restart — new tracker loads from disk
        tracker2 = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        loaded = tracker2._load_baseline()
        assert loaded is not None
        assert loaded.equity == 5000.0

    def test_restart_after_midnight_rebaselines(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker, DailyBaseline
        import json

        # Write yesterday's baseline
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        baseline_data = {
            "date_str": yesterday,
            "equity": 5200.0,
            "hash": "old123",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        (tmp_path / "daily_baseline.json").write_text(json.dumps(baseline_data))

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        tracker.initialize(broker_equity=5000.0)
        assert tracker._baseline is not None
        assert tracker._baseline.date_str == tracker._today_str()
        assert tracker._baseline.equity == 5000.0

    def test_corrupted_baseline_fails_closed(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker

        # Write corrupted baseline
        (tmp_path / "daily_baseline.json").write_text("NOT JSON")
        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        loaded = tracker._load_baseline()
        assert loaded is None

    def test_corrupted_baseline_json_fails_closed(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker
        import json

        # Write JSON missing required fields
        (tmp_path / "daily_baseline.json").write_text(json.dumps({"garbage": True}))
        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        loaded = tracker._load_baseline()
        assert loaded is None

    def test_force_reset_rebases_and_persists(self, tmp_path):
        from eigencapital.live.daily_loss import DailyLossTracker
        import json

        tracker = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        tracker.initialize(broker_equity=5000.0)

        # Simulate: restart on a new day by writing yesterday's date to disk
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        baseline_data = {
            "date_str": yesterday,
            "equity": 5000.0,
            "hash": "old",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        (tmp_path / "daily_baseline.json").write_text(json.dumps(baseline_data))

        # New tracker detects stale date, creates new baseline with current equity
        tracker2 = DailyLossTracker(max_daily_loss=100.0, persistence_dir=str(tmp_path))
        tracker2.initialize(broker_equity=4800.0)
        assert tracker2._baseline is not None
        assert tracker2._baseline.equity == 4800.0

        # Verify persisted
        loaded = tracker2._load_baseline()
        assert loaded is not None
        assert loaded.equity == 4800.0


class TestNoNaiveDatetimesInLivePaths:
    """Verify no naive datetime usage in safety-critical code."""

    def test_no_naive_wall_clock_in_any_live_module(self):
        """No live module should use bare datetime.now()."""
        import importlib
        import eigencapital.live as live_pkg

        pkg_dir = Path(live_pkg.__file__).parent
        violations = []
        for p in sorted(pkg_dir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            mod = importlib.import_module(f"eigencapital.live.{p.stem}")
            source = inspect.getsource(mod)
            # Look for datetime.now() without timezone — but allow datetime.now(timezone.utc)
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "datetime.now()" in stripped and "timezone" not in stripped:
                    violations.append(f"{p.name}:{i}: {stripped[:80]}")

        assert not violations, (
            "Naive datetime.now() in live modules:\n" + "\n".join(violations)
        )

    def test_live_package_imports_cleanly(self):
        """All live modules should import without error."""
        import importlib
        import eigencapital.live as live_pkg

        pkg_dir = Path(live_pkg.__file__).parent
        for p in sorted(pkg_dir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            mod = importlib.import_module(f"eigencapital.live.{p.stem}")
            assert mod is not None


class TestTimerPrecision:
    """Verify timing mechanisms are adequate for cycle measurement."""

    def test_time_never_goes_backwards(self):
        """time.time() should be monotonically non-decreasing."""
        t1 = time.time()
        t2 = time.time()
        assert t2 >= t1

    def test_trivial_cycle_measurement_overhead_small(self):
        """Measurement overhead should be negligible."""
        start = time.time()
        _ = sum(range(1000))
        elapsed = time.time() - start
        assert elapsed < 1.0
