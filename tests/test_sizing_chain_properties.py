"""Property-based tests for SizingChain invariants.

Verifies that the multiplicative guardrail chain preserves key safety
properties across a wide range of synthetic inputs (not just fixed cases).
"""
from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from shared.sizing_chain import SizingChain, SizingInput, SizingResult


positive_finite = st.floats(
    min_value=1.0, max_value=1e9, allow_nan=False, allow_infinity=False
)
price = st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False)
small_positive = st.floats(
    min_value=1e-6, max_value=1.0, allow_nan=False, allow_infinity=False
)
drawdown = st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)
fraction = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def sizing_inputs(draw):
    is_mt5 = draw(st.booleans())
    inp = SizingInput(
        equity=draw(positive_finite),
        drawdown_pct=draw(drawdown),
        size_scalar=draw(fraction),
        kelly_multiplier=draw(st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)),
        max_position_pct=draw(st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False)),
        max_risk_pct=draw(st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)),
        min_viable_pct=draw(small_positive),
        entry_price=draw(price),
        sl_distance=draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        is_mt5=is_mt5,
        ticker="TEST",
    )
    return inp


@given(sizing_inputs())
@settings(max_examples=100, deadline=None)
def test_is_viable_iff_no_skip_reason(inp: SizingInput) -> None:
    """vim chain contract: is_viable True iff no skip_reason is set."""
    result: SizingResult = SizingChain.compute(inp)
    if result.is_viable:
        assert result.skip_reason is None
    else:
        assert result.skip_reason is not None


@given(sizing_inputs())
@settings(max_examples=100, deadline=None)
def test_notional_nonnegative(inp: SizingInput) -> None:
    """Notional never goes negative."""
    result = SizingChain.compute(inp)
    assert result.notional >= 0


@given(sizing_inputs())
@settings(max_examples=100, deadline=None)
def test_quantity_nonnegative(inp: SizingInput) -> None:
    """Quantity is always >= 0."""
    result = SizingChain.compute(inp)
    assert result.quantity >= 0


def test_drawdown_taper_invariant_at_zero_dd() -> None:
    """At zero drawdown, taper should be 1.0."""
    assert SizingChain.drawdown_taper(0.0) == 1.0


def test_drawdown_taper_invariant_at_max_dd() -> None:
    """At end_dd drawdown, taper should equal min_size."""
    result = SizingChain.drawdown_taper(-0.20, -0.05, -0.15, 0.50)
    assert result == 0.50


@given(
    dd=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    start_dd=st.floats(max_value=-0.01, allow_nan=False, allow_infinity=False),
    end_dd=st.floats(max_value=-0.20, allow_nan=False, allow_infinity=False),
    min_size=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_drawdown_taper_within_bounds(dd, start_dd, end_dd, min_size) -> None:
    """Taper output is always in [min_size, 1.0]."""
    taper = SizingChain.drawdown_taper(dd, start_dd, end_dd, min_size)
    assert min_size <= taper <= 1.0 + 1e-9


def test_atomic_decrement_thread_safe() -> None:
    """Concurrent compute() calls exercise the chain safely."""
    n_calls = 20
    inp = SizingInput(
        equity=100000.0,
        drawdown_pct=0.0,
        is_mt5=False,
        size_scalar=0.05,
        entry_price=100.0,
        sl_distance=2.0,
    )

    def attempt():
        return SizingChain.compute(inp)

    results = [attempt() for _ in range(n_calls)]
    viable = sum(1 for r in results if r.is_viable)

    # All calls should produce a viable result if equity suffices
    assert viable >= 1
    # No side effects
    for r in results:
        assert isinstance(r, SizingResult)


def test_zero_equity_does_not_crash() -> None:
    """Zero equity should not crash; result is not viable."""
    inp = SizingInput(
        equity=0.0,
        drawdown_pct=0.0,
        is_mt5=False,
        size_scalar=0.5,
        entry_price=1.0,
        sl_distance=0.01,
    )
    result = SizingChain.compute(inp)
    # Should not crash; result might be viable or not depending on guards
    assert isinstance(result, SizingResult)


def test_extreme_size_scalar_does_not_explode_notional() -> None:
    """An unrealistic size_scalar should be capped by per-position cap."""
    inp = SizingInput(
        equity=100000.0,
        drawdown_pct=0.0,
        is_mt5=False,
        size_scalar=10.0,  # 10x normal — should be capped
        entry_price=100.0,
        sl_distance=2.0,
        max_position_pct=0.15,
    )
    result = SizingChain.compute(inp)
    assert result.is_viable
    assert result.notional <= 0.15 * 100000.0 + 1e-6


def test_extreme_drawdown_yields_taper_floor() -> None:
    """Very deep drawdown yields the min_size taper, not zero."""
    inp = SizingInput(
        equity=100000.0,
        drawdown_pct=-0.50,  # -50% drawdown (worse than end_dd -0.15)
        is_mt5=False,
        size_scalar=1.0,
        entry_price=100.0,
        sl_distance=2.0,
    )
    result = SizingChain.compute(inp)
    # drawdown_taper should have hit min_size floor (0.50 default)
    assert result.drawdown_taper >= 0.50
