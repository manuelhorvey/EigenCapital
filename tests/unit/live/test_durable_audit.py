"""Regression tests for C-3: durable_audit must lock across processes and
must never publish a torn/zeroed mirror.

Two failure modes are covered:

1. Concurrent appends from *multiple processes*. A threading.Lock alone does
   nothing across processes: each DurableAudit caches seq/prev_hash at
   construction, so two processes appending to the same file interleave,
   duplicate seq numbers, and break the hash chain. The fix is an
   inter-process flock around the read-head → append → fsync critical
   section.
2. A partial mirror write. The mirror must be published atomically
   (stage to a temp file, fsync, rename) so a crash mid-copy leaves the
   previous complete mirror in place — never a zeroed or truncated file.
"""

from __future__ import annotations

import fcntl
import json
import multiprocessing as mp
import os
from pathlib import Path

import pytest

from eigencapital.live.durable_audit import DurableAudit

N_WORKERS = 4
APPENDS_PER_WORKER = 6


def _worker(primary_str: str, mirror_str: str, worker_id: int, n: int) -> None:
    """Each process builds its own DurableAudit over the same files."""
    audit = DurableAudit(Path(primary_str), Path(mirror_str))
    for i in range(n):
        audit.append("evt", {"worker": worker_id, "i": i})


def _read_seqs(path: Path) -> list[int]:
    return [json.loads(line)["seq"] for line in path.read_text().splitlines() if line.strip()]


def test_concurrent_multiprocess_appends_keep_chain_intact(tmp_path: Path) -> None:
    primary = tmp_path / "audit.jsonl"
    mirror = tmp_path / "mirror" / "audit.jsonl"
    ctx = mp.get_context("fork")
    procs = [
        ctx.Process(target=_worker, args=(str(primary), str(mirror), w, APPENDS_PER_WORKER))
        for w in range(N_WORKERS)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    assert [p.exitcode for p in procs] == [0] * N_WORKERS

    total = N_WORKERS * APPENDS_PER_WORKER
    verdict = DurableAudit(primary).verify()
    assert verdict.valid, f"chain broken: {verdict.reason} at seq {verdict.broken_at_seq}"
    assert verdict.n_records == total
    # no duplicate or gapped seq numbers
    assert _read_seqs(primary) == list(range(1, total + 1))
    assert mirror.read_bytes() == primary.read_bytes()


def test_concurrent_appends_are_serialized_by_file_lock(tmp_path: Path) -> None:
    """append() must take an exclusive inter-process flock: while another
    process holds it, an append in a third process cannot complete."""
    primary = tmp_path / "audit.jsonl"
    DurableAudit(primary).append("e", {"n": 0})

    ctx = mp.get_context("fork")
    locked = ctx.Event()
    release = ctx.Event()
    done = ctx.Event()

    def _hold_lock() -> None:
        with open(primary, "a+b") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked.set()
            release.wait(timeout=30)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _try_append() -> None:
        DurableAudit(primary).append("e", {"n": 1})
        done.set()

    holder = ctx.Process(target=_hold_lock)
    applier = ctx.Process(target=_try_append)
    holder.start()
    try:
        assert locked.wait(timeout=30), "helper process never acquired the lock"
        applier.start()
        # Without a file lock this append finishes in milliseconds; with one
        # it must block until release below.
        assert not done.wait(timeout=1.5), "append ignored the inter-process lock"
        release.set()
        applier.join(timeout=30)
        assert done.is_set(), "append never completed after the lock was released"
        assert applier.exitcode == 0
    finally:
        release.set()
        holder.join(timeout=30)

    verdict = DurableAudit(primary).verify()
    assert verdict.valid and verdict.n_records == 2


def test_torn_mirror_write_never_truncates_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A torn staging write (partial copy) must never reach the mirror: the
    publish step renames only after a complete copy, so the mirror keeps the
    last complete content instead of being zeroed/truncated."""
    primary = tmp_path / "audit.jsonl"
    mirror = tmp_path / "mirror" / "audit.jsonl"
    audit = DurableAudit(primary, mirror)
    audit.append("e", {"n": 1})
    good = mirror.read_bytes()

    def _torn_publish(src: str, dst: str) -> None:
        # Simulate a crash mid-copy: the staged temp file is only partially
        # written, then the process dies before the atomic rename.
        staged = Path(src)
        data = staged.read_bytes()
        staged.write_bytes(data[: len(data) // 2])
        raise OSError("simulated crash mid mirror copy")

    monkeypatch.setattr(os, "replace", _torn_publish)
    with pytest.raises(OSError, match="simulated crash"):
        audit.append("e", {"n": 2})
    monkeypatch.undo()

    # The mirror still holds the complete previous copy — not zeroed/partial
    # — even though the primary already received record 2 before the crash.
    assert mirror.read_bytes() == good
    assert len(mirror.read_bytes().splitlines()) == 1
    assert len(primary.read_bytes().splitlines()) == 2

    # The next successful append republishes a complete mirror.
    audit.append("e", {"n": 3})
    assert mirror.read_bytes() == primary.read_bytes()
    assert not list(mirror.parent.glob("*.tmp"))
    assert DurableAudit(primary, mirror).verify().n_records == 3


def test_mirror_never_zero_length_after_appends(tmp_path: Path) -> None:
    primary = tmp_path / "audit.jsonl"
    mirror = tmp_path / "mirror" / "audit.jsonl"
    audit = DurableAudit(primary, mirror)
    for i in range(5):
        audit.append("e", {"n": i})
        assert mirror.exists()
        assert mirror.stat().st_size > 0
        assert mirror.read_bytes() == primary.read_bytes()


def test_interrupted_mirror_publish_keeps_previous_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the atomic rename itself fails (crash point), the mirror keeps the
    last complete copy rather than a zeroed file, and recovers on append."""
    primary = tmp_path / "audit.jsonl"
    mirror = tmp_path / "mirror" / "audit.jsonl"
    audit = DurableAudit(primary, mirror)
    audit.append("e", {"n": 1})
    good = mirror.read_bytes()

    def _boom(src: str, dst: str) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        audit.append("e", {"n": 2})
    monkeypatch.undo()

    assert mirror.read_bytes() == good
    audit.append("e", {"n": 3})
    assert mirror.read_bytes() == primary.read_bytes()
    assert DurableAudit(primary, mirror).verify().n_records == 3
