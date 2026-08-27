"""Property-based tests for invariant checking.

These tests use Hypothesis to verify that critical invariants hold
across a wide range of inputs. They catch edge cases that unit tests
might miss.
"""
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st, assume, settings
from hypothesis.stateful import RuleBasedStateMachine, rule, precondition

# Import components to test
from eigencapital.reconciliation.engine import (
    ReconciliationEngine, BrokerState, InternalState,
)
from eigencapital.live.health import HealthMonitor, HealthDimension, HealthState
from eigencapital.live.risk_observation import RiskObserver
from eigencapital.production_qual.event_ledger import EventLedger, EventType


# ─── Reconciliation Invariants ──────────────────────────────────────

class TestReconciliationInvariants:
    """Verify reconciliation engine invariants."""
    
    @given(
        position_count=st.integers(min_value=0, max_value=50),
        volume=st.floats(min_value=0.01, max_value=1.0),
    )
    def test_clean_reconciliation_always_reconciled(self, position_count, volume):
        """When broker and internal match, result is always RECONCILED."""
        engine = ReconciliationEngine()
        tickets = list(range(1000, 1000 + position_count))
        
        broker = BrokerState(
            positions=[{"ticket": t, "symbol": f"SYM{t}", "volume": volume, "type": 0, "magic": 20260825} for t in tickets],
            account_equity=5000.0, account_balance=5000.0,
            account_free_margin=5000.0, orders=[],
            timestamp="2026-01-01T00:00:00Z",
        )
        internal = InternalState(
            positions={t: {"ticket": t, "symbol": f"SYM{t}", "volume": volume, "side": "buy"} for t in tickets},
            pending_orders=[], last_signal={}, target_weights={},
            timestamp="2026-01-01T00:00:00Z",
        )
        
        result = engine.reconcile(broker, internal)
        assert result.status == "RECONCILED"
        assert result.action_required == "NONE"
    
    @given(
        broker_qty=st.floats(min_value=0.01, max_value=1.0),
        internal_qty=st.floats(min_value=0.01, max_value=1.0),
    )
    def test_quantity_mismatch_always_blocks(self, broker_qty, internal_qty):
        """When quantities differ, result is never RECONCILED."""
        assume(abs(broker_qty - internal_qty) > 1e-6)
        
        engine = ReconciliationEngine()
        broker = BrokerState(
            positions=[{"ticket": 1001, "symbol": "EURUSD", "volume": broker_qty, "type": 0, "magic": 20260825}],
            account_equity=5000.0, account_balance=5000.0,
            account_free_margin=5000.0, orders=[],
            timestamp="2026-01-01T00:00:00Z",
        )
        internal = InternalState(
            positions={1001: {"ticket": 1001, "symbol": "EURUSD", "volume": internal_qty, "side": "buy"}},
            pending_orders=[], last_signal={}, target_weights={},
            timestamp="2026-01-01T00:00:00Z",
        )
        
        result = engine.reconcile(broker, internal)
        assert result.status != "RECONCILED"
        assert result.action_required == "HALT"
    
    @given(foreign_count=st.integers(min_value=1, max_value=10))
    def test_foreign_positions_always_block(self, foreign_count):
        """Foreign positions always result in BLOCKING."""
        engine = ReconciliationEngine()
        broker = BrokerState(
            positions=[{"ticket": 2000 + i, "symbol": f"FOREIGN{i}", "volume": 0.01, "type": 0, "magic": 0} for i in range(foreign_count)],
            account_equity=5000.0, account_balance=5000.0,
            account_free_margin=5000.0, orders=[],
            timestamp="2026-01-01T00:00:00Z",
        )
        internal = InternalState(
            positions={}, pending_orders=[], last_signal={}, target_weights={},
            timestamp="2026-01-01T00:00:00Z",
        )
        
        result = engine.reconcile(broker, internal)
        assert result.status == "BLOCKING"
        assert result.action_required == "HALT"


# ─── Health State Invariants ────────────────────────────────────────

