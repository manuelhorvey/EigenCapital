import pytest
from paper_trading.entry.policy import ExecutionPolicyLayer
from paper_trading.entry.decision import (
    EntryAction, 
    SignalType, 
    TradeDecision, 
    MarketStructureState, 
    TPGeometry
)

def test_policy_layer_determinism():
    layer = ExecutionPolicyLayer()
    
    dec = TradeDecision("TEST", SignalType.BUY, 2, 75.0, 0.75, 0.1, 0.15, 100.0, "2026-05-26", 1.0, "BREAKOUT_TEST")
    struct = MarketStructureState(0.01, 0.02, 0, 0, 1.0, 0.95)
    tp_geo = TPGeometry(2.0, [], 1.5, {})
    
    # Same inputs -> same output
    res1 = layer.handle(EntryAction.ENTER, dec, "BREAKOUT_TEST", struct, tp_geo)
    res2 = layer.handle(EntryAction.ENTER, dec, "BREAKOUT_TEST", struct, tp_geo)
    
    assert res1 == res2
    assert res1.action == EntryAction.ENTER
    assert res1.exit_plan == tp_geo

def test_momentum_ignition_routing_reason():
    layer = ExecutionPolicyLayer()
    dec = TradeDecision("TEST", SignalType.BUY, 2, 75.0, 0.75, 0.1, 0.15, 100.0, "2026-05-26", 1.0, "MOMENTUM_IGNITION")
    struct = MarketStructureState(0.01, 0.02, 0, 0, 1.0, 0.95)
    
    res = layer.handle(EntryAction.DEFER, dec, "MOMENTUM_IGNITION", struct)
    assert res.action == EntryAction.DEFER
    assert "deferred (Structural Pressure: 0.95)" in res.reason

def test_policy_layer_no_market_logic():
    """Verify that the policy layer does not perform market calculations."""
    import inspect
    from paper_trading.entry.policy import ExecutionPolicyLayer
    
    source = inspect.getsource(ExecutionPolicyLayer)
    # Ensure no common calculation terms exist
    forbidden = ["np.log", "stats.linregress", "rolling(", "std()", "ewm("]
    for f in forbidden:
        assert f not in source, f"Market calculation '{f}' found in Policy Layer!"

if __name__ == "__main__":
    pytest.main([__file__])
