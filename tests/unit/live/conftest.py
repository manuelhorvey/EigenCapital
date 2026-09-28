"""Shared fixtures for the live unit suite.

``CampaignManager`` persists its history to a durable store and resolves a
``reports/``-relative default path. Point that default at a per-test temp
file so no test can see campaigns/events left behind by another test (or by
an earlier run of the suite) — tests that need a specific store still inject
``store_path`` explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_campaign_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIGENCAPITAL_CAMPAIGN_STORE", str(tmp_path / "campaigns.jsonl"))
