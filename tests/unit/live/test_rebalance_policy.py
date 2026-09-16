"""Unit tests for the RebalancePolicy abstraction (EXP-000002).

Covers brief Sections 4–9 and 24: policy selection, daily/weekly cadence,
threshold behavior and exact boundaries, exits/reversals/entries/removals,
hybrid events, restart persistence, idempotency, target hashing, turnover,
ledger isolation, and shadow evaluation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eigencapital.live.rebalance_policy import (
    CANONICAL_MIN_WEIGHT,
    DecisionAction,
    DecisionReason,
    PolicyConfig,
    PolicyType,
    RebalanceDecision,
    RebalanceEvents,
    RebalancePolicyLedger,
    build_policy,
    classify_symbol_event,
    compute_target_hash,
    compute_turnover,
    evaluate_all_policies,
    evaluate_symbol_band,
    experiment_matrix,
    load_policy_state,
    policy_from_env,
    save_policy_state,
)

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)


# ── Section 4/24: threshold classification and exact boundaries ────────


class TestThresholdSemantics:
    def test_exact_boundary_is_hold(self):
        # deviation == threshold belongs to the no-trade side (explicit).
        assert classify_symbol_event(0.06, 0.05, 0.01) == "adjustment_in"

    def test_just_above_boundary_trades(self):
        assert classify_symbol_event(0.0601, 0.05, 0.01) == "adjustment_out"

    def test_just_below_boundary_holds(self):
        assert classify_symbol_event(0.0599, 0.05, 0.01) == "adjustment_in"

    def test_new_entry_never_banded(self):
        assert classify_symbol_event(0.05, 0.0, 0.01) == "new_entry"
        # Sub-minimum current position still counts as flat (|w| <= min).
        assert classify_symbol_event(0.05, CANONICAL_MIN_WEIGHT, 0.01) == "new_entry"

    def test_full_exit_never_banded(self):
        assert classify_symbol_event(0.0, 0.05, 0.01) == "full_exit"
        # 0.004 target is "flat" by canonical convention → exit, not drift.
        assert classify_symbol_event(0.004, 0.05, 0.01) == "full_exit"

    def test_reversal_never_banded(self):
        assert classify_symbol_event(-0.05, 0.05, 0.01) == "reversal"
        assert classify_symbol_event(0.05, -0.05, 0.01) == "reversal"

    def test_no_target(self):
        assert classify_symbol_event(0.0, 0.0, 0.01) == "no_target"

    def test_band_evaluation_partition(self):
        tradable, banded, max_dev = evaluate_symbol_band(
            {"A": 0.06, "B": 0.055, "C": 0.0, "D": -0.07},
            {"A": 0.05, "B": 0.05, "C": 0.05, "D": 0.05},
            0.01,
        )
        # A: 0.05→0.06 == boundary → banded (boundary belongs to no-trade side).
        # B: 0.05→0.055 < 1pp → banded. C: exit → trades. D: reversal → trades.
        assert set(tradable) == {"C", "D"}
        assert set(banded) == {"A", "B"}
        assert max_dev == pytest.approx(0.12)  # D reversal |−0.07 − 0.05|

    def test_threshold_policy_decision_boundary(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.01))
        hold = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.06}, signal_timestamp=None, now=NOW
        )
        assert hold.action is DecisionAction.HOLD
        assert hold.reason is DecisionReason.NO_MATERIAL_CHANGE
        assert hold.banded_symbols == ["A"]

        trade = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.0601}, signal_timestamp=None, now=NOW
        )
        assert trade.action is DecisionAction.TRADE
        assert trade.reason is DecisionReason.WEIGHT_DRIFT

    def test_zero_threshold_always_trades_active_changes(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.0))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.0501}, signal_timestamp=None, now=NOW
        )
        assert d.action is DecisionAction.TRADE

    def test_band_does_not_block_exit(self):
        """+5% → 0 is an EXIT, never suppressed by a 1% band (Section 7)."""
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.0}, signal_timestamp=None, now=NOW
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.EXIT_SIGNAL
        assert "A" in d.tradable_symbols

    def test_band_does_not_block_entry_or_reversal(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.05))
        entry = policy.should_rebalance(
            current_weights={"A": 0.0}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW
        )
        assert entry.action is DecisionAction.TRADE
        reversal = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": -0.05}, signal_timestamp=None, now=NOW
        )
        assert reversal.action is DecisionAction.TRADE


# ── Section 5: DAILY cadence ────────────────────────────────────────────


class TestDailyPolicy:
    def test_first_decision_of_day_trades(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        d = policy.should_rebalance(current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW)
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.DAILY_SCHEDULE

    def test_second_decision_same_day_holds(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        policy.record_trade(NOW, _fake_decision(policy))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.06}, signal_timestamp=None, now=NOW + timedelta(hours=1)
        )
        assert d.action is DecisionAction.HOLD
        assert d.reason is DecisionReason.ALREADY_TRADED_PERIOD

    def test_next_day_trades_again(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        policy.record_trade(NOW, _fake_decision(policy))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.06}, signal_timestamp=None, now=NOW + timedelta(days=1)
        )
        assert d.action is DecisionAction.TRADE


# ── Section 6: WEEKLY cadence ───────────────────────────────────────────


class TestWeeklyPolicy:
    def _monday(self, hour: int = 0, minute: int = 0) -> datetime:
        # 2026-09-14 is a Monday.
        return datetime(2026, 9, 14, hour, minute, tzinfo=UTC)

    def test_trades_at_anchor(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        d = policy.should_rebalance(
            current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=self._monday(1)
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.WEEKLY_SCHEDULE

    def test_holds_before_anchor(self):
        # ISO-week semantics: the intervention window is [anchor of week N,
        # anchor of week N+1). With a Monday-12:00 anchor, Monday 09:00 of the
        # SAME ISO week is still before the anchor → hold.
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY, weekly_anchor_hour_utc=12))
        monday_morning = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.05}, signal_timestamp=None, now=monday_morning
        )
        assert d.action is DecisionAction.HOLD
        assert d.reason is DecisionReason.OUTSIDE_ANCHOR_WINDOW

    def test_sunday_late_trades_under_iso_week_semantics(self):
        # Sunday 23:00 belongs to the CURRENT ISO week (week of Mon Sep 7),
        # whose Monday-00:00 anchor has passed → the week's intervention is
        # permitted (once; the week-key guard blocks a second one).
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        sunday = datetime(2026, 9, 13, 23, 0, tzinfo=UTC)
        d = policy.should_rebalance(current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=sunday)
        assert d.action is DecisionAction.TRADE
        # And the next day (a new ISO week) permits one more intervention.
        policy.record_trade(sunday, _fake_decision(policy))
        monday_next_week = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
        d2 = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.05}, signal_timestamp=None, now=monday_next_week
        )
        assert d2.action is DecisionAction.TRADE

    def test_holds_after_trading_that_week(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        policy.record_trade(self._monday(1), _fake_decision(policy))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.07}, signal_timestamp=None, now=self._monday(5)
        )
        assert d.action is DecisionAction.HOLD
        assert d.reason is DecisionReason.ALREADY_TRADED_PERIOD

    def test_configurable_anchor(self):
        # Wednesday 14:00 anchor: Tuesday holds, Wednesday trades.
        policy = build_policy(
            PolicyConfig(policy_type=PolicyType.WEEKLY, weekly_anchor_weekday=2, weekly_anchor_hour_utc=14)
        )
        tuesday = datetime(2026, 9, 15, 10, tzinfo=UTC)
        wednesday = datetime(2026, 9, 16, 15, tzinfo=UTC)
        assert (
            policy.should_rebalance(
                current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=tuesday
            ).action
            is DecisionAction.HOLD
        )
        assert (
            policy.should_rebalance(
                current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=wednesday
            ).action
            is DecisionAction.TRADE
        )

    def test_anchor_time_same_day_respected(self):
        # Monday 00:00 anchor: Monday 23:00 (same ISO week, after anchor) trades.
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        monday_late = datetime(2026, 9, 14, 23, 0, tzinfo=UTC)
        assert (
            policy.should_rebalance(
                current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=monday_late
            ).action
            is DecisionAction.TRADE
        )

    def test_emergency_event_overrides_anchor(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        sunday = datetime(2026, 9, 13, 23, 0, tzinfo=UTC)
        d = policy.should_rebalance(
            current_weights={"A": 0.05},
            target_weights={"A": 0.02},
            signal_timestamp=None,
            now=sunday,
            events=RebalanceEvents(risk_mandated_reduction=True),
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.RISK_EVENT


# ── Section 8: HYBRID events ────────────────────────────────────────────


class TestHybridPolicy:
    def test_exit_overrides_band(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.HYBRID, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.0}, signal_timestamp=None, now=NOW
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.EXIT_SIGNAL

    def test_regime_transition_overrides_band(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.HYBRID, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05},
            target_weights={"A": 0.055},
            signal_timestamp=None,
            now=NOW,
            events=RebalanceEvents(regime_transition=True),
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.REGIME_EVENT

    def test_risk_event_overrides_band(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.HYBRID, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05},
            target_weights={"A": 0.055},
            signal_timestamp=None,
            now=NOW,
            events=RebalanceEvents(risk_mandated_reduction=True),
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.RISK_EVENT

    def test_no_event_band_holds(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.HYBRID, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.055}, signal_timestamp=None, now=NOW
        )
        assert d.action is DecisionAction.HOLD

    def test_symbol_removal_is_exit(self):
        """Target drops the symbol entirely (weight 0) → immediate exit."""
        policy = build_policy(PolicyConfig(policy_type=PolicyType.HYBRID, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05, "B": 0.04},
            target_weights={"B": 0.04},
            signal_timestamp=None,
            now=NOW,
        )
        assert d.action is DecisionAction.TRADE
        assert d.reason is DecisionReason.EXIT_SIGNAL
        assert "A" in d.tradable_symbols


# ── CANONICAL baseline ──────────────────────────────────────────────────


class TestCanonicalPolicy:
    def test_always_trades_when_target_exists(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.CANONICAL))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.050001}, signal_timestamp=None, now=NOW
        )
        assert d.action is DecisionAction.TRADE

    def test_tradable_set_is_unrestricted(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.CANONICAL))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.05, "B": 0.03}, signal_timestamp=None, now=NOW
        )
        assert set(d.tradable_symbols) == {"A", "B"}


# ── Sections 23/24: persistence, restart, idempotency ──────────────────


class TestPersistenceAndIdempotency:
    def test_same_cycle_twice_no_duplicate_trade(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        first = policy.should_rebalance(current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW)
        assert first.action is DecisionAction.TRADE
        policy.record_trade(NOW, first)
        second = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW + timedelta(hours=1)
        )
        assert second.action is DecisionAction.HOLD

    def test_restart_restores_day_anchor(self, tmp_path: Path):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        decision = policy.should_rebalance(
            current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW
        )
        policy.record_trade(NOW, decision)
        save_policy_state(tmp_path, policy.state)

        # Fresh instance (process restart).
        restarted = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        load_policy_state(tmp_path, restarted)
        d = restarted.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.06}, signal_timestamp=None, now=NOW + timedelta(hours=2)
        )
        assert d.action is DecisionAction.HOLD  # no double-trade after restart

    def test_restart_restores_week_anchor(self, tmp_path: Path):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        decision = policy.should_rebalance(
            current_weights={}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW
        )
        policy.record_trade(NOW, decision)
        save_policy_state(tmp_path, policy.state)

        restarted = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        load_policy_state(tmp_path, restarted)
        d = restarted.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.06}, signal_timestamp=None, now=NOW + timedelta(hours=2)
        )
        assert d.action is DecisionAction.HOLD
        assert d.reason is DecisionReason.ALREADY_TRADED_PERIOD

    def test_state_file_not_corrupted_by_missing_file(self, tmp_path: Path):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        load_policy_state(tmp_path, policy)  # no file → no-op
        assert policy.state.last_rebalance_day == ""

    def test_cross_policy_type_anchors_not_applied(self, tmp_path: Path):
        saved = build_policy(PolicyConfig(policy_type=PolicyType.DAILY))
        saved.state.last_rebalance_day = "2026-09-16"
        save_policy_state(tmp_path, saved.state)
        weekly = build_policy(PolicyConfig(policy_type=PolicyType.WEEKLY))
        load_policy_state(tmp_path, weekly)
        assert weekly.state.last_rebalance_day == ""  # anchors are policy-specific
        assert weekly.state.last_decision == saved.state.last_decision  # shared fields surface

    def test_same_target_repeated_is_idempotent_threshold(self):
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.01))
        # Identical target/positions repeatedly → first HOLD, and stays HOLD.
        for _ in range(3):
            d = policy.should_rebalance(
                current_weights={"A": 0.05}, target_weights={"A": 0.05}, signal_timestamp=None, now=NOW
            )
            assert d.action is DecisionAction.HOLD


# ── Target hashing + turnover ───────────────────────────────────────────


class TestHashingAndTurnover:
    def test_target_hash_stable_and_sensitive(self):
        h1 = compute_target_hash({"A": 0.05, "B": -0.03})
        h2 = compute_target_hash({"B": -0.03, "A": 0.05})
        h3 = compute_target_hash({"A": 0.06, "B": -0.03})
        assert h1 == h2  # order-independent
        assert h1 != h3  # content-sensitive

    def test_turnover_gross_traded_notional(self):
        # Σ|Δw|: a 5% increase plus a 5% reduction = 0.10 of equity traded.
        assert compute_turnover({"A": 0.10, "B": 0.0}, {"A": 0.05, "B": 0.05}) == pytest.approx(0.10)

    def test_turnover_full_rotation(self):
        assert compute_turnover({"B": 0.05}, {"A": 0.05}) == pytest.approx(0.10)  # sell A + buy B


# ── Section 29: ledger isolation ────────────────────────────────────────


class TestLedgerIsolation:
    def test_ledger_records_section29_schema(self, tmp_path: Path):
        ledger = RebalancePolicyLedger(tmp_path)
        policy = build_policy(PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=0.01))
        d = policy.should_rebalance(
            current_weights={"A": 0.05}, target_weights={"A": 0.065}, signal_timestamp=None, now=NOW
        )
        row = ledger.record(
            cycle_id="C1",
            decision=d,
            target_weights={"A": 0.06},
            current_weights={"A": 0.05},
            target_hash=compute_target_hash({"A": 0.06}),
            signal_date="2026-09-16",
            risk_state="gates_passed",
            regime="ON",
        )
        for key in (
            "timestamp",
            "signal_date",
            "cycle_id",
            "policy_id",
            "policy_version",
            "target_hash",
            "current_position_hash",
            "decision",
            "reason",
            "target_weights",
            "current_weights",
            "max_weight_deviation",
            "gross_turnover",
            "estimated_cost",
            "risk_state",
            "regime",
        ):
            assert key in row
        assert ledger.read()[0]["decision"] == "TRADE"

    def test_ledger_is_a_new_isolated_file(self, tmp_path: Path):
        ledger = RebalancePolicyLedger(tmp_path)
        assert ledger.path.name == "rebalance_policy_decisions.jsonl"
        assert ledger.path.name not in {
            "decisions.jsonl",
            "order_intents.jsonl",
            "risk_gate_audit.jsonl",
            "shadow_decisions.jsonl",
        }


# ── Sections 13/28: matrix + shadow evaluation ──────────────────────────


class TestExperimentMatrix:
    def test_matrix_matches_pre_registration(self):
        ids = [c.policy_id for c in experiment_matrix()]
        assert ids == [
            "R4-REB-CANONICAL",
            "R4-REB-DAILY",
            "R4-REB-WEEKLY",
            "R4-REB-T005",
            "R4-REB-T010",
            "R4-REB-T020",
            "R4-REB-T050",
            "R4-REB-HYBRID-T010",
        ]

    def test_evaluate_all_policies_is_stateless(self):
        decisions = evaluate_all_policies(
            target_weights={"A": 0.06},
            current_weights={"A": 0.05},
            signal_timestamp=None,
            now=NOW,
        )
        assert len(decisions) == 8
        assert all(isinstance(d, RebalanceDecision) for d in decisions)
        # CANONICAL/DAILY trade; WEEKLY trades (Monday anchor); threshold on 1pp drift trades.
        by_id = {d.policy_id: d for d in decisions}
        assert by_id["R4-REB-CANONICAL"].action is DecisionAction.TRADE
        assert by_id["R4-REB-WEEKLY"].action is DecisionAction.TRADE

    def test_policy_from_env(self):
        policy = policy_from_env({"R4_REBALANCE_POLICY": "THRESHOLD", "R4_REB_THRESHOLD": "0.02"})
        assert policy.config.policy_type is PolicyType.THRESHOLD
        assert policy.config.threshold == 0.02
        assert policy.config.policy_id == "R4-REB-T020"

    def test_policy_from_env_invalid_raises(self):
        with pytest.raises(ValueError):
            policy_from_env({"R4_REBALANCE_POLICY": "HOURLY"})

    def test_policy_from_env_defaults_canonical(self):
        policy = policy_from_env({})
        assert policy.config.policy_type is PolicyType.CANONICAL


def _fake_decision(policy) -> RebalanceDecision:
    return RebalanceDecision(
        action=DecisionAction.TRADE,
        reason=DecisionReason.DAILY_SCHEDULE,
        policy_type=policy.config.policy_type,
        policy_id=policy.config.policy_id,
        policy_version=policy.config.policy_version,
    )