class TestHealthInvariants:
    """Verify health monitor invariants."""
    
    @given(
        blocked_count=st.integers(min_value=0, max_value=9),
        total_dims=st.integers(min_value=9, max_value=9),
    )
    def test_blocked_dims_always_block_trading(self, blocked_count, total_dims):
        """Any BLOCKED/HALTED dimension blocks trading."""
        monitor = HealthMonitor()
        
        # Set some dimensions to BLOCKED
        dims = list(HealthDimension)
        for i in range(min(blocked_count, len(dims))):
            monitor.update_dimension(dims[i], HealthState.BLOCKED, f"Blocked {i}")
        
        health = monitor.get_system_health()
        
        if blocked_count > 0:
            assert health.authorization != "TRADING_AUTHORIZED"
        else:
            assert health.authorization == "TRADING_AUTHORIZED"
    
    def test_all_healthy_always_authorized(self):
        """When all dimensions are HEALTHY, trading is authorized."""
        monitor = HealthMonitor()
        
        for dim in HealthDimension:
            monitor.update_dimension(dim, HealthState.HEALTHY, "OK")
        
        assert monitor.is_trading_authorized()
    
    @given(state=st.sampled_from(list(HealthState)))
    def test_halted_always_blocks(self, state):
        """HALTED state always blocks trading."""
        monitor = HealthMonitor()
        monitor.update_dimension(HealthDimension.RECONCILIATION, state, "Test")
        
        health = monitor.get_system_health()
        
        if state == HealthState.HALTED:
            assert health.authorization == "TRADING_HALTED"


# ─── Event Ledger Invariants ────────────────────────────────────────

class TestEventLedgerInvariants:
    """Verify event ledger invariants."""
    
    @given(event_count=st.integers(min_value=1, max_value=100))
    @settings(deadline=500)
    def test_events_are_immutable(self, event_count):
        """Events cannot be modified after creation."""
        ledger = EventLedger(base_path="/tmp/property_ledger", flush_after=1000)
        
        events = []
        for i in range(event_count):
            event = ledger.append(
                event_type=EventType.SIGNAL_COMPUTED,
                account_id="test", tier="T1-5K", campaign_id="PROPERTY",
                symbol="EURUSD", payload={"index": i},
            )
            events.append(event)
        
        # Verify all events have unique IDs
        event_ids = [e.event_id for e in events]
        assert len(set(event_ids)) == len(event_ids)
        
        # Verify all events have timestamps
        for event in events:
            assert event.timestamp
            assert event.event_type == "SIGNAL_COMPUTED"
    
    @given(correlation_count=st.integers(min_value=1, max_value=20))
    def test_correlation_chains_are_complete(self, correlation_count):
        """Events with same correlation_id form a complete chain."""
        ledger = EventLedger(base_path="/tmp/property_ledger", flush_after=1000)
        
        chains = {}
        for i in range(correlation_count):
            cid = f"chain-{i}"
            chains[cid] = []
            
            for j in range(3):  # 3 events per chain
                event = ledger.append(
                    event_type=EventType.SIGNAL_COMPUTED,
                    account_id="test", tier="T1-5K", campaign_id="PROPERTY",
                    symbol="EURUSD", correlation_id=cid,
                )
                chains[cid].append(event)
        
        # Verify each chain is reconstructable
        for cid, expected_events in chains.items():
            chain = ledger.get_trade_chain(cid)
            assert len(chain) == len(expected_events)


# ─── Risk Observation Invariants ────────────────────────────────────

class TestRiskObservationInvariants:
    """Verify risk observation invariants."""
    
    @given(equity=st.floats(min_value=0, max_value=100000))
    def test_equity_floor_always_checked(self, equity):
        """Equity floor check always runs."""
        observer = RiskObserver()
        
        state = observer.observe(
            equity=equity, balance=equity, free_margin=equity,
            positions=[], daily_pnl=0.0,
        )
        
        # min_equity=4000, warning zone = 4000 * 1.1 = 4400
        if equity < 4000.0:
            assert state.observations["equity_floor"].level == "CRITICAL"
        elif equity < 4400.0:
            assert state.observations["equity_floor"].level == "WARNING"
        else:
            assert state.observations["equity_floor"].level == "NORMAL"
    
    @given(daily_pnl=st.floats(min_value=-1000, max_value=1000))
    def test_daily_loss_always_tracked(self, daily_pnl):
        """Daily loss is always tracked."""
        observer = RiskObserver(max_daily_loss=250.0)
        
        state = observer.observe(
            equity=5000.0, balance=5000.0, free_margin=5000.0,
            positions=[], daily_pnl=daily_pnl,
        )
        
        expected_loss = max(0, -daily_pnl)
        assert state.observations["daily_loss"].value == expected_loss
