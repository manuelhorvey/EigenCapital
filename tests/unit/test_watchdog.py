"""Regression tests for H-5: watchdog liveness probe (``process_alive``).

A bare ``pgrep -f <substring>`` matches unrelated processes (a grep of the
name, a different script with a similar name) and would report a dead loop
as healthy — that false ``True`` is what reaches ``loop_health.json``. These
tests pin the probe contract:

* live holder PID in the PID file -> alive (PID file preferred over pgrep);
* dead holder PID -> not alive, with no pgrep fallback, so loop health can
  never claim liveness for a dead holder;
* stale/invalid/missing PID file -> pgrep fallback;
* the pgrep fallback is an anchored full match that rejects unrelated
  similarly-named processes while still finding the real loop script.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from eigencapital.live.watchdog import ProbeResult, Watchdog, WatchState, process_alive

# Unique canary name: a real trading loop on the host must never match it,
# so every assertion here is hermetic.
CANARY = "h5_watchdog_canary"


def _bare_pgrep_matches(needle: str) -> bool:
    """What the old unanchored probe (``pgrep -f <needle>``) would report."""
    return subprocess.run(["pgrep", "-f", needle], capture_output=True).returncode == 0


def _wait_until_bare_match(needle: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _bare_pgrep_matches(needle):
            return
        time.sleep(0.05)
    raise AssertionError(f"no process matching {needle!r} appeared within {timeout}s")


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    proc.kill()
    proc.wait(timeout=5)


def _spawn(script: Path) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen([sys.executable, str(script)])
    try:
        _wait_until_bare_match(str(script))
    except AssertionError:
        _terminate(proc)
        raise
    return proc


def _reaped_dead_pid() -> int:
    """PID of a child that has exited *and* been reaped (so os.kill fails)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    return proc.pid


@pytest.fixture
def real_loop(tmp_path: Path) -> Iterator[subprocess.Popen[bytes]]:
    """A process whose cmdline matches the anchored pgrep fallback."""
    script = tmp_path / f"{CANARY}.py"
    script.write_text("import time\ntime.sleep(60)\n")
    proc = _spawn(script)
    try:
        yield proc
    finally:
        _terminate(proc)


@pytest.fixture
def similar_named_process(tmp_path: Path) -> Iterator[subprocess.Popen[bytes]]:
    """Not the loop: a different script whose name merely starts with CANARY."""
    script = tmp_path / f"{CANARY}_v2.py"
    script.write_text("import time\ntime.sleep(60)\n")
    proc = _spawn(script)
    try:
        yield proc
    finally:
        _terminate(proc)


def test_live_pid_file_reports_alive(tmp_path: Path) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text(str(os.getpid()))
    # No CANARY process exists, so the pgrep fallback would answer False:
    # this also proves the PID file is preferred over pgrep.
    assert not _bare_pgrep_matches(CANARY)
    assert process_alive(pattern=CANARY, pid_file=pid_file) is True


def test_dead_pid_reports_not_alive(tmp_path: Path) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text(str(_reaped_dead_pid()))
    assert process_alive(pattern=CANARY, pid_file=pid_file) is False


def test_dead_holder_pid_not_resurrected_by_unrelated_process(
    tmp_path: Path,
    similar_named_process: subprocess.Popen[bytes],
) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text(str(_reaped_dead_pid()))
    # The old bare-substring probe matched the unrelated process and claimed
    # liveness for the dead holder; loop_health.json inherited that lie.
    assert _bare_pgrep_matches(CANARY)
    assert process_alive(pattern=CANARY, pid_file=pid_file) is False


@pytest.mark.parametrize(
    "content",
    ["not-a-pid", "", "   ", "-1", "0", "12.5", str(2**22 + 1)],
)
def test_stale_or_invalid_pid_file_falls_back_to_pgrep(
    tmp_path: Path,
    content: str,
    real_loop: subprocess.Popen[bytes],
) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text(content)
    assert process_alive(pattern=CANARY, pid_file=pid_file) is True


def test_stale_pid_file_without_loop_reports_not_alive(tmp_path: Path) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text("not-a-pid")
    assert not _bare_pgrep_matches(CANARY)
    assert process_alive(pattern=CANARY, pid_file=pid_file) is False


def test_missing_pid_file_falls_back_to_pgrep(
    tmp_path: Path,
    real_loop: subprocess.Popen[bytes],
) -> None:
    assert process_alive(pattern=CANARY, pid_file=tmp_path / "absent.pid") is True


def test_pgrep_fallback_detects_the_real_loop_script(
    real_loop: subprocess.Popen[bytes],
) -> None:
    assert process_alive(pattern=CANARY, pid_file=None) is True


def test_pgrep_fallback_ignores_similarly_named_process(
    similar_named_process: subprocess.Popen[bytes],
) -> None:
    # Old behaviour: the bare substring reported the loop healthy here.
    assert _bare_pgrep_matches(CANARY)
    assert process_alive(pattern=CANARY, pid_file=None) is False


def test_pgrep_fallback_ignores_grep_of_the_process_name(tmp_path: Path) -> None:
    fifo = tmp_path / "holder.fifo"
    os.mkfifo(fifo)
    # `grep <name> <fifo>` blocks opening the FIFO, keeping the classic
    # self-match process (a grep for the loop name) alive for the probe.
    grep = subprocess.Popen(["grep", "--", CANARY, str(fifo)])
    try:
        _wait_until_bare_match(CANARY)
        assert process_alive(pattern=CANARY, pid_file=None) is False
    finally:
        _terminate(grep)


def test_dead_holder_pid_probe_never_claims_loop_health(tmp_path: Path) -> None:
    pid_file = tmp_path / "loop.pid"
    pid_file.write_text(str(_reaped_dead_pid()))
    alive = process_alive(pattern=CANARY, pid_file=pid_file)
    probe = ProbeResult(
        process_alive=alive,
        trail_age_seconds=0.0,
        equity_read_ok=True,
        broker_reachable=True,
        evidence_hash="h5",
    )
    watchdog = Watchdog(
        stale_after_seconds=1.0,
        blind_after_seconds=2.0,
        contain_after_seconds=3.0,
    )
    decision = watchdog.evaluate(probe)
    assert alive is False
    assert decision.state is not WatchState.NORMAL
    assert decision.evidence["probe"]["process_alive"] is False
