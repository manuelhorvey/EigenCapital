import pytest

from shared.sizing_chain import SizingChain, SizingInput


@pytest.fixture
def mt5_input():
    return SizingInput(
        equity=100.0,
        drawdown_pct=0.0,
        is_mt5=True,
        kelly_multiplier=1.0,
        max_position_pct=0.15,
        entry_price=1.0,
        sl_distance=0.01,
    )


def test_mt5_no_budget_ref(mt5_input):
    """MT5 sizing works without leverage budget (budget ref removed — sizing by position/risk cap)."""
    result = SizingChain.compute(mt5_input)
    assert result.is_viable
    assert result.skip_reason is None
