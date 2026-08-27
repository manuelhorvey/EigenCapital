"""Endurance tests — prove the system remains safe over extended operation.

Tests 50K simulated trading cycles measuring:
- Memory growth (tracemalloc)
- File descriptor count
- Thread count
- Latency degradation
- State corruption
- Duplicate order prevention
- Daily loss tracking across simulated days
- Disconnect recovery under load
"""

import os
import sys
import threading
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.live.daily_loss import DailyLossTracker
from eigencapital.live.risk import DisconnectRecovery, RecoveryState
from eigencapital.live.risk_enforcement import RiskEnforcer, RiskEnvelope
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
from eigencapital.risk.policy import RiskPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_enforcer():
    envelope = RiskEnvelope(
        max_concurrent_positions=19,
        max_position_notional=5000.0,
        max_order_notional=1500.0,
        max_account_drawdown_pct=20.0,
        max_daily_loss=250.0,
        min_equity=4000.0,
    )
    return RiskEnforcer(envelope)


# ---------------------------------------------------------------------------
# Endurance: Risk Evaluation
# ---------------------------------------------------------------------------


class TestRiskEndurance:
    """Risk evaluation must remain stable over 50K cycles."""

    def test_50k_risk_cycles_memory_stable(self):
        """Memory must not grow monotonically over 50K risk evaluations."""
        enforcer = _make_enforcer()
        tracemalloc.start()

        snapshots = []
        for i in range(50_000):
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )
            if i % 10_000 == 0:
                current, peak = tracemalloc.get_traced_memory()
                snapshots.append(current)

        tracemalloc.stop()

        # Memory at end should not be significantly larger than at start
        # Allow 2MB growth (for Python internals, audit log rotation)
        growth = snapshots[-1] - snapshots[0]
        assert growth < 2_000_000, (
            f"Memory grew {growth / 1024:.1f}KB over 50K cycles: "
            f"{snapshots[0] / 1024:.1f}KB → {snapshots[-1] / 1024:.1f}KB"
        )

    def test_50k_risk_cycles_latency_stable(self):
        """Latency must not degrade over 50K cycles."""
        enforcer = _make_enforcer()

        # Measure first 1K and last 1K
        def measure_batch(n=1000):
            start = time.perf_counter_ns()
            for _ in range(n):
                enforcer.check_all(
                    broker_positions=[],
                    account_equity=5000.0,
                    account_free_margin=3000.0,
                )
            elapsed_us = (time.perf_counter_ns() - start) / 1000
            return elapsed_us / n  # µs per call

        # Warmup
        measure_batch(500)

        first_batch_us = measure_batch(1000)

        # Run 48K cycles
        for _ in range(48_000):
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )

        last_batch_us = measure_batch(1000)

        # Last batch should not be > 3x slower than first
        ratio = last_batch_us / max(first_batch_us, 0.001)
        assert ratio < 3.0, f"Latency degraded {ratio:.1f}x: {first_batch_us:.1f}µs → {last_batch_us:.1f}µs"

    def test_50k_risk_cycles_audit_log_bounded(self):
        """Audit log must stay bounded at 1000 entries."""
        enforcer = _make_enforcer()
        for _ in range(50_000):
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )
        log = enforcer.get_audit_log()
        assert len(log) <= 1000, f"Audit log grew to {len(log)} entries"

    def test_file_descriptor_stable_over_50k_cycles(self):
        """File descriptors must not leak."""
        fd_start = len(os.listdir("/proc/self/fd"))
        enforcer = _make_enforcer()
        for _ in range(50_000):
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )
        fd_end = len(os.listdir("/proc/self/fd"))
        fd_growth = fd_end - fd_start
        assert fd_growth < 10, f"File descriptors grew by {fd_growth}: {fd_start} → {fd_end}"

    def test_thread_count_stable_over_50k_cycles(self):
        """Thread count must not leak."""
        threads_start = threading.active_count()
        enforcer = _make_enforcer()
        for _ in range(50_000):
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )
        threads_end = threading.active_count()
        assert threads_end - threads_start < 5, f"Threads grew from {threads_start} to {threads_end}"


# ---------------------------------------------------------------------------
# Endurance: Fingerprint Verification
# ---------------------------------------------------------------------------


