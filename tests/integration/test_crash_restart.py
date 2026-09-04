"""Crash/restart integration tests (P1-B) — prove the risk layer survives a process restart.

Simulates the R4 loop's failure modes at the enforcement boundary:

    process A:  cycles run, gates pass, audit persisted
        ↓ CRASH (no cleanup, no in-memory handoff)
    process B:  reconnects, replays the durable audit trail, reconciles,
                continues gating with the SAME baselines

Invariants verified:
  - Daily-loss baseline survives restart (a loss accrued pre-crash still counts)
  - Peak-equity survives restart (drawdown measured from the true peak)
  - Broker-authoritative position capacity is not double-counted after restart
  - Existing audit JSONL stays readable; new records append; no duplicates
  - Corrupted audit state → restart → FAIL CLOSED (no entries authorized)
  - First boot with no audit file is a clean start (not a failure)
"""

import json

from eigencapital.core.models.order import Order
from eigencapital.execution.broker import PaperBroker
from eigencapital.live.risk_enforcement import (
    BlockReason,
    GateResult,
    RiskEnforcer,
    RiskEnvelope,
)

# Shared envelope: retail-size limits matching the canonical live profile.
_ENVELOPE = RiskEnvelope(
    max_concurrent_positions=3,
    max_position_notional=5000.0,
    max_order_notional=1500.0,
    max_daily_loss=250.0,
    min_equity=4000.0,
    max_account_drawdown_pct=0.10,
    require_sl_on_positions=False,  # R4 uses signal-based exits
    t0_equity=5000.0,
)


def _broker_position(symbol: str, volume: float = 0.1, ptype: int = 0) -> dict:
    """A broker-confirmed MT5-style position row (source of truth)."""
    return {
        "symbol": symbol,
        "volume": volume,
        "type": ptype,
        "price_open": 1.1000,
        "sl": 0.0,
        "tp": 0.0,
        "profit": 0.0,
        "magic": 20260825,
        "comment": "R4-Rebalance",
    }


def _read_audit(path) -> list:
    """Read and parse every line of an audit JSONL file."""
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestRestartPreservesRiskBaselines:
    """The daily-loss baseline and peak equity must survive a crash."""

    def test_daily_loss_baseline_and_peak_survive_restart(self, tmp_path):
        path = tmp_path / "risk_gate_audit.jsonl"

        # ── Process A: healthy cycles, peak drifts up to $5,200 ──────────
        enforcer_a = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        enforcer_a.record_daily_start(5000.0)

        passed, results = enforcer_a.check_all([], 5200.0, 5100.0)
        assert passed, [r.to_dict() for r in results]
        enforcer_a.audit(results)

        passed, results = enforcer_a.check_all([], 5100.0, 5000.0)
        assert passed, [r.to_dict() for r in results]
        enforcer_a.audit(results)
        assert enforcer_a._peak_equity == 5200.0

        # ── CRASH: process A is dropped with no cleanup ──────────────────

        # ── Process B: restarts against the same audit trail ─────────────
        enforcer_b = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        assert enforcer_b.recovery_state == "RESTORED"
        assert enforcer_b.recovery_error == ""
        assert enforcer_b._peak_equity == 5200.0  # peak survives
        assert enforcer_b._daily_pnl_start == 5000.0  # baseline survives
        assert enforcer_b._daily_start_initialized is True

        # $150 loss since baseline — still within the $250 budget.
        passed, results = enforcer_b.check_all([], 4850.0, 4750.0)
        assert passed, [r.to_dict() for r in results]
        enforcer_b.audit(results)

        # $300 loss since the SURVIVED $5,000 baseline → daily-loss BLOCK.
        # If the baseline had been silently re-initialized to the current
        # equity (the pre-B5 behavior), this would have passed.
        passed, results = enforcer_b.check_all([], 4700.0, 4600.0)
        assert not passed
        gate = next(r for r in results if r.gate_name == "daily_loss")
        assert gate.result == GateResult.BLOCK
        assert gate.block_reason == BlockReason.DAILY_LOSS

        # Contrast: an enforcer with no persisted trail auto-initializes to
        # the first observed equity and would NOT flag this loss.
        naive = RiskEnforcer(_ENVELOPE)
        passed_naive, _ = naive.check_all([], 4700.0, 4600.0)
        assert passed_naive, "without recovery the same state must auto-init and pass"

        # Audit trail: readable, appended, every record carries runtime state.
        records = _read_audit(path)
        assert len(records) == 3
        assert all("runtime" in r for r in records)
        assert records[-1]["runtime"]["peak_equity"] == 5200.0
        assert records[-1]["runtime"]["daily_pnl_start"] == 5000.0


