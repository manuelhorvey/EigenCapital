"""Shared fixtures for the execution unit suite.

``AuditLog`` persists every emitted event to a durable store and resolves a
``reports/``-relative default path. Point that default at a per-test temp
file so no test can see events left behind by another test (or by an earlier
run of the suite) — tests that need a specific store still inject
``store_path`` explicitly. Mirrors ``tests/unit/live/conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_audit_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIGENCAPITAL_EXECUTION_AUDIT_STORE", str(tmp_path / "execution_audit.jsonl"))
