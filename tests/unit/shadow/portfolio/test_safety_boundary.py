"""Safety boundary tests (brief Sections 17/18 — Safety).

Proves, mechanically and structurally:
    1. The shadow portfolio package contains NO execution imports or order
       vocabulary (no broker, no order submission, no MT5).
    2. ShadowSelector exposes no submission capability.
    3. A shadow decision record is NOT an order intent (disjoint schema).
    4. The recorder refuses every frozen R4 evidence filename.
    5. The runner script never references the loop's execution functions.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from eigencapital.shadow.portfolio.selector import ShadowSelector, ShadowSelectorConfig
from eigencapital.shadow.portfolio.tracker import (
    PROTECTED_R4_EVIDENCE_FILES,
    ShadowDecisionRecorder,
)

REPO = Path(__file__).resolve().parents[4]
PACKAGE_DIR = REPO / "src" / "eigencapital" / "shadow" / "portfolio"
RUNNER = REPO / "scripts" / "r4_shadow_portfolio.py"

FORBIDDEN_IMPORTS = (
    "eigencapital.execution",
    "eigencapital.live.broker",
    "mt5linux",
    "MetaTrader5",
    "order_send",
)

# Execution vocabulary. NOTE: the literal filename "order_intents.jsonl"
# appears in tracker.py as a PROTECTED-file guard (refusing to write there)
# — that is a safety feature, not an execution path, and is covered by
# TestRecorderIsolation. So it is deliberately absent from this list.
FORBIDDEN_TOKENS = (
    "order_send",
    "submit_order",
    "positions_get",
    "execute_orders",
    "emergency_flatten",
    "TRADE_ACTION_DEAL",
    "mt5.order",
)

ORDER_INTENT_KEYS = {"symbol", "side", "quantity", "order_type", "ticket", "limit_price", "timestamp_utc"}


class TestPackageHasNoExecutionPath:
    def test_no_forbidden_imports(self):
        for py in PACKAGE_DIR.glob("*.py"):
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith(FORBIDDEN_IMPORTS), f"{py.name}: {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert not mod.startswith(FORBIDDEN_IMPORTS), f"{py.name}: {mod}"

    def test_no_forbidden_tokens(self):
        for py in PACKAGE_DIR.glob("*.py"):
            src = py.read_text()
            for tok in FORBIDDEN_TOKENS:
                assert tok not in src, f"{py.name} contains execution token {tok!r}"

    def test_selector_has_no_submission_capability(self):
        selector = ShadowSelector(ShadowSelectorConfig())
        for name in dir(selector):
            assert "submit" not in name.lower()
            assert "order" not in name.lower()
        assert not hasattr(selector, "broker")
        assert not hasattr(selector, "mt5")


class TestDecisionIsNotOrderIntent:
    def test_schema_disjoint_from_order_intent(self):
        """Shadow decision records share no keys with order intents."""
        candidates = []
        decision = ShadowSelector(ShadowSelectorConfig()).select(
            candidates, None, [], cycle_id="C", decision_timestamp="t", signal_date="d"
        )
        record = decision.to_dict()
        top_keys = set(record.keys())
        assert not (top_keys & ORDER_INTENT_KEYS), f"overlap: {top_keys & ORDER_INTENT_KEYS}"
        # And the serialized form stays schema-stable.
        assert json.dumps(record, default=str)


class TestRecorderIsolation:
    def test_refuses_every_protected_file(self, tmp_path: Path):
        for name in sorted(PROTECTED_R4_EVIDENCE_FILES):
            with pytest.raises(PermissionError):
                ShadowDecisionRecorder._append(tmp_path / name, {"event": "leak"})

    def test_r4_evidence_files_byte_identical_after_shadow_recording(self, tmp_path: Path):
        """Running the shadow recorder must not alter pre-existing R4 evidence."""
        protected = tmp_path / "decisions.jsonl"
        protected.write_text('{"event": "r4_decisions"}\n')
        before = protected.read_bytes()

        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        decision = ShadowSelector(ShadowSelectorConfig()).select(
            [], None, [], cycle_id="C", decision_timestamp="t", signal_date="d"
        )
        recorder.record_decision(decision)
        recorder.record_outcome({"signal_date": "d", "symbol": "A"})

        assert protected.read_bytes() == before  # untouched
        assert (tmp_path / "shadow_portfolio_decisions.jsonl").exists()
        assert (tmp_path / "shadow_portfolio_outcomes.jsonl").exists()


class TestRunnerHasNoExecutionReferences:
    def test_runner_never_calls_execution_functions(self):
        src = RUNNER.read_text()
        for tok in ("execute_orders", "order_send", "emergency_flatten", "positions_get"):
            assert tok not in src, f"runner references execution path {tok!r}"

    def test_runner_writes_only_shadow_namespace(self):
        src = RUNNER.read_text()
        # The runner delegates persistence to ShadowDecisionRecorder and must
        # not construct any literal path to the frozen R4 evidence files.
        assert "ShadowDecisionRecorder" in src
        for name in PROTECTED_R4_EVIDENCE_FILES:
            assert f'"{name}"' not in src
            assert f"'{name}'" not in src