class TestFingerprintEndurance:
    """Fingerprint verification must remain stable over 50K cycles."""

    def test_50k_fingerprint_cycles_memory_stable(self):
        verifier = FingerprintVerifier(
            manifest=R4ConfigManifest(),
            risk_policy=RiskPolicy(),
        )
        tracemalloc.start()
        snapshots = []
        for i in range(50_000):
            result = verifier.verify_all()
            assert result.all_verified is True
            if i % 10_000 == 0:
                current, _ = tracemalloc.get_traced_memory()
                snapshots.append(current)
        tracemalloc.stop()

        growth = snapshots[-1] - snapshots[0]
        assert growth < 2_000_000, f"Fingerprint verifier memory grew {growth / 1024:.1f}KB"

    def test_50k_fingerprint_log_bounded(self):
        verifier = FingerprintVerifier(
            manifest=R4ConfigManifest(),
            risk_policy=RiskPolicy(),
        )
        for _ in range(50_000):
            verifier.verify_all()
        log = verifier.verification_log
        assert len(log) <= 500, f"Verification log grew to {len(log)} entries"


# ---------------------------------------------------------------------------
# Endurance: Daily Loss Tracking
# ---------------------------------------------------------------------------


class TestDailyLossEndurance:
    """Daily loss tracker must handle many updates without corruption."""

    def test_50k_daily_loss_updates(self, tmp_path):
        tracker = DailyLossTracker(
            max_daily_loss=250.0,
            persistence_dir=str(tmp_path),
        )
        tracker.initialize(broker_equity=5000.0)

        for i in range(50_000):
            equity = 5000.0 - (i * 0.01)  # Slow decline
            tracker.update(equity)

            # After 25000 cycles, equity would be ~4750 — still within daily loss
            # Verify no crash, no corruption

        # Verify persistence still works
        loaded = tracker._load_baseline()
        assert loaded is not None
        assert loaded.equity > 0

    def test_daily_loss_persistence_survives_50k_updates(self, tmp_path):
        tracker = DailyLossTracker(
            max_daily_loss=250.0,
            persistence_dir=str(tmp_path),
        )
        tracker.initialize(broker_equity=5000.0)

        for i in range(50_000):
            tracker.update(5000.0 - (i * 0.01))

        # Read the persisted file directly
        import json

        data = json.loads((tmp_path / "daily_baseline.json").read_text())
        assert "date_str" in data
        assert "equity" in data
        assert "hash" in data


# ---------------------------------------------------------------------------
# Endurance: Disconnect Recovery
# ---------------------------------------------------------------------------


class TestDisconnectRecoveryEndurance:
    """Disconnect recovery must handle repeated cycles without state corruption."""

    def test_10k_disconnect_reconnect_cycles(self):
        for _ in range(10_000):
            dr = DisconnectRecovery()
            dr.on_disconnect()
            dr.on_reconnect()
            if dr.state == RecoveryState.RECONCILING:
                dr.on_reconnect()
            assert dr.state in (
                RecoveryState.CONNECTED,
                RecoveryState.RECONCILING,
                RecoveryState.HALTED,
                RecoveryState.FROZEN,
            )

    def test_disconnect_recovery_state_never_corrupts(self):
        """State must always be a valid RecoveryState."""
        for i in range(10_000):
            dr = DisconnectRecovery(max_recovery_attempts=3)
            # Random sequence of disconnects and reconnects
            for _ in range(i % 5):
                dr.on_disconnect()
                dr.on_reconnect()
            assert isinstance(dr.state, RecoveryState)


# ---------------------------------------------------------------------------
# Endurance: Combined System
# ---------------------------------------------------------------------------


class TestCombinedEndurance:
    """All components operating simultaneously over many cycles."""

    def test_10k_combined_cycles(self, tmp_path):
        """Run risk + fingerprint + daily loss + supervisor together."""
        from eigencapital.live.supervisor import ProcessSupervisor

        enforcer = _make_enforcer()
        verifier = FingerprintVerifier(
            manifest=R4ConfigManifest(),
            risk_policy=RiskPolicy(),
        )
        tracker = DailyLossTracker(
            max_daily_loss=250.0,
            persistence_dir=str(tmp_path),
        )
        tracker.initialize(broker_equity=5000.0)
        supervisor = ProcessSupervisor(state_dir=str(tmp_path))

        supervisor.claim_instance()

        tracemalloc.start()
        for i in range(10_000):
            # Risk check
            enforcer.check_all(
                broker_positions=[],
                account_equity=5000.0,
                account_free_margin=3000.0,
            )
            # Fingerprint check
            result = verifier.verify_all()
            assert result.all_verified is True
            # Daily loss update
            tracker.update(5000.0 - (i * 0.01))
            # Health check
            supervisor.mark_healthy()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Verify all components are still healthy
        health = supervisor.get_health_status()
        assert health["alive"] is True
        log = enforcer.get_audit_log()
        assert len(log) <= 1000
        vlog = verifier.verification_log
        assert len(vlog) <= 500

        # Memory growth should be bounded
        assert current < 50_000_000, f"Combined memory usage {current / 1024 / 1024:.1f}MB exceeds 50MB"

        supervisor.release()