class TestRestartAfterFilledOrders:
    """Restart after orders filled must not double-count positions or authorization."""

    def test_capacity_accounting_is_broker_authoritative_across_restart(self, tmp_path):
        path = tmp_path / "risk_gate_audit.jsonl"

        # ── Process A: one order submitted and filled on the paper broker ─
        broker = PaperBroker()
        order = Order(
            order_id="ORD-EURUSD-1",
            instrument_id="EURUSD",
            timestamp_utc="2025-01-15T10:00:00Z",
            order_type="MARKET",
            side="BUY",
            quantity=0.1,
            strategy_id="r4",
        )
        broker.submit_order(order)
        broker.generate_fill(order.order_id, fill_price=1.1000)
        assert broker.get_positions() == {"EURUSD": 0.1}

        enforcer_a = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        enforcer_a.record_daily_start(5000.0)
        broker_positions = [_broker_position("EURUSD", volume=0.1)]
        passed, results = enforcer_a.check_all(broker_positions, 5000.0, 4000.0, target_orders=0)
        assert passed, [r.to_dict() for r in results]
        enforcer_a.audit(results)

        # ── CRASH ────────────────────────────────────────────────────────

        # ── Process B: reconnects; broker state is re-read (authoritative) ─
        enforcer_b = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        assert enforcer_b.recovery_state == "RESTORED"

        # Same single position + 1 more entry → 2/3 slots, still allowed.
        passed, results = enforcer_b.check_all(broker_positions, 5000.0, 3900.0, target_orders=1)
        assert passed, [r.to_dict() for r in results]
        pos_gate = next(r for r in results if r.gate_name == "position_count")
        assert pos_gate.details["current"] == 1  # no phantom pre-crash state
        enforcer_b.audit(results)

        # Capacity math stays correct: 2 existing + 2 requested → 4 > 3 BLOCK.
        crowded = [
            _broker_position("EURUSD", volume=0.1),
            _broker_position("GBPUSD", volume=0.1),
        ]
        passed, results = enforcer_b.check_all(crowded, 5000.0, 3900.0, target_orders=2)
        assert not passed
        gate = next(r for r in results if r.gate_name == "position_count")
        assert gate.result == GateResult.BLOCK

        # No duplicate authorization events: exactly one audit line per audit().
        records = _read_audit(path)
        assert len(records) == 2
        timestamps = [r["timestamp"] for r in records]
        assert len(set(timestamps)) == len(timestamps)


class TestCorruptedAuditFailsClosed:
    """A torn/corrupted audit trail must fail closed on restart."""

    def test_corrupted_audit_blocks_all_entries(self, tmp_path):
        path = tmp_path / "risk_gate_audit.jsonl"
        # One valid record, then a torn write (crash mid-append), then another.
        with open(path, "w") as f:
            f.write('{"timestamp": "2025-01-15T10:00:00Z", "gates": [], "runtime": {}}\n')
            f.write('{"timestamp": "2025-01-15T10:00:01Z", "gates": [], "runt')
            f.write('{"timestamp": "2025-01-15T10:00:02Z", "gates": [], "runtime": {}}\n')

        enforcer = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        assert enforcer.recovery_state == "CORRUPTED"
        assert enforcer.recovery_error

        # Fail closed: even a healthy-looking cycle is refused.
        passed, results = enforcer.check_all([], 5000.0, 4000.0)
        assert not passed
        gate = next(r for r in results if r.gate_name == "state_recovery")
        assert gate.result == GateResult.CRITICAL
        assert gate.block_reason == BlockReason.EMERGENCY

    def test_unreadable_audit_blocks_all_entries(self, tmp_path):
        path = tmp_path / "risk_gate_audit.jsonl"
        path.write_text("not json at all\n")

        enforcer = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        assert enforcer.recovery_state == "CORRUPTED"
        passed, results = enforcer.check_all([], 5000.0, 4000.0)
        assert not passed
        assert any(r.gate_name == "state_recovery" for r in results)


class TestFirstBootCleanStart:
    """No audit file (or an empty one) is a normal first boot, not a failure."""

    def test_missing_audit_file_is_clean(self, tmp_path):
        enforcer = RiskEnforcer(_ENVELOPE, audit_log_path=str(tmp_path / "does_not_exist.jsonl"))
        assert enforcer.recovery_state == "CLEAN"
        passed, results = enforcer.check_all([], 5000.0, 4000.0)
        assert passed, [r.to_dict() for r in results]

    def test_empty_audit_file_is_clean(self, tmp_path):
        path = tmp_path / "risk_gate_audit.jsonl"
        path.write_text("")
        enforcer = RiskEnforcer(_ENVELOPE, audit_log_path=str(path))
        assert enforcer.recovery_state == "CLEAN"
        passed, results = enforcer.check_all([], 5000.0, 4000.0)
        assert passed, [r.to_dict() for r in results]
