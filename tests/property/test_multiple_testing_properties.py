"""Property tests for multiple-testing correction (F-09)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from eigencapital.analytics.validation.multiple_testing import (
    benjamini_hochberg,
    bonferroni,
    holm,
)

p_values = st.lists(
    st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    max_size=40,
)

TOL = 1e-12


def _rank_order(values: list[float]) -> list[int]:
    return sorted(range(len(values)), key=lambda index: values[index])


@settings(max_examples=200, deadline=None)
@given(p_values)
def test_holm_bounds_monotonicity_and_order(values: list[float]) -> None:
    original = list(values)
    adjusted = holm(values)

    assert values == original
    assert len(adjusted) == len(values)
    assert all(0.0 <= value <= 1.0 for value in adjusted)
    assert all(a + TOL >= p for a, p in zip(adjusted, values))

    rank_order = _rank_order(values)
    ranked = [adjusted[index] for index in rank_order]
    assert all(left <= right + TOL for left, right in zip(ranked, ranked[1:]))


@settings(max_examples=200, deadline=None)
@given(p_values)
def test_bh_bounds_monotonicity_and_order(values: list[float]) -> None:
    original = list(values)
    adjusted = benjamini_hochberg(values)

    assert values == original
    assert len(adjusted) == len(values)
    assert all(0.0 <= value <= 1.0 for value in adjusted)
    assert all(a + TOL >= p for a, p in zip(adjusted, values))

    rank_order = _rank_order(values)
    ranked = [adjusted[index] for index in rank_order]
    assert all(left <= right + TOL for left, right in zip(ranked, ranked[1:]))


@settings(max_examples=200, deadline=None)
@given(p_values)
def test_bh_is_pointwise_at_most_holm(values: list[float]) -> None:
    assert all(
        bh <= hm + TOL for bh, hm in zip(benjamini_hochberg(values), holm(values))
    )


@settings(max_examples=200, deadline=None)
@given(p_values)
def test_bonferroni_bounds_and_order(values: list[float]) -> None:
    adjusted = bonferroni(values)

    assert len(adjusted) == len(values)
    assert all(0.0 <= value <= 1.0 for value in adjusted)
    assert all(a + TOL >= p for a, p in zip(adjusted, values))

    rank_order = _rank_order(values)
    ranked = [adjusted[index] for index in rank_order]
    assert all(left <= right + TOL for left, right in zip(ranked, ranked[1:]))
