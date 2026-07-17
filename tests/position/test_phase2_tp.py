import pytest
from paper_trading.entry.tp_compiler import compute_take_profit
from paper_trading.entry.decision import MarketStructureState, ValidityState


def test_tp_compiler_determinism():
    struct = MarketStructureState(0.001, 0.02, 0.01, 0.05, 1.0, 0.5)

    # Same inputs -> same output
    geo1 = compute_take_profit(100.0, 2.0, ValidityState.GREEN, "MOMENTUM_IGNITION", struct)
    geo2 = compute_take_profit(100.0, 2.0, ValidityState.GREEN, "MOMENTUM_IGNITION", struct)

    assert geo1.tp_distance == geo2.tp_distance
    assert geo1.scale_out_tiers == geo2.scale_out_tiers
    assert geo1.convexity_score == geo2.convexity_score


def test_tp_compiler_archetype_sensitivity():
    struct = MarketStructureState(0.001, 0.02, 0.01, 0.05, 1.0, 0.5)

    # Momentum Ignition should have higher convexity and backloaded tiers
    geo_mi = compute_take_profit(100.0, 2.0, ValidityState.GREEN, "MOMENTUM_IGNITION", struct)

    # Mean Reversion should have lower convexity and frontloaded tiers
    geo_mr = compute_take_profit(100.0, 2.0, ValidityState.GREEN, "MEAN_REVERSION", struct)

    assert geo_mi.convexity_score > geo_mr.convexity_score
    assert geo_mi.tp_distance > geo_mr.tp_distance

    # Check MI backloaded: last tier multiplier is highest
    assert geo_mi.scale_out_tiers[-1][1] > geo_mi.scale_out_tiers[0][1]
    # Check MR frontloaded: first tier fraction is high
    assert geo_mr.scale_out_tiers[0][0] >= 0.5


def test_tp_compiler_regime_safety():
    struct = MarketStructureState(0.001, 0.02, 0.01, 0.05, 1.0, 0.5)

    # Normal trend
    geo_trend = compute_take_profit(100.0, 2.0, "trend", "TREND_PULLBACK", struct)

    # Crisis regime - should compress TP
    geo_crisis = compute_take_profit(100.0, 2.0, "crisis", "TREND_PULLBACK", struct)

    assert geo_crisis.tp_distance < geo_trend.tp_distance
    # Ensure tiers didn't flip structure (Balanced still balanced)
    assert geo_crisis.scale_out_tiers == geo_trend.scale_out_tiers


def test_tp_compiler_no_internal_imports():
    """Verify decoupling: compiler should not import heavy project modules."""
    import sys

    # Check modules currently loaded
    project_mods = [
        m
        for m in sys.modules
        if m.startswith("paper_trading.")
        and m != "paper_trading.entry.tp_compiler"
        and m != "paper_trading.entry.decision"
    ]

    # This test is a bit tricky since they might be loaded by other tests,
    # but we can check the file content.
    with open("paper_trading/entry/tp_compiler.py", "r") as f:
        content = f.read()

    assert "import AssetEngine" not in content
    assert "from paper_trading.asset_engine" not in content
    assert "import PositionManager" not in content
    assert "import ScaleOutEngine" not in content


if __name__ == "__main__":
    pytest.main([__file__])
