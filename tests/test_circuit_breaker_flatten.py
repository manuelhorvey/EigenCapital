"""Tests for the circuit breaker flatten behaviour.

Covers:
    - EngineOrchestrator.flatten_positions() closes all open positions
    - drawdown circuit breaker triggers flatten before setting halt
    - flatten is resilient to individual actor failures
    - synthetic correlated-AUD-cascade scenario triggers at 15% drawdown
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from paper_trading.governance.drawdown_controls import (
    check_drawdown_circuit_breaker,
    compute_drawdown,
    compute_exposure_multiplier,
)
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator

# ── Mock helpers ────────────────────────────────────────────────────────────────


class _MockPosition:
    def __init__(self, side: str = "long", entry_price: float = 100.0):
        self.side = side
        self.entry_price = entry_price


class _MockPosMgr:
    def __init__(self, has_pos: bool = False):
        self._has_pos = has_pos
        self.position = _MockPosition() if has_pos else None
        self.exposure_multiplier = 1.0

    def has_position(self) -> bool:
        return self._has_pos


class _MockAssetEngine:
    """Minimal mock simulating what EngineOrchestrator accesses on AssetEngine."""

    def __init__(self, name: str, current_price: float = 100.0, has_position: bool = False, mtm_value: float = 1000.0):
        self.name = name
        self.current_price = current_price
        self.current_value = mtm_value
        self.mtm_value = mtm_value
        self.pos_mgr = _MockPosMgr(has_position)
        self.reentry_positions: list[dict] = []
        self.closed_positions: list[dict] = []
        self.last_refresh = None
        self.last_pnl = None
        self.last_signal = None

    def _close_position(self, exit_price: float, exit_date: str, reason: str, trade_id: str | None = None):
        self.closed_positions.append(
            {
                "exit_price": exit_price,
                "exit_date": exit_date,
                "reason": reason,
            }
        )
        self.pos_mgr = _MockPosMgr(has_pos=False)

    def _close_all_positions(self, exit_price: float, exit_date: str, reason: str):
        return self._close_position(exit_price, exit_date, reason)

    def refresh_price(self):
        self.last_refresh = datetime.now(timezone.utc)

    def update_pnl(self):
        self.last_pnl = datetime.now(timezone.utc)

    def generate_signal(self):
        self.last_signal = {"asset": self.name, "signal": "BUY", "confidence": 0.75}
        return self.last_signal

    def update_validity(self):
        return {"state": "GREEN", "exposure": 1.0}


def _make_orchestrator(engines: dict[str, _MockAssetEngine]) -> EngineOrchestrator:
    actors = {name: AssetActor(name, eng) for name, eng in engines.items()}
    return EngineOrchestrator(actors)


# ── Tests: drawdown_controls (pure functions) ────────────────────────────────
# These complement the existing test_governance_drawdown.py with edge cases.


class TestComputeDrawdown:
    def test_small_drawdown(self):
        assert compute_drawdown(99.0, 100.0) == -0.01

    def test_large_drawdown(self):
        assert compute_drawdown(50.0, 100.0) == -0.50

    def test_zero_value_handling(self):
        assert compute_drawdown(0.0, 100.0) == -1.0

    def test_negative_current_value(self):
        dd = compute_drawdown(-50.0, 100.0)
        assert dd < 0.0

    def test_both_zero_returns_zero(self):
        assert compute_drawdown(0.0, 0.0) == 0.0


class TestComputeExposureMultiplier:
    def test_exactly_at_hard_limit_defaults(self):
        mult, halted = compute_exposure_multiplier(-0.15)
        assert mult == 0.0
        assert halted

    def test_custom_limits(self):
        mult, halted = compute_exposure_multiplier(-0.12, drawdown_limit=-0.10, soft_limit=-0.05)
        assert mult == 0.0
        assert halted

    def test_partial_at_custom_limits(self):
        mult, halted = compute_exposure_multiplier(-0.075, drawdown_limit=-0.10, soft_limit=-0.05)
        assert mult == pytest.approx(0.5)
        assert not halted

    def test_soft_limit_equals_hard_limit(self):
        # When soft == hard, the >= soft_limit check fires first: drawdown at
        # limit gets full exposure (1.0). Drawdown below limit => halted (0.0).
        mult, halted = compute_exposure_multiplier(-0.10, drawdown_limit=-0.10, soft_limit=-0.10)
        assert mult == 1.0
        assert not halted


class TestCheckDrawdownCircuitBreaker:
    def test_peak_value_has_not_been_set(self):
        result = check_drawdown_circuit_breaker(100.0, 0.0)
        assert result["drawdown"] == 0.0
        assert not result["halted"]

    def test_drawdown_of_exactly_one_percent(self):
        result = check_drawdown_circuit_breaker(99.0, 100.0)
        assert result["drawdown"] == -0.01
        assert not result["halted"]

    def test_drawdown_of_negative_ten_percent_should_not_halt(self):
        result = check_drawdown_circuit_breaker(90.0, 100.0)
        assert result["drawdown"] == -0.10
        assert result["exposure_multiplier"] == 1.0
        assert not result["halted"]

    def test_drawdown_of_negative_twenty_percent_should_halt(self):
        result = check_drawdown_circuit_breaker(80.0, 100.0)
        assert result["drawdown"] == -0.20
        assert result["halted"]
        assert result["breached"]


# ── Tests: EngineOrchestrator flatten_positions() ────────────────────────────


class TestFlattenPositions:
    def test_flatten_closes_all_open_positions(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", current_price=0.65, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", current_price=1.08, has_position=True),
            "GBPUSD": _MockAssetEngine("GBPUSD", current_price=1.25, has_position=False),
        }
        orch = _make_orchestrator(engines)
        flattened = orch.flatten_positions(reason="test_flatten")
        assert sorted(flattened) == ["AUDUSD", "EURUSD"]
        assert len(engines["AUDUSD"].closed_positions) == 1
        assert engines["AUDUSD"].closed_positions[0]["reason"] == "test_flatten"
        assert engines["AUDUSD"].closed_positions[0]["exit_price"] == 0.65
        assert len(engines["GBPUSD"].closed_positions) == 0

    def test_flatten_no_positions_returns_empty(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", has_position=False),
            "EURUSD": _MockAssetEngine("EURUSD", has_position=False),
        }
        orch = _make_orchestrator(engines)
        flattened = orch.flatten_positions()
        assert flattened == []

    def test_flatten_empty_actors(self):
        orch = EngineOrchestrator({})
        flattened = orch.flatten_positions()
        assert flattened == []

    def test_flatten_skips_missing_current_price(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", current_price=0.0, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", current_price=None, has_position=True),
        }
        orch = _make_orchestrator(engines)
        flattened = orch.flatten_positions()
        assert flattened == []

    def test_flatten_resilient_to_individual_failure(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", current_price=0.65, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", current_price=1.08, has_position=True),
        }

        def _broken_close(*args, **kwargs):
            raise RuntimeError("close failed")

        engines["EURUSD"]._close_position = _broken_close
        orch = _make_orchestrator(engines)
        flattened = orch.flatten_positions()
        # AUDUSD still closes despite EURUSD failure
        assert "AUDUSD" in flattened
        assert len(engines["AUDUSD"].closed_positions) == 1
        # EURUSD failed but overall operation continues
        assert len(engines["EURUSD"].closed_positions) == 0


# ── Tests: drawdown circuit breaker integration with flatten ─────────────────


class TestDrawdownBreakerIntegration:
    def test_breaker_flattens_and_halts_at_15pct(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=85.0, current_price=0.65, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", mtm_value=85.0, current_price=1.08, has_position=True),
        }
        # Each engine starts at 100 mtm, now at 85 → 15% drawdown
        for eng in engines.values():
            eng.mtm_value = 85.0
        orch = _make_orchestrator(engines)
        # Manually set peak to trigger 15% drawdown
        orch._peak_portfolio_value = 100.0 + 100.0  # 200 peak
        results = orch.run_once()
        assert results["drawdown"]["halted"]
        assert results["circuit_breaker"]["triggered"]
        assert results["circuit_breaker"]["reason"].startswith("drawdown_")
        # All positions flattened
        assert len(engines["AUDUSD"].closed_positions) == 1
        assert engines["AUDUSD"].closed_positions[0]["reason"] == "drawdown_circuit_breaker"
        assert len(engines["EURUSD"].closed_positions) == 1

    def test_breaker_does_not_fire_below_threshold(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=95.0, current_price=0.65, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 100.0
        results = orch.run_once()
        assert not results["drawdown"]["halted"]
        # Breaker did not fire, positions NOT closed
        assert len(engines["AUDUSD"].closed_positions) == 0

    def test_after_breaker_next_run_returns_immediately(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=80.0, current_price=0.65, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 100.0
        r1 = orch.run_once()
        assert r1["circuit_breaker"]["triggered"]
        assert len(engines["AUDUSD"].closed_positions) == 1
        # Second run: emergency halt persistent
        r2 = orch.run_once()
        assert r2["circuit_breaker"]["triggered"]
        assert r2["circuit_breaker"]["reason"] == "emergency_halt_persistent"
        # No additional closes
        assert len(engines["AUDUSD"].closed_positions) == 1


# ── Synthetic cascade: correlated AUD pairs simultaneous adverse move ─────────


class TestCorrelatedAUDSyntheticCascade:
    """Simulate a rapid cascade across AUD-correlated assets.

    Scenario: AUDNZD, AUDUSD, and AUDCHF (if still present) drop
    simultaneously from 100 to 70, hitting the circuit breaker.
    This tests the portfolio-level drawdown detection rather than
    per-asset halting.
    """

    def _scenario_equities(self, drop_pct: float) -> dict[str, _MockAssetEngine]:
        engines = {}
        for name in ["AUDUSD", "AUDJPY", "NZDCAD"]:
            mtm = 100.0 * (1.0 - drop_pct)
            engines[name] = _MockAssetEngine(name, mtm_value=mtm, current_price=1.0 - drop_pct, has_position=True)
        return engines

    def test_aud_cascade_15pct_drop_triggers_breaker(self):
        engines = self._scenario_equities(0.15)
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 300.0  # 3 × 100 start
        results = orch.run_once()
        assert results["drawdown"]["halted"]
        assert results["drawdown"]["drawdown"] <= -0.149
        assert results["circuit_breaker"]["triggered"]
        # All 3 positions flattened
        for name in engines:
            assert len(engines[name].closed_positions) == 1
            assert engines[name].closed_positions[0]["reason"] == "drawdown_circuit_breaker"

    def test_aud_cascade_10pct_drop_does_not_trigger_breaker(self):
        engines = self._scenario_equities(0.10)
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 300.0
        results = orch.run_once()
        assert not results["drawdown"]["halted"]
        assert results["circuit_breaker"] is None or not results["circuit_breaker"]["triggered"]
        # No positions closed by circuit breaker
        for name in engines:
            assert len(engines[name].closed_positions) == 0

    def test_aud_cascade_mixed_drawdown_reduces_exposure(self):
        """Between -10% and -15%, exposure is reduced but no halt."""
        engines = self._scenario_equities(0.12)  # -12% total
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 300.0
        results = orch.run_once()
        assert not results["drawdown"]["halted"]
        assert results["drawdown"]["exposure_multiplier"] < 1.0
        assert results["drawdown"]["exposure_multiplier"] > 0.0
        # No positions closed
        for name in engines:
            assert len(engines[name].closed_positions) == 0

    def test_aud_cascade_gradual_recovery(self):
        """Simulate a drop to 15%, then recovery above threshold but breaker stays set."""
        engines = self._scenario_equities(0.15)
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 300.0
        r1 = orch.run_once()
        assert r1["circuit_breaker"]["triggered"]
        assert len(engines["AUDUSD"].closed_positions) == 1
        # Now prices recover to 100 — still halted
        for eng in engines.values():
            eng.mtm_value = 100.0
        orch._peak_portfolio_value = 300.0  # peak unchanged
        r2 = orch.run_once()
        assert r2["circuit_breaker"]["triggered"]
        assert r2["circuit_breaker"]["reason"] == "emergency_halt_persistent"
        # No additional closes
        assert len(engines["AUDUSD"].closed_positions) == 1

    def test_aud_cascade_emergency_halt_reset(self):
        """After reset_emergency_halt, the breaker allows new cycles."""
        engines = self._scenario_equities(0.15)
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 300.0
        r1 = orch.run_once()
        assert r1["circuit_breaker"]["triggered"]
        # Positions are closed; recovery price resets the peak
        orch.reset_emergency_halt()
        for eng in engines.values():
            eng.mtm_value = 100.0
            eng.current_value = 100.0
        # Peak resets to new high since all recovered
        orch._peak_portfolio_value = 300.0
        r2 = orch.run_once()
        # Cycle succeeds — drawdown is now 0% since mtm == peak
        assert r2["circuit_breaker"] is None
        assert not r2["drawdown"]["halted"]


class TestSequentialCascade:
    """Assets drop across multiple cycles, testing cumulative drawdown tracking."""

    def test_sequential_drop_crosses_threshold_on_second_cycle(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=100.0, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", mtm_value=100.0, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 200.0

        # Cycle 1: AUDUSD drops 10% (cumulative portfolio -5%), no trip
        engines["AUDUSD"].mtm_value = 90.0
        engines["AUDUSD"].current_value = 90.0
        r1 = orch.run_once()
        assert not r1["drawdown"]["halted"]
        assert r1["drawdown"]["drawdown"] == pytest.approx(-0.05)
        assert len(engines["AUDUSD"].closed_positions) == 0

        # Cycle 2: EURUSD drops 10% (cumulative portfolio -10%), still below -15% hard limit
        engines["EURUSD"].mtm_value = 90.0
        engines["EURUSD"].current_value = 90.0
        r2 = orch.run_once()
        assert not r2["drawdown"]["halted"]
        assert r2["drawdown"]["drawdown"] == pytest.approx(-0.10)
        assert len(engines["AUDUSD"].closed_positions) == 0

        # Cycle 3: AUDUSD drops another 10% (cumulative portfolio -15%), triggers breaker
        engines["AUDUSD"].mtm_value = 80.0
        engines["AUDUSD"].current_value = 80.0
        r3 = orch.run_once()
        assert r3["drawdown"]["halted"]
        assert r3["drawdown"]["drawdown"] == pytest.approx(-0.15)
        assert r3["circuit_breaker"]["triggered"]
        assert len(engines["AUDUSD"].closed_positions) == 1

    def test_recovery_between_drops_does_not_reset_peak(self):
        engines = {
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=95.0, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", mtm_value=95.0, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 200.0

        # Cycle 1: portfolio at 190 (190/200 = -5%)
        r1 = orch.run_once()
        assert r1["drawdown"]["drawdown"] == pytest.approx(-0.05)
        assert not r1["drawdown"]["halted"]

        # Cycle 2: partial recovery to 195 (still -2.5% from original peak)
        engines["AUDUSD"].mtm_value = 100.0
        engines["AUDUSD"].current_value = 100.0
        r2 = orch.run_once()
        assert r2["drawdown"]["drawdown"] == pytest.approx(-0.025)
        assert not r2["drawdown"]["halted"]

        # Cycle 3: drop again to 170 (cumulative -15% from original peak)
        engines["AUDUSD"].mtm_value = 75.0
        engines["AUDUSD"].current_value = 75.0
        engines["EURUSD"].mtm_value = 95.0
        engines["EURUSD"].current_value = 95.0
        r3 = orch.run_once()
        assert r3["drawdown"]["halted"]
        assert r3["drawdown"]["drawdown"] == pytest.approx(-0.15)
        assert r3["circuit_breaker"]["triggered"]


class TestSingleAssetConcentratedDrop:
    """Single large position can trigger the breaker independently."""

    def test_large_position_drop_triggers_breaker(self):
        """One asset at 60% of portfolio value drops 25% → portfolio -15%."""
        engines = {
            "GC": _MockAssetEngine("GC", mtm_value=300.0, has_position=True),
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=100.0, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", mtm_value=100.0, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 500.0

        # GC drops 25%: 300 → 225, portfolio: 425/500 = -15%
        engines["GC"].mtm_value = 225.0
        engines["GC"].current_value = 225.0
        results = orch.run_once()
        assert results["drawdown"]["halted"]
        assert results["drawdown"]["drawdown"] == pytest.approx(-0.15)
        assert results["circuit_breaker"]["triggered"]
        # All positions get flattened regardless of which asset triggered
        assert len(engines["GC"].closed_positions) == 1
        assert len(engines["AUDUSD"].closed_positions) == 1
        assert len(engines["EURUSD"].closed_positions) == 1

    def test_concentrated_drop_below_threshold_no_trip(self):
        """One asset drops 15% but portfolio drawdown is only -5% due to diversification."""
        engines = {
            "GC": _MockAssetEngine("GC", mtm_value=300.0, has_position=True),
            "AUDUSD": _MockAssetEngine("AUDUSD", mtm_value=100.0, has_position=True),
            "EURUSD": _MockAssetEngine("EURUSD", mtm_value=100.0, has_position=True),
        }
        orch = _make_orchestrator(engines)
        orch._peak_portfolio_value = 500.0

        engines["GC"].mtm_value = 255.0  # -15% on GC = -9% portfolio hit
        engines["GC"].current_value = 255.0
        results = orch.run_once()
        assert not results["drawdown"]["halted"]
        assert results["drawdown"]["drawdown"] == pytest.approx(-0.09)
        assert len(engines["GC"].closed_positions) == 0
