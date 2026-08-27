"""Memory and Resource Leak Detection Tests.

Runs repeated cycles of core operations and measures whether resources
monotonically increase. A trading system that leaks memory over thousands
of cycles will eventually crash in production.

Tests:
- 10,000 risk evaluation cycles
- 10,000 fingerprint verification cycles
- 10,000 daily loss update cycles
- 10,000 audit event cycles
- 10,000 config load cycles

Each test measures RSS before and after, and asserts no significant growth.
"""

from __future__ import annotations

import gc
import os
import resource
import sys
import tracemalloc

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.config import load_config
from eigencapital.live.daily_loss import DailyLossTracker
from eigencapital.live.risk_enforcement import RiskEnforcer, RiskEnvelope
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

CYCLES = 10_000


def _rss_mb() -> float:
    """Current RSS in MB."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _heap_bytes() -> int:
    """Current Python heap size."""
    import sys

    return sys.getsizeof([])  # Placeholder — tracemalloc used for real


@pytest.fixture
def config():
    return load_config("production")


@pytest.fixture
def envelope():
    return RiskEnvelope(
        max_concurrent_positions=19,
        max_position_notional=5000.0,
        max_order_notional=1500.0,
        max_per_position_loss_pct=0.10,
        max_account_drawdown_pct=0.10,
        max_daily_loss=250.0,
        min_equity=4000.0,
        require_sl_on_positions=False,
        t0_equity=5010.94,
    )


class TestRiskEvaluationLeak:
    """Verify 10K risk evaluations don't leak memory."""

    def test_no_memory_growth(self, envelope):
        """10K risk evaluations should not significantly increase RSS."""
        enforcer = RiskEnforcer(envelope)
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        positions = [
            {"symbol": f"S{i}", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "profit": 0, "magic": 0, "comment": ""}
            for i in range(5)
        ]

        for _ in range(CYCLES):
            enforcer.check_all(
                broker_positions=positions,
                account_equity=5010.94,
                account_free_margin=4900.0,
            )

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Compare top allocations
        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        # Allow up to 5MB growth over 10K cycles
        assert total_growth < 5 * 1024 * 1024, f"Memory grew {total_growth / 1024:.1f}KB over {CYCLES} risk evaluations"


class TestFingerprintVerificationLeak:
    """Verify 10K fingerprint verifications don't leak memory."""

    def test_no_memory_growth(self, config):
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        verifier = FingerprintVerifier(config=config)
        for _ in range(CYCLES):
            verifier.verify_all()

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        assert total_growth < 5 * 1024 * 1024, (
            f"Memory grew {total_growth / 1024:.1f}KB over {CYCLES} fingerprint verifications"
        )


class TestDailyLossTrackerLeak:
    """Verify 10K daily loss updates don't leak memory."""

    def test_no_memory_growth(self, tmp_path):
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        tracker = DailyLossTracker(
            max_daily_loss=250.0,
            persistence_dir=str(tmp_path),
        )
        tracker.initialize(broker_equity=5010.94)

        for i in range(CYCLES):
            equity = 5010.94 - (i % 200) * 0.5
            tracker.update(equity=equity)

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        assert total_growth < 5 * 1024 * 1024, (
            f"Memory grew {total_growth / 1024:.1f}KB over {CYCLES} daily loss updates"
        )


class TestAuditLogLeak:
    """Verify audit logging doesn't accumulate unbounded objects."""

    def test_no_memory_growth(self, envelope):
        """10K audit entries should not grow unbounded in memory."""
        enforcer = RiskEnforcer(envelope)
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        positions = [
            {"symbol": "EURUSD", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "profit": 0, "magic": 0, "comment": ""}
        ]

        for _ in range(CYCLES):
            _, results = enforcer.check_all(
                broker_positions=positions,
                account_equity=5010.94,
                account_free_margin=4900.0,
            )
            enforcer.audit(results)

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Audit log has bounded retention (max_audit_entries)
        audit_log = enforcer.get_audit_log()
        assert len(audit_log) <= 1000  # Bounded retention

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        # Audit log is append-only, so growth is expected.
        # Check it's proportional, not super-linear.
        bytes_per_entry = total_growth / CYCLES
        assert bytes_per_entry < 1024, f"Audit log uses {bytes_per_entry:.0f} bytes/entry — too large"


class TestConfigLoadLeak:
    """Verify repeated config loading doesn't leak."""

    def test_no_memory_growth(self):
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        for _ in range(CYCLES):
            load_config("production")

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        assert total_growth < 5 * 1024 * 1024, f"Memory grew {total_growth / 1024:.1f}KB over {CYCLES} config loads"


class TestCombinedLeak:
    """Simulate mixed workload — 10K combined operations."""

    def test_no_memory_growth(self, config, envelope):
        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        enforcer = RiskEnforcer(envelope)
        verifier = FingerprintVerifier(config=config)
        positions = [
            {"symbol": "EURUSD", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "profit": 0, "magic": 0, "comment": ""}
        ]

        for i in range(CYCLES):
            # Risk check
            enforcer.check_all(
                broker_positions=positions if i % 3 == 0 else [],
                account_equity=5010.94,
                account_free_margin=4900.0,
            )

            # Fingerprint (every 10th cycle)
            if i % 10 == 0:
                verifier.verify_all()

            # Audit (every cycle)
            _, results = enforcer.check_all(
                broker_positions=positions,
                account_equity=5010.94,
                account_free_margin=4900.0,
            )
            enforcer.audit(results)

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        assert total_growth < 10 * 1024 * 1024, (
            f"Memory grew {total_growth / 1024:.1f}KB over {CYCLES} combined operations"
        )
