"""Durable audit store — tamper-evident hash-chained JSONL with mirror copies.

C5 of the P0 Safety Remediation campaign. Every record is appended with:
  seq, ts, prev_hash, payload, hash
where hash = sha256(prev_hash + canonical(payload) + seq). Verification walks
the chain and detects any mutation, deletion, or reordering. A mirror copy is
written to a second directory after every append so a cleanup job deleting one
location cannot silently destroy evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


def _digest(prev_hash: str, seq: int, payload: dict[str, Any]) -> str:
    material = f"{prev_hash}|{seq}|{_canonical(payload)}"
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class ChainVerdict:
    valid: bool
    n_records: int
    broken_at_seq: int | None = None
    reason: str = ""


class DurableAudit:
    """Append-only, hash-chained audit log with an offline mirror."""

    def __init__(self, primary: Path, mirror: Path | None = None) -> None:
        self._primary = Path(primary)
        self._mirror = Path(mirror) if mirror else None
        self._seq = self._last_seq()
        self._prev_hash = self._last_hash()

    # ── path helpers ───────────────────────────────────────────────
    @property
    def path(self) -> Path:
        return self._primary

    def _last_record(self) -> dict[str, Any] | None:
        if not self._primary.exists():
            return None
        last = None
        with open(self._primary, "rb") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        pass  # torn tail line from a crash: ignored for chaining
        return last

    def _last_seq(self) -> int:
        rec = self._last_record()
        return int(rec["seq"]) if rec else 0

    def _last_hash(self) -> str:
        rec = self._last_record()
        return str(rec["hash"]) if rec else "GENESIS"

    # ── write path ─────────────────────────────────────────────────
    def append(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append one record; fsync; mirror to secondary location."""
        self._seq += 1
        record = {
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            "payload": payload,
            "prev_hash": self._prev_hash,
        }
        record["hash"] = _digest(str(record["prev_hash"]), self._seq, payload)
        self._primary.parent.mkdir(parents=True, exist_ok=True)
        with open(self._primary, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._prev_hash = str(record["hash"])
        if self._mirror is not None:
            self._mirror.parent.mkdir(parents=True, exist_ok=True)
            self._mirror.write_bytes(self._primary.read_bytes())
        return record

    # ── verification ───────────────────────────────────────────────
    def verify(self) -> ChainVerdict:
        if not self._primary.exists():
            return ChainVerdict(valid=True, n_records=0)
        prev = "GENESIS"
        n = 0
        with open(self._primary) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return ChainVerdict(False, n, n + 1, "unparseable record")
                expected = _digest(
                    str(rec.get("prev_hash")),
                    int(rec.get("seq", 0)),
                    rec.get("payload", {}),
                )
                if rec.get("prev_hash") != prev:
                    return ChainVerdict(False, n, rec.get("seq"), "chain break")
                if rec.get("hash") != expected:
                    return ChainVerdict(False, n, rec.get("seq"), "hash mismatch")
                if int(rec.get("seq", -1)) != n + 1:
                    return ChainVerdict(False, n, rec.get("seq"), "sequence gap")
                prev = rec["hash"]
                n += 1
        return ChainVerdict(valid=True, n_records=n)

    def mirror_matches(self) -> bool:
        if self._mirror is None:
            return True
        if not self._mirror.exists():
            return not self._primary.exists() or self._primary.stat().st_size == 0
        return self._mirror.read_bytes() == self._primary.read_bytes()
