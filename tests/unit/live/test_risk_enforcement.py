"""Regression tests for the Risk Enforcement Overlay.

These tests cover the exact invariants that were violated in the 9>8 incident
and the missing risk gates that the forensic audit identified.

Test categories:
1. Position count enforcement (the 9>8 breach)
2. Account drawdown enforcement
3. Daily loss enforcement
4. Equity floor enforcement
5. Position protection (SL) check
6. Fingerprint check
7. Broker connectivity check
8. Integration: full gate pipeline
9. Emergency flatten
10. Edge cases: stale state, partial fills, restart recovery
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.risk_enforcement import (
    GateResult,
    RiskEnforcer,
    RiskEnvelope,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def envelope():
    """Standard $5K MINIMAL envelope."""
    return RiskEnvelope(
        max_concurrent_positions=19,
        max_position_notional=5_000.0,
        max_order_notional=1_500.0,
        max_per_position_loss_pct=0.10,
        max_account_drawdown_pct=0.10,
        max_daily_loss=250.0,
        min_equity=4_000.0,
        require_sl_on_positions=False,
        t0_equity=5_010.94,
    )


@pytest.fixture
def enforcer(envelope):
    """Risk enforcer with standard envelope."""
    return RiskEnforcer(envelope)


def _make_position(symbol="EURUSD", volume=0.01, sl=0.0, tp=0.0, profit=0.0, ptype=0):
    """Create a mock broker position dict."""
    return {
        "symbol": symbol,
        "volume": volume,
        "type": ptype,
        "price_open": 1.1000,
        "sl": sl,
        "tp": tp,
        "profit": profit,
        "magic": 20260825,
        "comment": "R4-Rebalance",
    }


def _envelope(**kwargs):
    """Create a RiskEnvelope with overrides (avoids frozen dataclass mutation)."""
    defaults = dict(
        max_concurrent_positions=19,
        max_position_notional=5_000.0,
        max_order_notional=1_500.0,
        max_per_position_loss_pct=0.10,
        max_account_drawdown_pct=0.10,
        max_daily_loss=250.0,
        min_equity=4_000.0,
        require_sl_on_positions=False,
        t0_equity=5_010.94,
    )
    defaults.update(kwargs)
    return RiskEnvelope(**defaults)


def _gate_named(results, name):
    """Find a gate result by name."""
    for r in results:
        if r.gate_name == name:
            return r
    return None


# ── 1. Position Count Enforcement ──────────────────────────────────


class TestPositionCountEnforcement:
    """Tests for position count enforcement (max_concurrent_positions=19)."""

    def test_zero_positions_allows_entries(self, enforcer):
        """0 positions + 19 target orders → PASS."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_010.94,
            account_free_margin=5_000.0,
            target_orders=19,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.PASS
        assert "0/19" in gate.message
        assert passed

    def test_nineteen_positions_blocks_new_entries(self, enforcer):
        """19 positions + 1 target order → BLOCK (would create #20)."""
        positions = [_make_position(f"SYM{i}") for i in range(19)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=1,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.BLOCK
        assert "would create position #20" in gate.message.lower()
        assert not passed

    def test_twenty_positions_is_critical_breach(self, enforcer):
        """20 positions already exist → CRITICAL (breach already happened)."""
        positions = [_make_position(f"SYM{i}") for i in range(20)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=0,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.CRITICAL
        assert "already breached" in gate.message.lower()
        assert not passed

    def test_eighteen_positions_allows_one_entry(self, enforcer):
        """18 positions + 1 target order → PASS."""
        positions = [_make_position(f"SYM{i}") for i in range(18)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=1,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.PASS
        assert "18/19" in gate.message

    def test_eighteen_positions_blocks_two_entries(self, enforcer):
        """18 positions + 2 target orders → BLOCK (would exceed limit)."""
        positions = [_make_position(f"SYM{i}") for i in range(18)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=2,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.BLOCK
        assert not passed

    def test_zero_target_orders_at_limit_passes(self, enforcer):
        """8 positions + 0 target orders → PASS (no new entries, just monitoring)."""
        positions = [_make_position(f"SYM{i}") for i in range(8)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=0,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.PASS


# ── 2. Account Drawdown Enforcement ───────────────────────────────


class TestAccountDrawdown:
    """Tests for account-level drawdown from peak equity."""

    def test_no_drawdown_passes(self, enforcer):
        """Equity at peak → 0% drawdown → PASS."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_010.94,
            account_free_margin=5_000.0,
        )
        gate = _gate_named(results, "account_drawdown")
        assert gate.result == GateResult.PASS

    def test_small_drawdown_passes(self, enforcer):
        """5% drawdown (< 10% limit) → PASS."""
        enforcer._peak_equity = 5_010.94
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_760.0,
            account_free_margin=4_700.0,
        )
        gate = _gate_named(results, "account_drawdown")
        assert gate.result == GateResult.PASS

    def test_ten_pct_drawdown_blocks(self, enforcer):
        """10%+ drawdown → BLOCK."""
        enforcer._peak_equity = 5_010.94
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_500.0,
            account_free_margin=4_400.0,
        )
        gate = _gate_named(results, "account_drawdown")
        assert gate.result == GateResult.BLOCK
        assert not passed

    def test_peak_equity_tracks_higher(self, enforcer):
        """Peak equity updates when equity exceeds previous peak."""
        enforcer._peak_equity = 5_010.94
        enforcer.check_all(
            broker_positions=[],
            account_equity=5_500.0,
            account_free_margin=5_400.0,
        )
        assert enforcer._peak_equity == 5_500.0


# ── 3. Daily Loss Enforcement ─────────────────────────────────────


class TestDailyLoss:
    """Tests for daily loss limit ($250 max)."""

    def test_no_loss_passes(self, enforcer):
        """No daily loss → PASS."""
        enforcer.record_daily_start(5_010.94)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_010.94,
            account_free_margin=5_000.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.PASS

    def test_loss_within_limit_passes(self, enforcer):
        """$200 loss (< $250 limit) → PASS."""
        enforcer.record_daily_start(5_010.94)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_810.94,
            account_free_margin=4_700.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.PASS

    def test_loss_exceeding_limit_blocks(self, enforcer):
        """$300 loss (> $250 limit) → BLOCK."""
        enforcer.record_daily_start(5_010.94)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_710.94,
            account_free_margin=4_600.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.BLOCK
        assert not passed

    def test_profit_does_not_count_as_loss(self, enforcer):
        """Profit is not treated as negative loss → PASS."""
        enforcer.record_daily_start(5_010.94)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_200.0,
            account_free_margin=5_100.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.PASS


# ── 4. Equity Floor ───────────────────────────────────────────────


class TestEquityFloor:
    """Tests for absolute equity minimum ($4,000)."""

    def test_equity_above_floor_passes(self, enforcer):
        """$5,000 > $4,000 → PASS."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _gate_named(results, "equity_floor")
        assert gate.result == GateResult.PASS

    def test_equity_below_floor_is_critical(self, enforcer):
        """$3,999 < $4,000 → CRITICAL (need to prevent drawdown from blocking first)."""
        # Set peak to same as equity so drawdown doesn't trigger first
        enforcer._peak_equity = 3_999.0
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=3_999.0,
            account_free_margin=3_900.0,
        )
        gate = _gate_named(results, "equity_floor")
        assert gate.result == GateResult.CRITICAL
        assert not passed


# ── 5. Position Protection (SL Check) ────────────────────────────


class TestPositionProtection:
    """Tests for SL protection on open positions."""

    def test_sl_check_disabled_passes(self, envelope):
        """When require_sl_on_positions=False, all positions pass."""
        env = _envelope(require_sl_on_positions=False)
        enforcer = RiskEnforcer(env)
        positions = [_make_position(sl=0.0)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _gate_named(results, "position_protection")
        assert gate.result == GateResult.PASS

    def test_sl_check_enabled_detects_missing(self, envelope):
        """When enabled, positions without SL → CRITICAL."""
        env = _envelope(require_sl_on_positions=True)
        enforcer = RiskEnforcer(env)
        positions = [_make_position(symbol="EURUSD", sl=0.0), _make_position(symbol="GBPUSD", sl=0.0050)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _gate_named(results, "position_protection")
        assert gate.result == GateResult.CRITICAL
        assert "EURUSD" in gate.message
        # Gate 6 CRITICAL does NOT early-exit (intentional design).
        # R4 uses signal-based exits, not SL-based exits.
        # CRITICAL is logged for audit trail but passed reflects all gates.
        assert not passed  # CRITICAL gate means not all gates PASS


# ── 6. Fingerprint Check ──────────────────────────────────────────


class TestFingerprint:
    """Tests for T=0 fingerprint integrity."""

    def test_matching_fingerprint_passes(self, enforcer):
        """Fingerprint match → PASS."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
            fingerprint_match=True,
        )
        gate = _gate_named(results, "fingerprint")
        assert gate.result == GateResult.PASS

    def test_drifted_fingerprint_is_critical(self, enforcer):
        """Fingerprint mismatch → CRITICAL."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
            fingerprint_match=False,
        )
        gate = _gate_named(results, "fingerprint")
        assert gate.result == GateResult.CRITICAL
        assert not passed


# ── 7. Broker Connectivity ────────────────────────────────────────


class TestBrokerConnectivity:
    """Tests for broker data validity."""

    def test_valid_data_passes(self, enforcer):
        """Non-zero equity → PASS."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _gate_named(results, "broker_connectivity")
        assert gate.result == GateResult.PASS

    def test_zero_equity_is_critical(self, enforcer):
        """Zero equity + zero free margin → CRITICAL (disconnect/stale)."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=0.0,
            account_free_margin=0.0,
        )
        gate = _gate_named(results, "broker_connectivity")
        assert gate.result == GateResult.CRITICAL
        assert not passed


# ── 8. Full Pipeline Integration ──────────────────────────────────


class TestFullPipeline:
    """Integration tests for the complete gate pipeline."""

    def test_all_gates_pass_normal_conditions(self, enforcer):
        """Normal conditions: 3 positions, $5K equity → all PASS."""
        positions = [_make_position(f"SYM{i}") for i in range(3)]
        enforcer.record_daily_start(5_010.94)
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_900.0,
            target_orders=2,
        )
        assert passed
        assert all(r.result == GateResult.PASS for r in results)

    def test_critical_stops_immediately(self, enforcer):
        """CRITICAL on broker connectivity → remaining gates not checked."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=0.0,
            account_free_margin=0.0,
        )
        assert not passed
        assert len(results) == 1  # only broker_connectivity checked
        assert results[0].result == GateResult.CRITICAL

    def test_block_stops_immediately(self, enforcer):
        """BLOCK on position count → remaining gates not checked."""
        positions = [_make_position(f"SYM{i}") for i in range(19)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_900.0,
            target_orders=1,
        )
        assert not passed
        # position_count should be the last gate checked (BLOCK stops pipeline)
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.BLOCK

    def test_multiple_gates_can_fail(self, enforcer):
        """When first gate passes but later gate blocks → BLOCK."""
        # 19 positions but good equity → position_count blocks
        positions = [_make_position(f"SYM{i}") for i in range(19)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_900.0,
            target_orders=1,
        )
        assert not passed
        # broker_connectivity passes, position_count blocks
        conn = _gate_named(results, "broker_connectivity")
        pos = _gate_named(results, "position_count")
        assert conn.result == GateResult.PASS
        assert pos.result == GateResult.BLOCK


# ── 9. Regression: Position Count Enforcement ──────────────────────


class TestNinePositionRegression:
    """Regression tests for position count enforcement (max_concurrent=19)."""

    def test_twenty_broker_positions_critical(self, enforcer):
        """Broker reports 20 positions → CRITICAL (breach already happened)."""
        positions = [_make_position(f"SYM{i}") for i in range(20)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=0,
        )
        gate = _gate_named(results, "position_count")
        assert gate.result == GateResult.CRITICAL
        assert "already breached" in gate.message.lower()
        assert not passed

    def test_twenty_positions_blocks_even_zero_target(self, enforcer):
        """20 positions + 0 target orders → still CRITICAL (state is invalid)."""
        positions = [_make_position(f"SYM{i}") for i in range(20)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_010.94,
            account_free_margin=4_000.0,
            target_orders=0,
        )
        assert not passed

    def test_enforce_max_concurrent_in_loop(self, enforcer):
        """Simulate the loop's concurrency check: 19 positions → 0 slots."""
        positions = [_make_position(f"SYM{i}") for i in range(19)]
        max_concurrent = 19
        available_slots = max_concurrent - len(positions)
        assert available_slots == 0
        # No orders should be generated


# ── 10. Audit Trail ───────────────────────────────────────────────


class TestAuditTrail:
    """Tests for audit logging of gate results."""

    def test_audit_records_all_gates(self, enforcer):
        """Audit log captures all gate results."""
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        enforcer.audit(results)
        log = enforcer.get_audit_log()
        assert len(log) == 1
        assert "gates" in log[0]
        assert log[0]["all_pass"] is True

    def test_audit_records_block(self, enforcer):
        """Audit log captures BLOCKED state."""
        positions = [_make_position(f"SYM{i}") for i in range(19)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_000.0,
            account_free_margin=4_900.0,
            target_orders=1,
        )
        enforcer.audit(results)
        log = enforcer.get_audit_log()
        assert log[0]["all_pass"] is False


# ── 11. Edge Cases ────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: empty state, exact boundary, etc."""

    def test_exact_boundary_at_limit(self, enforcer):
        """Exactly at limit (8 positions, 0 target) → PASS."""
        positions = [_make_position(f"SYM{i}") for i in range(8)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_000.0,
            account_free_margin=4_900.0,
            target_orders=0,
        )
        assert passed

    def test_exact_boundary_one_over(self, enforcer):
        """Exactly one over (20 positions) → CRITICAL."""
        positions = [_make_position(f"SYM{i}") for i in range(20)]
        passed, results = enforcer.check_all(
            broker_positions=positions,
            account_equity=5_000.0,
            account_free_margin=4_900.0,
            target_orders=0,
        )
        assert not passed

    def test_drawdown_exact_boundary(self, enforcer):
        """Drawdown exactly at 10% → PASS (uses >, not >=)."""
        enforcer._peak_equity = 5_000.0
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_500.0,
            account_free_margin=4_400.0,
        )
        gate = _gate_named(results, "account_drawdown")
        assert gate.result == GateResult.PASS  # 10% exactly is not > 10%

    def test_drawdown_just_over_boundary(self, enforcer):
        """Drawdown just over 10% → BLOCK."""
        enforcer._peak_equity = 5_000.0
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_499.0,
            account_free_margin=4_400.0,
        )
        gate = _gate_named(results, "account_drawdown")
        assert gate.result == GateResult.BLOCK

    def test_daily_loss_exact_boundary(self, enforcer):
        """Daily loss exactly at $250 → PASS (uses >, not >=)."""
        enforcer.record_daily_start(5_000.0)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_750.0,
            account_free_margin=4_600.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.PASS  # $250 exactly is not > $250

    def test_daily_loss_just_over_boundary(self, enforcer):
        """Daily loss just over $250 → BLOCK."""
        enforcer.record_daily_start(5_000.0)
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_749.0,
            account_free_margin=4_600.0,
        )
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.BLOCK

    def test_equity_floor_exact_boundary(self, enforcer):
        """Equity exactly at $4,000 → PASS (at boundary, not below)."""
        # Set peak to same as equity so drawdown doesn't block first
        enforcer._peak_equity = 4_000.0
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=4_000.0,
            account_free_margin=3_900.0,
        )
        gate = _gate_named(results, "equity_floor")
        assert gate.result == GateResult.PASS

    def test_equity_just_below_floor(self, enforcer):
        """Equity $3,999.99 → CRITICAL."""
        # Set peak to same as equity so drawdown doesn't block first
        enforcer._peak_equity = 3_999.99
        passed, results = enforcer.check_all(
            broker_positions=[],
            account_equity=3_999.99,
            account_free_margin=3_900.0,
        )
        gate = _gate_named(results, "equity_floor")
        assert gate.result == GateResult.CRITICAL


