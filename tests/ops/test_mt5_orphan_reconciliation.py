"""Tests for MT5 orphan reconciliation — close-time queue, pre-open guard, and orchestrator sweep.

Covers:
    - MT5Broker.close_position() returning True for "not found" (already closed)
    - MT5Broker.close_position() returning False for real failures
    - MT5Broker.ticker_to_mt5_symbol()
    - PositionService.close_position() returning mt5_orphan on failure
    - EngineOrchestrator._reconcile_mt5_orphans() Phase A: drain, retry, abandon
    - EngineOrchestrator._reconcile_mt5_orphans() Phase B: stale ticket detection
    - EntryService._submit_mt5_order() pre-open guard blocking on orphan
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.execution.mt5_broker import MT5Broker
from paper_trading.orchestrator._engine import EngineOrchestrator
from paper_trading.services.entry_service import EntryService
from tests.mock_mt5_client import MockMT5Client

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    return MockMT5Client()


@pytest.fixture
def broker(mock_client):
    return MT5Broker(client=mock_client, symbol_map={"EURUSD": "EURUSD.fx"})


@pytest.fixture
def mock_asset_engine():
    """Minimal AssetEngine-like object for position_service / entry_service tests."""
    engine = MagicMock()
    engine.name = "EURUSD"
    engine.ticker = "EURUSD"
    engine.position = {
        "side": "long",
        "entry": 1.0500,
        "sl": 1.0400,
        "tp": 1.0700,
        "entry_date": "2026-06-17",
        "vol": 0.01,
        "mt5_ticket": 12345,
    }
    engine._mt5_cleanup_queue = []
    engine._mt5_cleanup_retries = 0
    engine.config = {}
    engine.current_value = 100000.0
    engine.initial_capital = 100000.0
    engine.pos_mgr.position_size = 0.95
    engine.pos_mgr.exposure_multiplier = 1.0
    engine.pos_mgr.current_value = 100000.0
    return engine


# ── MT5Broker.close_position() — "not found" ────────────────────────────


class TestMT5BrokerClosePosition:
    def test_close_already_closed_returns_true(self, broker, mock_client):
        """Bridge returns not-found → broker returns True (position is gone)."""
        mock_client._close_result = {"error": "Position 99999 not found"}
        result = broker.close_position("EURUSD", "99999")
        assert result is True

    def test_close_success_returns_true(self, broker, mock_client):
        """Bridge returns success retcode → broker returns True."""
        mock_client._close_result = {"result": {"retcode": 10009}}
        result = broker.close_position("EURUSD", "12345")
        assert result is True

    def test_close_real_failure_returns_false(self, broker, mock_client):
        """Bridge returns genuine failure → broker returns False."""
        mock_client._close_result = {"error": "close failed: market closed"}
        result = broker.close_position("EURUSD", "12345")
        assert result is False

    def test_close_no_tick_returns_false(self, broker, mock_client):
        """Bridge returns no-tick error → broker returns False (retryable)."""
        mock_client._close_result = {"error": "No tick for EURUSD.fx to close position"}
        result = broker.close_position("EURUSD", "12345")
        assert result is False

    def test_close_network_exception_raises(self, broker, mock_client):
        """Network errors propagate up to position_service's except block."""
        mock_client._close_result = None

        def _raise(*args):
            raise ConnectionError("bridge down")

        mock_client.close_position = _raise
        with pytest.raises(ConnectionError):
            broker.close_position("EURUSD", "12345")


# ── MT5Broker.ticker_to_mt5_symbol() ────────────────────────────────────


class TestTickerToMt5Symbol:
    def test_mapped_symbol(self, broker):
        assert broker.ticker_to_mt5_symbol("EURUSD") == "EURUSD.fx"

    def test_unmapped_symbol_passthrough(self, broker):
        assert broker.ticker_to_mt5_symbol("GBPNZD") == "GBPNZD"


# ── PositionService.close_position() — atomic close (MT5 before paper) ──


