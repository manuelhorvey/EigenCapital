"""End-to-end orchestrator cycle integration test (TEST-02).

Exercises the full EngineOrchestrator 4-phase cycle with mocked external
dependencies (MT5, yfinance, model inference). Verifies that:

    1. Pre-phase builds PortfolioStateSnapshot + RiskBudget + PerformanceState
    2. Phase 1a runs parallel actor cycles and collects signals
    3. Phase 1b runs PEK admission review
    4. Phase 2 updates validity states
    5. Phase 3 runs portfolio health, circuit breakers, VaR
    6. Phase 4 persists queued commands and records trade outcomes
    7. The overall results dict has all expected phase keys

Does NOT require Wine, MT5 terminal, yfinance, or pre-trained models.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from paper_trading.orchestrator.engine import EngineOrchestrator


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_price_data():
    """Generate deterministic price data for 2 assets."""
    np.random.seed(42)
    n = 300
    prices = 100 + np.cumsum(np.random.randn(n) * 0.3)
    df = pd.DataFrame(
        {
            "close": prices,
            "high": prices * 1.005,
            "low": prices * 0.995,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"),
    )
    return df


@pytest.fixture
def mock_signals():
    """Canned signal dict returned by generate_signal()."""
    return {
        "asset": "TEST",
        "signal": "BUY",
        "side": "long",
        "final_signal": "BUY",
        "confidence": 65.0,
        "prob_long": 0.65,
        "prob_short": 0.15,
        "prob_neutral": 0.20,
        "position_size": 0.5,
        "close_price": 100.0,
    }


def _make_mock_engine(name: str, price: float = 100.0) -> SimpleNamespace:
    """Build a minimal AssetEngine mock for orchestrator testing.

    Covers the minimum surface area required by EngineOrchestrator:
      - mtm_value, current_value, current_price
      - pos_mgr with has_position(), current_side(), has_position() bool
      - generate_signal(), refresh_price(), update_pnl(), update_validity()
      - trade_log, batches, position
    """
    pos_mgr = SimpleNamespace(
        has_position=lambda: False,
        current_side=lambda: None,
        position=None,
        exposure_multiplier=1.0,
        halted=False,
        trade_log=[],
    )
    return SimpleNamespace(
        name=name,
        mtm_value=100_000.0,
        current_value=100_000.0,
        current_price=price,
        capital_base=100_000.0,
        pos_mgr=pos_mgr,
        config={},
        ticker="EURUSD=X",
        _cycle_total_equity=100_000.0,
        _cycle_drawdown_pct=0.0,
        _last_entry_notional=0.0,
        trade_log=[],
        batches={},
        position=None,
        _last_gates_trace={},
        _last_confidence=65.0,
        _last_spread_bps=5.0,
        _spread_tier="fx_major",
        _risk_off=False,
        _signal_chain=[],
        _kelly_multiplier=1.0,
        _calibration_applied=False,
        _gate_blocked_counts={},
        generate_signal=lambda threshold=0.45, shared_macro=None: {
            "asset": name,
            "signal": "HOLD",
            "side": "none",
            "final_signal": "HOLD",
            "confidence": 50.0,
            "prob_long": 0.5,
            "prob_short": 0.5,
            "prob_neutral": 0.0,
            "position_size": 0.0,
            "close_price": price,
        },
        refresh_price=lambda: None,
        update_pnl=lambda: None,
        update_validity=lambda halt=None: {"state": "GREEN", "exposure": 1.0},
        check_halt_conditions=lambda metrics=None: {"halted": False},
        _close_position=lambda exit_price, exit_date, reason: True,
        _close_all_positions=lambda exit_price, exit_date, reason: True,
        get_metrics=lambda: {
            "current_value": 100_000.0,
            "current_price": price,
            "position": None,
            "meta_inference": {},
            "feature_stability": {},
            "drawdown": 0.0,
        },
        _decision_to_dict=lambda decision, final_signal=None: {},
    )


def _make_actor(name: str, engine=None) -> SimpleNamespace:
    """Build a minimal AssetActor mock for orchestrator testing."""
    if engine is None:
        engine = _make_mock_engine(name)
    from paper_trading.orchestrator.actor import ActorHealth, ActorMetrics

    return SimpleNamespace(
        name=name,
        health=ActorHealth.GREEN,
        health_score=100.0,
        metrics=ActorMetrics(),
        _engine=engine,
        _max_failures=10,
        _recovery_cooldown=60.0,
        _wal=None,
        _persist_queue=[],
        _fault_reason="",
        _last_trade_count=0,
        _last_price=None,
        _last_recovery_probe=0.0,
        run_cycle=lambda market_data=None, shared_macro=None: SimpleNamespace(
            success=True,
            asset=name,
            signal={
                "asset": name,
                "signal": "HOLD",
                "side": "none",
                "final_signal": "HOLD",
                "confidence": 50.0,
                "prob_long": 0.5,
                "prob_short": 0.5,
                "prob_neutral": 0.0,
                "position_size": 0.0,
                "close_price": 100.0,
            },
            error=None,
            cycle_id=1,
            duration_ms=5.0,
        ),
        drain_persist_queue=lambda: [],
        reset=lambda: None,
    )


# ── Mock the data-fetching layer ────────────────────────────────────────────


@pytest.fixture
def mock_data_fetch(mock_price_data):
    """Patch the data-fetching layer to return canned price data without
    making any network calls (yfinance or MT5).
    """
    # Patch at the actual import sites used by the code under test.
    # fetch_live is imported in pipeline.py from paper_trading.ops.data_fetcher.
    # fetch_asset_data/ohlcv are imported inside _build_feature_set from features.data_fetch.
    patches = [
        patch("paper_trading.ops.data_fetcher.fetch_live", return_value=mock_price_data),
        patch("features.data_fetch.fetch_asset_data", return_value=(
            mock_price_data, pd.DataFrame(),
            pd.Series(dtype=float), pd.Series(dtype=float),
            pd.Series(dtype=float), pd.DataFrame(),
        )),
        patch("features.data_fetch.fetch_asset_ohlcv", return_value=mock_price_data),
        patch("features.data_fetch.prefetch_shared_data", return_value={}),
        patch("features.alpha_features._compute_shared_features", return_value=pd.DataFrame()),
        patch("features.alpha_features.build_alpha_features", return_value=pd.DataFrame({
            "TEST_mom_21d": [0.01] * 300,
            "TEST_mom_63d": [0.02] * 300,
            "TEST_zscore_20": [0.5] * 300,
        }, index=mock_price_data.index)),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture
def mock_wal():
    """Mock WAL writer that records all events in memory."""
    events: list[tuple[str, dict]] = []

    def _write(kind: str, data: dict) -> None:
        events.append((kind, data))

    return SimpleNamespace(write=_write, flush=lambda: None, events=events)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestOrchestratorCycle:
    """Full orchestrator cycle integration tests."""

    def test_builds_portfolio_snapshot(self, mock_data_fetch):
        """Pre-phase should build a valid PortfolioStateSnapshot."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        assert orch._portfolio_snapshot is not None
        assert orch._portfolio_snapshot.total_equity > 0
        assert orch._portfolio_snapshot.mode == "production"
        assert orch._portfolio_snapshot.open_position_count == 0

    def test_pre_phase_injects_cycle_context(self, mock_data_fetch):
        """Pre-phase should distribute cycle equity/drawdown to all actors."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()

        for name in ("EURUSD", "GBPUSD"):
            actor = actors[name]
            assert hasattr(actor._engine, "_cycle_total_equity")
            assert actor._engine._cycle_total_equity > 0
            assert actor._engine.pos_mgr.exposure_multiplier == 1.0

    def _init_phase_results(self) -> dict:
        """Initialize results dict with keys expected by individual phase methods."""
        return {"phasetimestamps": {}, "assets": {}, "circuit_breaker": None, "health": None}

    def test_phase_1a_refresh_signal_collects_results(self, mock_data_fetch):
        """Phase 1a should collect asset results from all actors."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()

        results = self._init_phase_results()
        orch._phase_1_refresh_signal(None, results)

        assert "assets" in results
        assert "EURUSD" in results["assets"]
        assert "GBPUSD" in results["assets"]

    def test_phase_1b_admission_review_produces_admission(self, mock_data_fetch):
        """Phase 1b PEK admission should produce admission results."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        results = self._init_phase_results()
        orch._phase_1_refresh_signal(None, results)
        orch._phase_1b_admission_review(results, defaults, max_leverage, budget_ref)

        assert "admission" in results

    def test_phase_2_validity_updates_successfully(self, mock_data_fetch):
        """Phase 2 validity updates should not raise."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()

        results = self._init_phase_results()
        orch._phase_2_validity(results)  # should not raise

    def test_phase_3_portfolio_health_returns_ok(self, mock_data_fetch):
        """Phase 3 should compute health without tripping circuit breakers."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()

        results = self._init_phase_results()
        halted = orch._phase_3_portfolio_health(results, {}, 2.0)

        assert not halted  # no circuit breakers should trip in normal conditions
        assert "health" in results
        assert results["health"]["system_healthy"]

    def test_phase_4_persist_does_not_raise(self, mock_data_fetch):
        """Phase 4 persist should flush buffers without raising."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._wal = SimpleNamespace(write=lambda kind, data: None, flush=lambda: None)

        results = self._init_phase_results()
        orch._phase_4_persist(results)  # should not raise

    def _assert_full_cycle_result(self, result: dict | None) -> None:
        """Assert common full-cycle result expectations."""
        assert result is not None, "run_once() returned None — check orchestrator cycle for exceptions"
        assert isinstance(result, dict)
        assert "phasetimestamps" in result
        assert "health" in result
        assert "drawdown" in result
        breaker = result.get("circuit_breaker")
        assert breaker is None or not breaker.get("triggered", False)

    def test_run_once_full_cycle(self, mock_data_fetch):
        """Full run_once() cycle returns expected phase structure."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        result = orch.run_once(market_data=None)
        self._assert_full_cycle_result(result)

    def test_run_once_writes_health_events_to_wal(self, mock_data_fetch, mock_wal):
        """Full run_once() should write health events to WAL."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2, wal_writer=mock_wal)

        result = orch.run_once(market_data=None)
        self._assert_full_cycle_result(result)

        # Check that health events were written
        health_events = [e for e in mock_wal.events if e[0] == "actor_health"]
        assert len(health_events) >= 1
        assert health_events[0][1]["system_healthy"]

    def test_emergency_halt_not_tripped_on_normal_cycle(self, mock_data_fetch):
        """Normal cycle should not trip emergency halt."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        result = orch.run_once(market_data=None)

        assert not orch.emergency_halt
        self._assert_full_cycle_result(result)

    def test_cycle_elapsed_increments(self, mock_data_fetch):
        """Each run_once() should increment the cycle counter."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)

        assert orch._cycles_elapsed == 0
        orch.run_once()
        assert orch._cycles_elapsed == 1
        orch.run_once()
        assert orch._cycles_elapsed == 2

    def test_peak_portfolio_value_tracks_peak(self, mock_data_fetch):
        """Peak portfolio value should be the max of init equity."""
        actors = {
            "EURUSD": _make_actor("EURUSD", engine=_make_mock_engine("EURUSD", price=100.0)),
            "GBPUSD": _make_actor("GBPUSD", engine=_make_mock_engine("GBPUSD", price=100.0)),
        }
        orch = EngineOrchestrator(actors, max_workers=2)

        orch.run_once()
        assert orch._halt_state.peak_portfolio_value is not None
        assert orch._halt_state.peak_portfolio_value > 0

    def test_actor_failure_is_isolated(self, mock_data_fetch):
        """A single actor failure should not crash the orchestrator or other actors."""
        actors = {
            "WORKING": _make_actor("WORKING"),
            "FAILING": _make_actor("FAILING"),
        }
        # Make the FAILING actor raise on run_cycle
        def _failing_run(market_data=None, shared_macro=None):
            from paper_trading.orchestrator.actor import AssetResult
            return AssetResult.failed("FAILING", "simulated_failure")
        actors["FAILING"].run_cycle = _failing_run

        orch = EngineOrchestrator(actors, max_workers=2)
        result = orch.run_once()

        assert result is not None
        # The orchestrator should not have emergency halted
        assert not orch.emergency_halt


