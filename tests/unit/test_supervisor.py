"""Process Supervisor Tests — prove duplicate prevention and health tracking."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.supervisor import ProcessSupervisor


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def supervisor(tmp_dir):
    return ProcessSupervisor(state_dir=tmp_dir)


class TestClaimInstance:
    """Test instance claiming and duplicate prevention."""

    def test_first_claim_succeeds(self, supervisor):
        """First claim should succeed."""
        assert supervisor.claim_instance() is True

    def test_second_claim_same_pid_succeeds(self, supervisor):
        """Re-claiming with same PID should succeed."""
        assert supervisor.claim_instance() is True
        assert supervisor.claim_instance() is True

    def test_state_persisted_after_claim(self, supervisor, tmp_dir):
        """State should be persisted to disk after claim."""
        supervisor.claim_instance()
        state_file = Path(tmp_dir) / "supervisor_state.json"
        assert state_file.exists()
        with open(state_file) as f:
            data = json.load(f)
        assert data["pid"] == os.getpid()
        assert data["status"] == "running"

    def test_pid_file_created(self, supervisor, tmp_dir):
        """PID file should be created after claim."""
        supervisor.claim_instance()
        pid_file = Path(tmp_dir) / "supervisor.pid"
        assert pid_file.exists()
        assert int(pid_file.read_text()) == os.getpid()

    def test_instance_id_generated(self, supervisor):
        """Instance ID should be generated on claim."""
        supervisor.claim_instance()
        assert supervisor.state is not None
        assert len(supervisor.state.instance_id) == 12

    def test_is_owner_after_claim(self, supervisor):
        """is_owner should be True after claiming."""
        supervisor.claim_instance()
        assert supervisor.is_owner


class TestMarkHealthy:
    """Test health marking."""

    def test_mark_healthy_updates_timestamp(self, supervisor):
        """mark_healthy should update last_healthy_at."""
        supervisor.claim_instance()
        before = supervisor.state.last_healthy_at
        supervisor.mark_healthy()
        assert supervisor.state.last_healthy_at >= before

    def test_health_file_written(self, supervisor, tmp_dir):
        """Health file should be written after mark_healthy."""
        supervisor.claim_instance()
        supervisor.mark_healthy()
        health_file = Path(tmp_dir) / "loop_health.json"
        assert health_file.exists()
        with open(health_file) as f:
            data = json.load(f)
        assert data["alive"] is True
        assert data["pid"] == os.getpid()


class TestRelease:
    """Test instance release."""

    def test_release_removes_pid_file(self, supervisor, tmp_dir):
        """Release should remove PID file."""
        supervisor.claim_instance()
        supervisor.release()
        pid_file = Path(tmp_dir) / "supervisor.pid"
        assert not pid_file.exists()

    def test_release_writes_dead_health(self, supervisor, tmp_dir):
        """Release should write dead health status."""
        supervisor.claim_instance()
        supervisor.release()
        health_file = Path(tmp_dir) / "loop_health.json"
        with open(health_file) as f:
            data = json.load(f)
        assert data["alive"] is False


class TestMarkFrozen:
    """Test frozen state."""

    def test_mark_frozen(self, supervisor):
        """mark_frozen should set status to frozen."""
        supervisor.claim_instance()
        supervisor.mark_frozen(reason="too many failures")
        assert supervisor.state.status == "frozen"


class TestRestartCount:
    """Test restart count tracking."""

    def test_restart_count_increments(self, supervisor):
        """Restart count should increment."""
        supervisor.claim_instance()
        assert supervisor.state.restart_count == 0
        count = supervisor.increment_restart_count()
        assert count == 1
        count = supervisor.increment_restart_count()
        assert count == 2


class TestHealthStatus:
    """Test external health status."""

    def test_health_status_before_anything(self, supervisor):
        """Health status should return defaults when no health file."""
        status = supervisor.get_health_status()
        assert status["alive"] is False