class TestPositionServiceAtomicClose:
    @pytest.fixture
    def pos_service(self, mock_asset_engine, broker):
        from paper_trading.services.position_service import PositionService

        bridge = MagicMock()
        bridge._is_real_broker = True
        bridge.broker = broker
        bridge.fill_price.return_value = (1.0500, 0.0, 0.0)

        pos_mgr = MagicMock()
        pos_mgr.close.return_value = {"return": 0.01, "pnl": 100.0}
        pos_mgr.trade_log = []
        pos_mgr.current_value = 100000.0
        pos_mgr.has_position.return_value = True
        pos_mgr.position_size = 0.95
        pos_mgr.exposure_multiplier = 1.0
        pos_mgr.position.side = "long"

        svc = PositionService(
            name="EURUSD",
            ticker="EURUSD",
            config={},
            pos_mgr=pos_mgr,
            state_store=None,
            attribution=MagicMock(),
            attribution_svc=MagicMock(),
            execution_bridge=bridge,
            model=None,
            shadow_sltp=None,
        )
        return svc

    def test_does_not_abort_paper_close_on_mt5_failure(self, pos_service, broker, mock_client, mock_asset_engine):
        """When MT5 close fails, paper close still proceeds — mutations returned.

        This is a critical safety fix: previously, a single MT5 failure would
        block the paper close, causing the paper position to become orphaned
        indefinitely. Now the paper close proceeds regardless, and the MT5
        orphan is cleaned up by the orchestrator's reconciliation loop.
        """
        mock_client._close_result = {"error": "close failed: market closed"}
        mutations = pos_service.close_position(
            exit_price=1.0500,
            exit_date="2026-06-17",
            reason="stop_loss",
            position=mock_asset_engine.position,
            current_value=100000.0,
            entry_archetype="TREND",
            current_trade_id="t1",
            attribution_buffer=[],
            cycle_counter=1,
            last_entry_slippage=0.0,
            last_policy_hash="abc",
            exit_archetype="",
            attribution_export_dir="",
            experiment_id="",
            entry_signal_dir=1,
            last_macro_dir=None,
            last_blend_dir=None,
        )
        assert mutations != {}, "Paper close should proceed despite MT5 failure"
        assert "trade" in mutations, "Paper close should return trade data"
        pos_service.pos_mgr.close.assert_called_once()

    def test_paper_close_on_mt5_success(self, pos_service, broker, mock_client, mock_asset_engine):
        """When MT5 close succeeds, paper close proceeds."""
        mock_client._close_result = {"result": {"retcode": 10009, "ticket": 12345}}
        mutations = pos_service.close_position(
            exit_price=1.0500,
            exit_date="2026-06-17",
            reason="stop_loss",
            position=mock_asset_engine.position,
            current_value=100000.0,
            entry_archetype="TREND",
            current_trade_id="t1",
            attribution_buffer=[],
            cycle_counter=1,
            last_entry_slippage=0.0,
            last_policy_hash="abc",
            exit_archetype="",
            attribution_export_dir="",
            experiment_id="",
            entry_signal_dir=1,
            last_macro_dir=None,
            last_blend_dir=None,
        )
        assert "mt5_orphan" not in mutations
        pos_service.pos_mgr.close.assert_called_once()

    def test_paper_close_on_already_closed(self, pos_service, broker, mock_client, mock_asset_engine):
        """When MT5 position is already closed (not found), paper close proceeds."""
        mock_client._close_result = {"error": "Position 12345 not found"}
        mutations = pos_service.close_position(
            exit_price=1.0500,
            exit_date="2026-06-17",
            reason="stop_loss",
            position=mock_asset_engine.position,
            current_value=100000.0,
            entry_archetype="TREND",
            current_trade_id="t1",
            attribution_buffer=[],
            cycle_counter=1,
            last_entry_slippage=0.0,
            last_policy_hash="abc",
            exit_archetype="",
            attribution_export_dir="",
            experiment_id="",
            entry_signal_dir=1,
            last_macro_dir=None,
            last_blend_dir=None,
        )
        assert "mt5_orphan" not in mutations
        pos_service.pos_mgr.close.assert_called_once()


# ── EngineOrchestrator._reconcile_mt5_orphans() — Phase A ────────────────


class _OrphanEngine:
    """Minimal engine stub for orchestrator reconciliation tests."""

    def __init__(self, name: str, cleanup_queue=None, position=None, broker=None):
        self.name = name
        self._mt5_cleanup_queue = cleanup_queue or []
        self._mt5_cleanup_retries = 0
        self.position = position
        self.ticker = name
        self.mtm_value = 100000.0
        self.current_value = 100000.0
        self.pos_mgr = MagicMock()
        self.pos_mgr.position_size = 1.0
        self.pos_mgr.exposure_multiplier = 1.0
        self.pos_mgr.current_value = 100000.0
        self.pos_mgr.has_position.return_value = False
        self._last_entry_notional = 0.0
        if broker is not None:
            bridge = MagicMock()
            bridge._is_real_broker = True
            bridge.broker = broker
            self.execution_bridge = bridge
        else:
            self.execution_bridge = None