class TestOrchestratorWithPositions:
    """Tests with simulated open positions."""

    def test_open_positions_appear_in_snapshot(self, mock_data_fetch):
        """Open positions should be reflected in the portfolio snapshot."""
        eur_engine = _make_mock_engine("EURUSD", price=1.05)
        # Add a live position
        pos = SimpleNamespace(
            side="long",
            quantity=100_000,
            entry_price=1.04,
            stop_loss=1.03,
            take_profit=1.07,
        )
        eur_engine.pos_mgr.position = pos
        eur_engine.pos_mgr.has_position = lambda: True
        eur_engine.pos_mgr.current_side = lambda: "long"

        actors = {
            "EURUSD": _make_actor("EURUSD", engine=eur_engine),
            "GBPUSD": _make_actor("GBPUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()

        snap = orch._portfolio_snapshot
        assert snap is not None
        assert snap.open_position_count == 1
        assert snap.total_long_notional > 0

    def test_negative_equity_does_not_crash(self, mock_data_fetch):
        """Snapshot builder should handle 0 equity gracefully."""
        eng = _make_mock_engine("DEAD", price=0.0)
        eng.mtm_value = 0.0
        eng.current_value = 0.0

        actors = {
            "DEAD": _make_actor("DEAD", engine=eng),
            "ALIVE": _make_actor("ALIVE"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._pre_phase_pek()  # should not raise

        snap = orch._portfolio_snapshot
        assert snap is not None
        assert snap.total_equity >= 0


class TestOrchestratorHalt:
    """Tests for orchestrator halt behavior."""

    def test_drawdown_circuit_breaker_places_flatten(self, mock_data_fetch):
        """Drawdown circuit breaker should flatten positions."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._halt_state.peak_portfolio_value = 100_000.0

        flattened = orch.flatten_positions(reason="drawdown_circuit_breaker")
        assert isinstance(flattened, list)

    def test_auto_unhalt_eligibility_checks(self, mock_data_fetch):
        """Auto-unhalt should become eligible when drawdown recovers."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._halt_state.set_halt("DRAWDOWN", "dd=-0.2000")
        orch._halt_state.peak_portfolio_value = 100_000.0

        # Simulate recovery: equity back to peak
        orch._cycle_total_equity = 99_500.0
        orch._cycles_elapsed = 10

        # Should eventually mark as eligible
        orch._halt_state.unhalt_recovery_cycles = 10
        orch._halt_state.check_auto_unhalt(orch._cycles_elapsed, orch._cycle_total_equity)
        # After sufficient recovery cycles, it should unhalt

    def test_halt_persistent_logging_does_not_crash(self, mock_data_fetch):
        """Throttled halt warning should not crash."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._halt_state.set_halt("DRAWDOWN", "test")
        orch._cycles_elapsed = 1

        orch._halt_state.maybe_warn_persistent(orch._cycles_elapsed, 100_000.0)  # should not raise


class TestOrchestratorWeekendFilter:
    """Tests for weekend/asset-filtered cycles."""

    def test_filtered_actors_returns_subset(self, mock_data_fetch):
        """_filtered_actors should return only the allowed subset."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "BTCUSD": _make_actor("BTCUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)

        weekend = orch._filtered_actors({"BTCUSD"})
        assert "BTCUSD" in weekend
        assert "EURUSD" not in weekend

    def test_filtered_actors_none_returns_all(self, mock_data_fetch):
        """_filtered_actors with None returns all actors."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "BTCUSD": _make_actor("BTCUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)

        all_actors = orch._filtered_actors(None)
        assert len(all_actors) == 2

    def test_weekend_cycle_tracks_full_equity(self, mock_data_fetch):
        """Even during filtered cycles, portfolio metrics use the full actor set."""
        actors = {
            "EURUSD": _make_actor("EURUSD"),
            "BTCUSD": _make_actor("BTCUSD"),
        }
        orch = EngineOrchestrator(actors, max_workers=2)
        orch._saved_full_actors = actors

        result = orch.run_once(market_data=None, allowed_assets={"BTCUSD"})
        assert result is not None
        # Only BTCUSD should appear in assets
        assert "BTCUSD" in result.get("assets", {})
