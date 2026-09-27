"""Single-instance guard for scripts/r4_rebalance_loop.py (EC-REL-001).

Two live rebalance processes interleave the append-only ledgers in
reports/r4_loop with different cycle counters and can double-submit orders.
The guard claims reports/r4_loop/supervisor.pid before any ledger write or
broker call; a second live instance is refused with exit 75.

The loop module is imported read-only exactly as the immutability and T0
sizing tests do. No broker is contacted; claims run against a tmp state dir.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_loop_module():
    spec = importlib.util.spec_from_file_location("r4_rebalance_loop_guard", REPO / "scripts" / "r4_rebalance_loop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def loop_mod(tmp_path, monkeypatch):
    mod = _load_loop_module()
    monkeypatch.setattr(mod, "AUDIT_DIR", str(tmp_path))
    return mod


class TestBypassPredicate:
    """--flatten and --verify-config must stay usable while a loop runs."""

    @pytest.mark.parametrize(
        "args",
        [
            ["--flatten"],
            ["--flatten", "--loop"],
            ["--verify-config"],
            ["--verify-config", "--loop", "--interval", "60"],
        ],
    )
    def test_operator_modes_bypass(self, loop_mod, args):
        assert loop_mod._instance_guard_bypassed(args) is True

    @pytest.mark.parametrize("args", [[], ["--loop"], ["--dry-run"], ["--loop", "--dry-run"], ["--interval", "60"]])
    def test_trading_modes_are_guarded(self, loop_mod, args):
        assert loop_mod._instance_guard_bypassed(args) is False


class TestClaim:
    def test_claim_writes_pid_and_restores_shutdown_handler(self, loop_mod, tmp_path):
        supervisor = loop_mod._claim_single_instance()
        assert supervisor is not None
        assert (tmp_path / "supervisor.pid").read_text().strip() == str(os.getpid())
        # claim_instance() swaps in its own SIGINT handler; the guard must
        # restore the loop's, otherwise Ctrl-C would never stop the loop.
        assert signal.getsignal(signal.SIGINT) is loop_mod._handle_signal
        if hasattr(signal, "SIGTERM"):
            assert signal.getsignal(signal.SIGTERM) is loop_mod._handle_signal
        supervisor.release()
        assert not (tmp_path / "supervisor.pid").exists()

    def test_stale_pid_file_is_reclaimed(self, loop_mod, tmp_path):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=30)
        (tmp_path / "supervisor.pid").write_text(str(dead.pid))

        supervisor = loop_mod._claim_single_instance()
        assert supervisor is not None
        assert (tmp_path / "supervisor.pid").read_text().strip() == str(os.getpid())
        supervisor.release()

    def test_stale_health_file_dropped_on_claim(self, loop_mod, tmp_path):
        (tmp_path / "loop_health.json").write_text('{"alive": false, "pid": 1}')

        supervisor = loop_mod._claim_single_instance()
        assert supervisor is not None
        # Stale alive:false would pin the dashboard at HALTED after restart.
        assert not (tmp_path / "loop_health.json").exists()
        supervisor.release()


class TestRefusal:
    def test_second_instance_is_refused_while_holder_alive(self, loop_mod, tmp_path, capsys):
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            (tmp_path / "supervisor.pid").write_text(str(holder.pid))

            assert loop_mod._claim_single_instance() is None
            out = capsys.readouterr().out
            assert "REFUSED TO START" in out
            assert str(holder.pid) in out
            # The refused process must leave the holder's claim untouched.
            assert (tmp_path / "supervisor.pid").read_text().strip() == str(holder.pid)
        finally:
            holder.terminate()
            holder.wait(timeout=30)