class _OrphanActor:
    def __init__(self, name: str, cleanup_queue=None, position=None, broker=None):
        self.name = name
        self._engine = _OrphanEngine(name, cleanup_queue, position, broker=broker)
        self.health = MagicMock()
        self.health.value = "GREEN"

    def drain_persist_queue(self):
        return []


@pytest.fixture
def orch():
    actors = {}
    return EngineOrchestrator(actors, wal_writer=None)


class TestReconcilePhaseA:
    def test_empty_queue_noop(self, orch, broker, mock_client):
        """No cleanup queue — nothing happens."""
        mock_client._close_result = {"error": "close failed: market closed"}
        orch._actors["EURUSD"] = _OrphanActor("EURUSD", cleanup_queue=[], broker=broker)
        broker.connect()
        orch._reconcile_mt5_orphans()
        assert orch._actors["EURUSD"]._engine._mt5_cleanup_retries == 0

    def test_orphan_cleaned_on_retry(self, orch, broker, mock_client):
        """Orphan in queue → retry close succeeds → queue drained."""
        mock_client._close_result = {"result": {"retcode": 10009, "ticket": 12345}}
        actor = _OrphanActor("EURUSD", cleanup_queue=[("EURUSD.fx", 12345)], broker=broker)
        orch._actors["EURUSD"] = actor
        broker.connect()
        orch._reconcile_mt5_orphans()
        assert actor._engine._mt5_cleanup_queue == []
        assert actor._engine._mt5_cleanup_retries == 0

    def test_orphan_retried_on_persistent_failure(self, orch, broker, mock_client):
        """Orphan close keeps failing → stays in queue, retry incremented."""
        mock_client._close_result = {"error": "close failed: market closed"}
        actor = _OrphanActor("EURUSD", cleanup_queue=[("EURUSD.fx", 12345)], broker=broker)
        orch._actors["EURUSD"] = actor
        broker.connect()

        orch._reconcile_mt5_orphans()
        assert len(actor._engine._mt5_cleanup_queue) == 1
        assert actor._engine._mt5_cleanup_retries == 1

        orch._reconcile_mt5_orphans()
        assert actor._engine._mt5_cleanup_retries == 2

    def test_orphan_abandoned_after_max_retries(self, orch, broker, mock_client):
        """After MAX_CLEANUP_RETRIES failures → queue cleared with ERROR."""
        mock_client._close_result = {"error": "close failed: market closed"}
        actor = _OrphanActor("EURUSD", cleanup_queue=[("EURUSD.fx", 12345)], broker=broker)
        orch._actors["EURUSD"] = actor
        broker.connect()

        for _ in range(EngineOrchestrator.MAX_CLEANUP_RETRIES + 1):
            orch._reconcile_mt5_orphans()

        assert actor._engine._mt5_cleanup_queue == []
        assert actor._engine._mt5_cleanup_retries == 0

    def test_orphan_cleared_when_already_closed_on_retry(self, orch, broker, mock_client):
        """Position already closed natively between cycles → retry succeeds."""
        mock_client._close_result = {"error": "Position 12345 not found"}
        actor = _OrphanActor("EURUSD", cleanup_queue=[("EURUSD.fx", 12345)], broker=broker)
        orch._actors["EURUSD"] = actor
        broker.connect()
        orch._reconcile_mt5_orphans()
        assert actor._engine._mt5_cleanup_queue == []
        assert actor._engine._mt5_cleanup_retries == 0


# ── EngineOrchestrator._reconcile_mt5_orphans() — Phase B ────────────────


