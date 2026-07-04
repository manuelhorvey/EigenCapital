import pandas as pd
import numpy as np
import pytest
from features.market_structure import MarketStructureDetector
from paper_trading.entry.optimizer import EntryOptimizer
from paper_trading.entry.deferred_entry import DeferredEntry, DeferredEntryStatus
from paper_trading.entry.decision import SignalType, TradeDecision

def test_market_structure_detection():
    # Trending up data
    data = pd.DataFrame({
        "close": np.linspace(100, 110, 100),
        "high": np.linspace(101, 111, 100),
        "low": np.linspace(99, 109, 100)
    })
    detector = MarketStructureDetector(window=50)
    state = detector.detect(data)
    
    assert state.trend_strength > 0
    assert state.breakout_pressure > 0.8  # Near the top of the range

def test_entry_optimizer_routing():
    optimizer = EntryOptimizer()
    from paper_trading.entry.decision import MarketStructureState
    
    # Momentum Ignition + High Pressure = DEFER
    structure = MarketStructureState(
        trend_strength=0.01,
        compression_score=0.02,
        distance_to_swing_high=0.0,
        distance_to_swing_low=0.10,
        volatility_regime=1.0,
        breakout_pressure=0.95
    )
    
    action = optimizer.evaluate(SignalType.BUY, "MOMENTUM_IGNITION", structure)
    assert action.value == "DEFER"

def test_deferred_entry_lifecycle():
    decision = TradeDecision(
        asset="TEST",
        signal=SignalType.BUY,
        label=2,
        confidence=75.0,
        prob_long=0.75,
        prob_short=0.10,
        prob_neutral=0.15,
        close_price=100.0,
        timestamp="2026-05-26",
        position_size=1.0,
        archetype="MOMENTUM_IGNITION"
    )
    
    entry = DeferredEntry.from_decision(decision, max_bars=2)
    assert entry.status == DeferredEntryStatus.PENDING
    
    entry.update() # Bar 1
    assert entry.status == DeferredEntryStatus.PENDING
    
    entry.update() # Bar 2
    assert entry.status == DeferredEntryStatus.PENDING
    
    entry.update() # Bar 3 -> EXPIRED
    assert entry.status == DeferredEntryStatus.EXPIRED

if __name__ == "__main__":
    pytest.main([__file__])
