"""Loop integration tests for the rebalance policy gate (EXP-000002).

Proves the Sections 28/32 invariants at the loop boundary:
  1. Default (no env var) selects CANONICAL → the policy layer never vetoes
     or filters, so run_cycle behavior is identical to pre-research.
  2. The policy gate sits AFTER risk gates/order generation and BEFORE
     execution — a HOLD cannot suppress a risk response (hard gates return
     earlier, fail-closed).
  3. The policy writes ONLY its own evidence files: rebalance_policy_state.json
     and rebalance_policy_decisions.jsonl. Frozen R4 evidence
     (runtime_state.json, decisions.jsonl, order_intents.jsonl) is untouched
     by the policy helpers.
  4. Policy state restore after restart prevents double-trading.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_loop_module():
    spec = importlib.util.spec_from_file_location(
        "r4_rebalance_loop_rebtest", REPO / "scripts" / "r4_rebalance_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop_rebtest"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPolicySelectionAndDefaults:
    def test_default_policy_is_canonical(self):
        loop = _load_loop_module()
        assert loop._rebalance_policy.config.policy_id == "R4-REB-CANONICAL"

    def test_env_selects_threshold(self, monkeypatch):
        monkeypatch.setenv("R4_REBALANCE_POLICY", "THRESHOLD")
        monkeypatch.setenv("R4_REB_THRESHOLD", "0.02")
        import subprocess

        code = (
            "import importlib.util,sys;"
            "spec=importlib.util.spec_from_file_location('m',"
            f"{str(REPO / 'scripts' / 'r4_rebalance_loop.py')!r});"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            "print(m._rebalance_policy.config.policy_id)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={
                **__import__("os").environ,
                "R4_REBALANCE_POLICY": "THRESHOLD",
                "R4_REB_THRESHOLD": "0.02",
            },
        )
        assert out.stdout.strip() == "R4-REB-T020"

    def test_env_invalid_policy_rejected(self, monkeypatch):
        monkeypatch.setenv("R4_REBALANCE_POLICY", "HOURLY")
        import subprocess

        # NOTE: no semicolons before compound statements — the snippet is
        # parsed as a real program (a `try:` after `;` is a SyntaxError).
        code = (
            "import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('m', {str(REPO / 'scripts' / 'r4_rebalance_loop.py')!r})\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "try:\n"
            "    spec.loader.exec_module(m)\n"
            "    print('NO-ERROR')\n"
            "except ValueError:\n"
            "    print('REJECTED')\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "REJECTED"


class TestGatePlacement:
    def test_policy_gate_after_aligned_before_intents(self):
        """The gate must run after order generation/alignment checks and
        before order-intent persistence/execution (source-order proof)."""
        loop = _load_loop_module()
        src = inspect.getsource(loop.run_cycle)
        idx_aligned = src.find('"status": "ALIGNED"')
        idx_gate = src.find("_evaluate_rebalance_policy(")
        idx_intents = src.find("_persist_order_intents(")
        assert -1 < idx_aligned < idx_gate < idx_intents, "gate misordered"

    def test_canonical_never_filters(self):
        loop = _load_loop_module()
        # CANONICAL decision permits every symbol; filter is a no-op.
        orders = [("EURUSD", "BUY", 0.01, "LONG +5.0% (5.0% |w|)", None)]
        import pandas as pd

        decision = loop._rebalance_policy.should_rebalance(
            current_weights={"EURUSD": 0.04},
            target_weights=pd.Series({"EURUSD": 0.05}),
            signal_timestamp=None,
            now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        assert decision.policy_id == "R4-REB-CANONICAL"
        assert loop._apply_policy_to_orders(orders, decision) == orders

    def test_threshold_policy_filters_banded_symbols(self):
        loop = _load_loop_module()
        from datetime import UTC, datetime

        from eigencapital.live.rebalance_policy import PolicyConfig, PolicyType, build_policy

        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.01))
        decision = policy.should_rebalance(
            current_weights={"EURUSD": 0.05, "GBPUSD": 0.05},
            target_weights={"EURUSD": 0.055, "GBPUSD": 0.07},
            signal_timestamp=None,
            now=datetime.now(UTC),
        )
        assert decision.action.value == "TRADE"
        orders = [
            ("EURUSD", "BUY", 0.01, "adjust", None),  # banded → dropped
            ("GBPUSD", "BUY", 0.01, "adjust", None),  # outside band → kept
        ]
        filtered = loop._apply_policy_to_orders(orders, decision)
        assert [o[0] for o in filtered] == ["GBPUSD"]


class TestEvidenceIsolation:
    def test_policy_state_file_is_separate(self, tmp_path: Path):
        from eigencapital.live.rebalance_policy import (
            PolicyConfig,
            PolicyType,
            build_policy,
            load_policy_state,
            save_policy_state,
        )

        # Frozen runtime state file untouched by policy helpers.
        runtime = tmp_path / "runtime_state.json"
        runtime.write_text('{"recovery_state": "connected"}\n')
        before = runtime.read_bytes()

        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        policy.state.last_rebalance_day = "2026-09-16"
        save_policy_state(tmp_path, policy.state)
        policy2 = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        load_policy_state(tmp_path, policy2)

        assert runtime.read_bytes() == before  # frozen file byte-identical
        assert (tmp_path / "rebalance_policy_state.json").exists()
        assert policy2.state.last_rebalance_day == "2026-09-16"

    def test_ledger_does_not_write_protected_files(self, tmp_path: Path):
        from eigencapital.live.rebalance_policy import (
            DecisionAction,
            DecisionReason,
            PolicyType,
            RebalanceDecision,
            RebalancePolicyLedger,
        )

        for name in ("decisions.jsonl", "order_intents.jsonl", "shadow_decisions.jsonl"):
            (tmp_path / name).write_text("frozen\n")
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

        ledger = RebalancePolicyLedger(tmp_path)
        decision = RebalanceDecision(
            action=DecisionAction.TRADE,
            reason=DecisionReason.NEW_SIGNAL,
            policy_type=PolicyType.CANONICAL,
            policy_id="R4-REB-CANONICAL",
            policy_version="1.0",
        )
        ledger.record(cycle_id="C1", decision=decision, target_weights={}, current_weights={}, target_hash="x")
        after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        for name, data in before.items():
            assert after[name] == data  # protected files byte-identical
        assert (tmp_path / "rebalance_policy_decisions.jsonl").exists()

    def test_cycle_result_statuses_exist(self):
        loop = _load_loop_module()
        src = inspect.getsource(loop.run_cycle)
        assert '"status": "POLICY_HOLD"' in src
        assert '"status": "POLICY_ALIGNED"' in src
        # CANONICAL path never returns these (only non-canonical policies do).
        assert '"status": "EXECUTED"' in src


class TestRestartNoDoubleTrade:
    def test_daily_restart_idempotent_via_loop_module(self, tmp_path: Path):
        from datetime import UTC, datetime, timedelta

        from eigencapital.live.rebalance_policy import (
            PolicyConfig,
            PolicyType,
            build_policy,
            load_policy_state,
            save_policy_state,
        )

        # Fixed mid-day timestamp (same convention as test_rebalance_policy.NOW):
        # datetime.now(UTC) + 1h crosses the UTC midnight boundary when this test
        # runs between 23:00-23:59 UTC, and DailyPolicy would (correctly) allow a
        # next-day intervention — flaky false failure. A fixed clock makes the
        # restart-idempotency check deterministic at any wall-clock time.
        now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        d1 = policy.should_rebalance(current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=now)
        assert d1.action.value == "TRADE"
        policy.record_trade(now, d1)
        save_policy_state(tmp_path, policy.state)

        restarted = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        load_policy_state(tmp_path, restarted)
        d2 = restarted.should_rebalance(
            current_weights={"A": 0.05},
            target_weights={"A": 0.06},
            signal_timestamp=None,
            now=now + timedelta(hours=1),
        )
        assert d2.action.value == "HOLD"
        assert d2.reason.value == "ALREADY_TRADED_PERIOD"
