"""Process Supervisor Tests — prove duplicate prevention and health tracking."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.supervisor import ProcessSupervisor

REPO_ROOT = Path(__file__).resolve().parents[2]


def _child_env() -> dict[str, str]:
    """Environment that lets subprocesses import eigencapital from src/."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (os.pathsep + existing if existing else "")
    return env


# Two claimants barrier on a shared wall-clock start time, race
# claim_instance() against the same state dir, and — if one wins — hold the
# claim until the other has recorded its refusal. Holding matters: without it
# the winner could release before the loser even tried, and two sequential
# claims would mask the race this test exists to catch.
_CONCURRENT_CLAIMANT = """
import sys
import time
from pathlib import Path

from eigencapital.live.supervisor import ProcessSupervisor

state_dir = sys.argv[1]
role = sys.argv[2]
start_at = float(sys.argv[3])
other = "1" if role == "0" else "0"
state = Path(state_dir)

supervisor = ProcessSupervisor(state_dir=state_dir)

deadline = time.monotonic() + 15.0
while time.time() < start_at:
    if time.monotonic() > deadline:
        print("timed out waiting for the shared start time", file=sys.stderr, flush=True)
        sys.exit(2)

won = supervisor.claim_instance()
(state / ("result_" + role)).write_text("win" if won else "lose")

if won:
    wait_deadline = time.monotonic() + 15.0
    while not (state / ("result_" + other)).exists():
        if time.monotonic() > wait_deadline:
            break
        time.sleep(0.01)
    supervisor.release()
sys.exit(0)
"""

_SOLO_CLAIMANT = """
import sys

from eigencapital.live.supervisor import ProcessSupervisor

supervisor = ProcessSupervisor(state_dir=sys.argv[1])
won = supervisor.claim_instance()
print("WIN" if won else "LOSE", flush=True)
if won:
    supervisor.release()
sys.exit(0)
"""


def _await_claimant_results(state: Path, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    results: dict[str, str] = {}
    while time.monotonic() < deadline and len(results) < 2:
        for role in ("0", "1"):
            if role not in results:
                result_file = state / f"result_{role}"
                if result_file.exists():
                    results[role] = result_file.read_text().strip()
        if len(results) < 2:
            time.sleep(0.05)
    return results


def _reap(procs: list[subprocess.Popen[str]]) -> list[str]:
    """Wait for children, killing any that hang; return their combined output."""
    output: list[str] = []
    for proc in procs:
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=30)
        output.append(f"rc={proc.returncode} stdout={stdout!r} stderr={stderr!r}")
    return output


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

    def test_stale_dead_pid_is_reclaimed(self, supervisor, tmp_dir):
        """A PID file left behind by a dead process must not block a claim."""
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=30)
        pid_file = Path(tmp_dir) / "supervisor.pid"
        pid_file.write_text(str(dead.pid))

        assert supervisor.claim_instance() is True
        assert pid_file.read_text().strip() == str(os.getpid())
        assert supervisor.state is not None
        assert supervisor.state.pid == os.getpid()


class TestAtomicClaim:
    """C-4: claim_instance must be atomic — no check-then-write window."""

    ROUNDS = 3

    def test_claim_refused_while_lock_is_held(self, supervisor, tmp_dir):
        """A claimant must serialise through the shared lock file.

        The state dir is empty here, so without lock serialisation this
        claim would win; only an exclusive flock on supervisor.lock makes
        it fail while another process sits in its critical section.
        """
        lock_fd = open(Path(tmp_dir) / "supervisor.lock", "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert supervisor.claim_instance() is False
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        assert supervisor.claim_instance() is True

    def test_exactly_one_of_two_concurrent_claimants_wins(self, tmp_dir):
        """Two processes racing the claim: exactly one may win, every round."""
        state = Path(tmp_dir)
        for attempt in range(self.ROUNDS):
            for stale in state.iterdir():
                stale.unlink(missing_ok=True)
            start_at = time.time() + 1.0
            procs = [
                subprocess.Popen(
                    [sys.executable, "-c", _CONCURRENT_CLAIMANT, tmp_dir, role, repr(start_at)],
                    env=_child_env(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for role in ("0", "1")
            ]
            try:
                results = _await_claimant_results(state, timeout=30.0)
            finally:
                diagnostics = _reap(procs)
            assert set(results) == {"0", "1"}, f"round {attempt}: claimants did not finish: {results}; {diagnostics}"
            assert sorted(results.values()) == ["lose", "win"], (
                f"round {attempt}: expected exactly one winner, got {results}; {diagnostics}"
            )


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

    def test_release_does_not_break_a_subsequent_claim(self, supervisor, tmp_dir):
        """A released claim must be immediately claimable again."""
        assert supervisor.claim_instance() is True
        supervisor.release()
        assert not (Path(tmp_dir) / "supervisor.pid").exists()

        fresh = ProcessSupervisor(state_dir=tmp_dir)
        assert fresh.claim_instance() is True
        assert fresh.state is not None
        assert fresh.state.pid == os.getpid()

    def test_release_frees_the_claim_for_another_process(self, supervisor, tmp_dir):
        """After release, a different OS process must be able to claim."""
        assert supervisor.claim_instance() is True
        supervisor.release()
        assert not (Path(tmp_dir) / "supervisor.pid").exists()

        out = subprocess.run(
            [sys.executable, "-c", _SOLO_CLAIMANT, tmp_dir],
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "WIN"


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