class TestReconcilePhaseB:
    def test_stale_ticket_grace_period_holds(self, orch, broker, mock_client):
        """Ticket survives MAX_STALE_TICKET_CYCLES-1 cycles, then cleared on last.

        Verifies the grace period prevents premature closure during MT5
        order fill propagation delay (~5 min at 30s/cycle).
        A valid deal result is returned so the deal-history check (cycle 3)
        does not trigger early closure — the full grace period runs.
        """
        mock_client._positions = []
        # Provide a valid deal result so the deal check at
        # STALE_TICKET_DEAL_CHECK_CYCLES does not trigger early closure
        mock_client._deal_results = {
            "99999": {
                "result": {
                    "ticket": 99999,
                    "order": 88888,
                    "symbol": "EURUSD.fx",
                    "type": 1,
                    "volume": 0.1,
                    "price": 1.0500,
                    "profit": 0.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "time": 0,
                    "comment": "EigenCapital",
                }
            }
        }
        actor = _OrphanActor(
            "EURUSD",
            position={
                "side": "long",
                "mt5_ticket": 99999,
            },
            broker=broker,
        )
        orch._actors["EURUSD"] = actor
        broker.connect()

        # Run MAX_STALE_TICKET_CYCLES-1 cycles — ticket should survive
        for _ in range(orch.MAX_STALE_TICKET_CYCLES - 1):
            orch._reconcile_mt5_orphans()
            assert actor._engine.position.get("mt5_ticket") == 99999, f"Ticket cleared early at cycle {_ + 1}"

        # Run the final cycle — ticket should be cleared
        orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") is None

    def test_stale_ticket_no_deal_rejected(self, orch, broker, mock_client):
        """Ticket missing and deal history empty → closed after STALE_TICKET_DEAL_CHECK_CYCLES.

        When the deal history confirms the order was never filled,
        the paper position is closed early (after 3 cycles instead of 10).
        """
        mock_client._positions = []
        mock_client._deal_results = {"99999": None}  # no deal found
        actor = _OrphanActor(
            "EURUSD",
            position={
                "side": "long",
                "mt5_ticket": 99999,
            },
            broker=broker,
        )
        orch._actors["EURUSD"] = actor
        broker.connect()

        # Run STALE_TICKET_DEAL_CHECK_CYCLES-1 cycles — ticket survives
        for _ in range(orch.STALE_TICKET_DEAL_CHECK_CYCLES - 1):
            orch._reconcile_mt5_orphans()
            assert actor._engine.position.get("mt5_ticket") == 99999

        # Run the deal-check cycle — ticket should be cleared (order rejected)
        orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") is None

    def test_stale_ticket_deal_found_closed(self, orch, broker, mock_client):
        """Ticket missing but deal history shows it was filled → grace continues.

        When deal history confirms the order was genuinely filled (then
        closed by MT5-native SL/TP or manual), we wait for the full
        MAX_STALE_TICKET_CYCLES before closing the paper position to
        avoid race conditions with the paper position manager.
        """
        mock_client._positions = []
        mock_client._deal_results = {
            "99999": {
                "result": {
                    "ticket": 99999,
                    "order": 88888,
                    "symbol": "EURUSD.fx",
                    "type": 1,
                    "volume": 0.1,
                    "price": 1.0500,
                    "profit": 100.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "time": 0,
                    "comment": "EigenCapital",
                }
            }
        }
        actor = _OrphanActor(
            "EURUSD",
            position={
                "side": "long",
                "mt5_ticket": 99999,
            },
            broker=broker,
        )
        orch._actors["EURUSD"] = actor
        broker.connect()

        # Run STALE_TICKET_DEAL_CHECK_CYCLES cycles — deal found, ticket survives
        for _ in range(orch.STALE_TICKET_DEAL_CHECK_CYCLES):
            orch._reconcile_mt5_orphans()
            assert actor._engine.position.get("mt5_ticket") == 99999, (
                f"Ticket closed early despite deal found at cycle {_ + 1}"
            )

        # Full grace period should still complete
        for _ in range(orch.MAX_STALE_TICKET_CYCLES - orch.STALE_TICKET_DEAL_CHECK_CYCLES):
            orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") is None

    def test_stale_ticket_recovered_before_deal_check(self, orch, broker, mock_client):
        """Ticket missing for 2 cycles then reappears → counter resets."""
        mock_client._positions = []
        mock_client._deal_results = {}
        actor = _OrphanActor(
            "EURUSD",
            position={
                "side": "long",
                "mt5_ticket": 99999,
            },
            broker=broker,
        )
        orch._actors["EURUSD"] = actor
        broker.connect()

        # 2 cycles with no position
        for _ in range(2):
            orch._reconcile_mt5_orphans()
            assert actor._engine.position.get("mt5_ticket") == 99999

        # Ticket reappears in broker positions
        mock_client._positions = [
            {
                "ticket": 99999,
                "symbol": "EURUSD.fx",
                "type": "buy",
                "volume": 0.1,
                "price_open": 1.0500,
                "price_current": 1.0600,
                "profit": 100.0,
                "commission": 0.0,
                "sl": 1.0400,
                "tp": 1.0700,
                "time": 0,
                "comment": "EigenCapital",
            },
        ]
        orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") == 99999  # recovered

        # Remove ticket again and verify grace period restarts from 0
        mock_client._positions = []
        for _ in range(orch.STALE_TICKET_DEAL_CHECK_CYCLES - 1):
            orch._reconcile_mt5_orphans()
            assert actor._engine.position.get("mt5_ticket") == 99999, (
                f"Ticket cleared early after reset at cycle {_ + 1}"
            )
        # Deal check would fire here but deal_results is {} so closes early
        orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") is None

    def test_valid_ticket_preserved(self, orch, broker, mock_client):
        """Paper mt5_ticket matches an open MT5 position → preserved."""
        mock_client._positions = [
            {
                "ticket": 12345,
                "symbol": "EURUSD.fx",
                "type": "buy",
                "volume": 0.1,
                "price_open": 1.0500,
                "price_current": 1.0600,
                "profit": 100.0,
                "commission": 0.0,
                "sl": 1.0400,
                "tp": 1.0700,
                "time": 0,
                "comment": "EigenCapital",
            },
        ]
        actor = _OrphanActor(
            "EURUSD",
            position={
                "side": "long",
                "mt5_ticket": 12345,
            },
            broker=broker,
        )
        orch._actors["EURUSD"] = actor
        broker.connect()
        orch._reconcile_mt5_orphans()
        assert actor._engine.position.get("mt5_ticket") == 12345

    def test_no_position_nothing_to_check(self, orch, broker, mock_client):
        """No paper position → Phase B skips."""
        mock_client._positions = []
        actor = _OrphanActor("EURUSD", position=None, broker=broker)
        orch._actors["EURUSD"] = actor
        broker.connect()
        orch._reconcile_mt5_orphans()  # should not raise