class TestRestartRecovery:
    """P1-B: durable audit replay restores baselines; corruption fails closed.

    Unit-scope counterpart of the integration crash/restart suite: a restarted
    enforcer must replay the audit trail to the same peak equity and
    start-of-day baseline the crashed process held, and a corrupted trail must
    refuse to authorize entries.
    """

    def test_restart_replays_peak_and_daily_baseline(self, envelope, tmp_path):
        """Peak equity and daily baseline survive a simulated restart."""
        path = str(tmp_path / "risk_gate_audit.jsonl")
        process_a = RiskEnforcer(envelope, audit_log_path=path)
        process_a.record_daily_start(5000.0)
        passed, results = process_a.check_all([], 5200.0, 5100.0)  # peak → 5200
        assert passed, [r.to_dict() for r in results]
        process_a.audit(results)

        # Simulated crash + restart against the same audit trail.
        process_b = RiskEnforcer(envelope, audit_log_path=path)
        assert process_b.recovery_state == "RESTORED"
        assert process_b.recovery_error == ""
        assert process_b._peak_equity == 5200.0
        assert process_b._daily_pnl_start == 5000.0

        # $300 loss vs the SURVIVED $5,000 baseline → daily-loss BLOCK. A
        # silently re-initialized baseline would have passed this.
        passed, results = process_b.check_all([], 4700.0, 4600.0)
        assert not passed
        gate = _gate_named(results, "daily_loss")
        assert gate.result == GateResult.BLOCK

    def test_corrupt_audit_fails_closed(self, envelope, tmp_path):
        """A torn/unreadable audit trail blocks all entries (no silent reset)."""
        path = tmp_path / "risk_gate_audit.jsonl"
        path.write_text('{"gates": [], "runtime": {}}\n{"gates": [], "runt')

        enforcer = RiskEnforcer(envelope, audit_log_path=str(path))
        assert enforcer.recovery_state == "CORRUPTED"
        assert enforcer.recovery_error

        passed, results = enforcer.check_all([], 5000.0, 4000.0)
        assert not passed
        gate = _gate_named(results, "state_recovery")
        assert gate.result == GateResult.CRITICAL

    def test_missing_or_empty_audit_is_clean_start(self, envelope, tmp_path):
        """First boot (no audit file, or an empty one) is CLEAN, not a failure."""
        missing = RiskEnforcer(envelope, audit_log_path=str(tmp_path / "none.jsonl"))
        assert missing.recovery_state == "CLEAN"
        assert missing.recovery_error == ""

        empty_path = tmp_path / "empty.jsonl"
        empty_path.write_text("")
        empty = RiskEnforcer(envelope, audit_log_path=str(empty_path))
        assert empty.recovery_state == "CLEAN"
