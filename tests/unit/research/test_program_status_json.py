"""Guard: reports/research_program/program_status.json must stay aligned with the
frozen research program record.

Governance rule (docs/research/RESEARCH_PROGRAM_STATUS.md): in any disagreement
between the JSON and the document, the DOCUMENT governs and the JSON must be
corrected to match. This test therefore checks only the invariants that are
frozen by governance — stage verdict kinds, trial-slot accounting, the
production-boundary flags, and the reopening-rule count — so that the JSON can
never silently drift into contradicting the frozen record (e.g. by presenting a
parked stage as passed, or research as able to modify R4).
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAM_JSON = REPO_ROOT / "reports" / "research_program" / "program_status.json"
STATUS_DOC = REPO_ROOT / "docs" / "research" / "RESEARCH_PROGRAM_STATUS.md"


@pytest.fixture(scope="module")
def program() -> dict:
    assert PROGRAM_JSON.exists(), (
        "reports/research_program/program_status.json is the canonical "
        "machine-readable program record and must exist in the tree"
    )
    return json.loads(PROGRAM_JSON.read_text(encoding="utf-8"))


class TestRecordIntegrity:
    def test_governing_document_is_named_and_governs(self, program: dict) -> None:
        assert program["authority"]["governing_document"] == ("docs/research/RESEARCH_PROGRAM_STATUS.md")
        assert program["authority"]["precedence"] == "document_governs"

    def test_queue_is_closed(self, program: dict) -> None:
        assert program["status"] == "RESEARCH QUEUE CLOSED"
        assert program["queue_closed"] is True


class TestProductionBoundary:
    def test_research_cannot_modify_r4(self, program: dict) -> None:
        assert program["production_boundary"]["production_strategy_modifiable_by_research"] is False
        boundary = program["production_boundary"]
        assert "Nothing in R0-R6 constitutes permission to alter frozen R4" in boundary["statement"]

    def test_r4s_is_the_only_production_decision_path(self, program: dict) -> None:
        assert program["production_boundary"]["r4s_forward_soak_only_production_decision_path"] is True

    def test_no_stage_can_modify_r4(self, program: dict) -> None:
        assert len(program["stages"]) == 9
        assert all(stage["can_modify_r4"] is False for stage in program["stages"])


class TestStageVerdicts:
    def test_verdict_kinds_match_frozen_record(self, program: dict) -> None:
        expected = {
            "R0": "COMPLETE",
            "R1": "COMPLETE_FROZEN",
            "R2": "COMPLETE_FROZEN",
            "R3": "COMPLETE_FALSIFIED",
            "R4": "CLOSED_PARKED",
            "R5": "COMPLETE_FROZEN",
            "R6": "CLOSED_PARKED",
            "R7": "BLOCKED_DATA",
            "R8": "DEFERRED",
        }
        actual = {stage["id"]: stage["verdict_kind"] for stage in program["stages"]}
        assert actual == expected

    def test_verdict_text_matches_document_phrasing(self, program: dict) -> None:
        by_id = {stage["id"]: stage for stage in program["stages"]}
        # Exact verdict strings as recorded in the governing document.
        assert by_id["R1"]["verdict"] == "COMPLETE / FROZEN"
        assert by_id["R3"]["verdict"] == "COMPLETE / H1 FALSIFIED"
        assert by_id["R4"]["verdict"] == "INCONCLUSIVE -> CLOSED / PARKED"
        assert by_id["R6"]["verdict"] == "INCONCLUSIVE -> CLOSED / PARKED"
        assert by_id["R7"]["verdict"] == "BLOCKED - DATA"
        assert by_id["R8"]["verdict"] == "DEFERRED"

    def test_no_validated_verdict_exists_anywhere(self, program: dict) -> None:
        vocab = program["result_vocabulary"]
        assert vocab["VALIDATED"]["exists_in_eigencapital_research"] is False
        for stage in program["stages"]:
            assert "VALIDATED" not in stage["verdict"].upper().replace("UNVALIDATED", "")

    def test_blocked_and_deferred_stages_have_no_artifacts(self, program: dict) -> None:
        by_id = {stage["id"]: stage for stage in program["stages"]}
        assert by_id["R7"]["artifacts"] == []
        assert by_id["R8"]["artifacts"] == []
        assert by_id["R7"]["ledger"] is None
        assert by_id["R8"]["ledger"] is None


class TestTrialSlotLedger:
    def test_six_slots_consumed(self, program: dict) -> None:
        ledger = program["trial_slot_ledger"]
        assert ledger["slots_consumed"] == 6
        assert len(ledger["slots"]) == 6

    def test_slot_outcomes_match_governance_vocabulary(self, program: dict) -> None:
        expected = {
            "R2-B1": "REJECTED",
            "R3-B1": "FALSIFIED",
            "R4-B1": "INCONCLUSIVE",
            "R4-B2": "PARKED",
            "R6-B1": "INCONCLUSIVE",
        }
        actual = {slot["slot"]: slot["outcome"] for slot in program["trial_slot_ledger"]["slots"]}
        for slot_id, outcome in expected.items():
            assert actual[slot_id].startswith(outcome), slot_id


class TestReopeningRules:
    def test_four_frozen_reopening_rules(self, program: dict) -> None:
        rules = program["reopening_rules"]
        assert rules["status"] == "FROZEN"
        assert len(rules["rules"]) == 4

    def test_data_upgrade_contract_is_not_authorization(self, program: dict) -> None:
        contract = program["reopening_rules"]["data_upgrade_contract"]
        assert contract["document"] == "docs/research/DATA_REQUIREMENTS.md"
        assert "NOT a preregistration" in contract["status"]


class TestDocumentJsonAlignment:
    def test_status_doc_still_declares_json_as_machine_record(self) -> None:
        text = STATUS_DOC.read_text(encoding="utf-8")
        assert "reports/research_program/program_status.json" in text
        # Governance precedence must remain: document governs, JSON corrected to match.
        assert "this document governs" in text

    def test_artifact_note_matches_document(self, program: dict) -> None:
        text = STATUS_DOC.read_text(encoding="utf-8")
        assert "not present in the current checkout" in text
        assert "remain authoritative" in text
        assert "pruned" in program["artifact_availability_note"]