# ── EntryService pre-open guard ──────────────────────────────────────────


class TestPreOpenGuard:
    @pytest.fixture
    def entry_with_orphan(self, broker, mock_client):
        """EntryService with MT5 broker that has an orphaned position."""
        mock_client._positions = [
            {
                "ticket": 99999,
                "symbol": "EURUSD.fx",
                "type": "buy",
                "volume": 0.1,
                "price_open": 1.0500,
                "price_current": 1.0600,
                "profit": 100.0,
                "commission": 0.0,
                "sl": 1.0400,
                "tp": 1.0700,
                "time": 0,
                "comment": "EigenCapital",
            },
        ]
        mock_client._close_result = {"result": {"retcode": 10009, "ticket": 99999}}

        engine = MagicMock()
        engine.name = "EURUSD"
        engine.ticker = "EURUSD"
        engine.current_price = 1.0600
        engine.config = {}
        engine.price_data = MagicMock()
        engine.validity_sm = MagicMock()
        engine.validity_sm.current_state.value = "GREEN"
        engine.governance = MagicMock()
        engine.governance._narrative_sl_mult = 1.0
        engine.governance._narrative_size_scalar = 1.0
        engine.governance._liquidity_sl_mult = 1.0
        engine.governance._liquidity_size_scalar = 1.0
        engine.sl_mult = 1.0
        engine.tp_mult = 2.0
        engine.regime_geometry = {}
        engine._entry_archetype = "UNKNOWN"
        engine._structure_detector = MagicMock()
        engine._entry_optimizer = MagicMock()
        engine.initial_capital = 100000
        engine.capital_base = 100000
        engine.current_value = 100000
        engine.pos_mgr.position_size = 0.95
        engine.pos_mgr.exposure_multiplier = 1.0
        engine._attribution = MagicMock()
        engine._shadow_sltp = None
        engine._pending_entries = {}
        engine._sltp_engine = None
        engine._scale_out_engine = None
        engine._last_label = 0
        engine._last_confidence = 0.0
        engine._last_prob_long = 0.0
        engine._last_prob_short = 0.0
        engine._last_prob_neutral = 0.0
        engine._last_meta_proba = None
        engine._current_regime = "neutral"
        engine._kelly_multiplier = 1.0
        engine._drawdown_taper_mult = 1.0

        bridge = MagicMock()
        bridge._is_real_broker = True
        bridge.broker = broker
        engine.execution_bridge = bridge

        return engine, broker, mock_client

    def test_guard_blocks_entry_when_orphan_exists(self, entry_with_orphan):
        """Pre-open guard returns None mt5_ticket when orphan position exists."""
        engine, broker, mock_client = entry_with_orphan
        service = EntryService()

        fill_price, slippage, mt5_ticket = service._submit_mt5_order(
            engine,
            "buy",
            1.0600,
            1.0400,
            1.0700,
        )

        assert mt5_ticket is None
        assert fill_price == 1.0600
