"""Audit tests for the Research Accounting Contract.

Guards the governance artifacts created at the intraday-branch freeze so
they cannot silently disappear or drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eigencapital.research.intraday import campaign7_rerun_hardened as gov
from eigencapital.research.intraday.campaign8_tf003_confirmation import (
    COST_ONE_WAY_ADVERSE,
    COST_ONE_WAY_BASE,
    bt_corrected,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestContractDocs:
    def test_ledger_exists_and_declares_freeze(self):
        p = REPO_ROOT / "docs" / "research" / "INTRADAY_RESEARCH_LEDGER.md"
        assert p.exists(), "intraday research ledger missing"
        text = p.read_text()
        assert "FROZEN" in text or "Frozen" in text
        assert "205" in text, "cumulative trial count must be recorded"

    def test_accounting_contract_exists_and_names_primitives(self):
        p = REPO_ROOT / "docs" / "RESEARCH_ACCOUNTING_CONTRACT.md"
        assert p.exists(), "accounting contract missing"
        text = p.read_text()
        for token in ["bt_corrected", "COST_ONE_WAY_BASE", "family_adjust", "cumulative_adjust"]:
            assert token in text, f"contract must reference {token}"

    def test_timeframe_freeze_doc_present(self):
        p = REPO_ROOT / "docs" / "research" / "INTRADAY_TIMEFRAME_BRANCH_FROZEN.md"
        assert p.exists()


class TestMandatoryPrimitivesImportable:
    def test_corrected_engine_signature(self):
        assert callable(bt_corrected)

    def test_cost_constants_locked(self):
        assert pytest.approx(6.5e-4) == COST_ONE_WAY_BASE
        assert pytest.approx(11e-4) == COST_ONE_WAY_ADVERSE

    def test_governance_counters_monotonic(self):
        assert gov.PRIOR_EVALUATIONS >= 133
        assert gov.CUMULATIVE_TRIALS > gov.PRIOR_EVALUATIONS
        assert callable(gov.family_adjust)
        assert callable(gov.cumulative_adjust)
