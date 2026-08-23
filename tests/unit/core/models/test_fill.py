"""Unit tests for EigenCapital domain models — Fill.

Tests per-fill invariants, side/instrument validation, serialization.
The aggregate invariant (sum(fills.quantity) <= order.quantity) lives in OrderLifecycle.
"""

import math
from eigencapital.core.models.fill import Fill

_counter = 0


def _make_fill(**overrides):
    """Helper to create a Fill with sensible defaults. Auto-generates unique fill_id."""
    global _counter
    _counter += 1
    defaults = dict(
        fill_id=f"F{_counter}",
        order_id="O1",
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        quantity=10,
        side="BUY",
        fill_price=4500.0,
        commission=2.50,
        fees=0.50,
        fill_type="FULL",
        liquidity_indicator="TAKER",
        strategy_id="trend_v1",
    )
    defaults.update(overrides)
    return Fill(**defaults)


def test_fill_creation():
    """Test basic Fill creation."""
    fill = _make_fill()
    assert fill.order_id == "O1"
    assert fill.instrument_id == "ES"
    assert fill.quantity == 10
    assert fill.side == "BUY"
    assert fill.fill_price == 4500.0
    assert fill.fill_type == "FULL"
    assert fill.strategy_id == "trend_v1"


def test_fill_quantity_always_positive():
    """INVARIANT: Fill.quantity > 0 always."""
    fill = _make_fill(quantity=0.01)
    assert fill.quantity == 0.01

    try:
        _make_fill(quantity=0)
        assert False, "Should reject quantity=0"
    except ValueError as e:
        assert "quantity must be > 0" in str(e)

    try:
        _make_fill(quantity=-5)
        assert False, "Should reject negative quantity"
    except ValueError as e:
        assert "quantity must be > 0" in str(e)


def test_fill_side_validation():
    """INVARIANT: side must be BUY or SELL."""
    buy = _make_fill(side="BUY")
    assert buy.side == "BUY"

    sell = _make_fill(side="SELL")
    assert sell.side == "SELL"

    try:
        _make_fill(side="HOLD")
        assert False, "Should reject invalid side"
    except ValueError as e:
        assert "side must be 'BUY' or 'SELL'" in str(e)


def test_fill_instrument_id_required():
    """INVARIANT: instrument_id must be non-empty."""
    try:
        _make_fill(instrument_id="")
        assert False, "Should reject empty instrument_id"
    except ValueError as e:
        assert "instrument_id must be non-empty" in str(e)


def test_fill_strategy_id_required():
    """INVARIANT: strategy_id must be non-empty for accountability."""
    try:
        _make_fill(strategy_id="")
        assert False, "Should reject empty strategy_id"
    except ValueError as e:
        assert "strategy_id must be non-empty" in str(e)


def test_fill_timestamp_format():
    """INVARIANT: timestamp_utc must be ISO-8601."""
    fill = _make_fill(timestamp_utc="2024-03-15T09:35:00Z")
    assert "T" in fill.timestamp_utc

    try:
        _make_fill(timestamp_utc="2024-03-15 09:35:00")
        assert False, "Should reject non-ISO timestamp"
    except ValueError as e:
        assert "ISO-8601" in str(e)


def test_fill_price_validation():
    """INVARIANT: fill_price must be finite and positive."""
    fill = _make_fill(fill_price=4500.0)
    assert fill.fill_price == 4500.0

    try:
        _make_fill(fill_price=0)
        assert False, "Should reject fill_price=0"
    except ValueError as e:
        assert "fill_price must be > 0" in str(e)

    try:
        _make_fill(fill_price=float("nan"))
        assert False, "Should reject NaN fill_price"
    except ValueError:
        pass

    try:
        _make_fill(fill_price=float("inf"))
        assert False, "Should reject inf fill_price"
    except ValueError:
        pass


def test_fill_commission_fees_nonnegative():
    """INVARIANT: commission and fees >= 0."""
    fill = _make_fill(commission=0, fees=0)
    assert fill.commission == 0
    assert fill.fees == 0

    try:
        _make_fill(commission=-1)
        assert False, "Should reject negative commission"
    except ValueError as e:
        assert "commission must be >= 0" in str(e)

    try:
        _make_fill(fees=-1)
        assert False, "Should reject negative fees"
    except ValueError as e:
        assert "fees must be >= 0" in str(e)


def test_fill_types():
    """Test fill_type validation."""
    for ft in ("FULL", "PARTIAL", "CANCELLED"):
        fill = _make_fill(fill_type=ft)
        assert fill.fill_type == ft

    try:
        _make_fill(fill_type="UNKNOWN")
        assert False, "Should reject unknown fill_type"
    except ValueError as e:
        assert "Invalid fill_type" in str(e)


def test_fill_liquidity_indicator():
    """Test liquidity_indicator validation."""
    taker = _make_fill(liquidity_indicator="TAKER")
    assert taker.liquidity_indicator == "TAKER"
    assert taker.taker

    maker = _make_fill(liquidity_indicator="MAKER")
    assert maker.liquidity_indicator == "MAKER"
    assert maker.maker

    try:
        _make_fill(liquidity_indicator="UNKNOWN")
        assert False, "Should reject unknown indicator"
    except ValueError as e:
        assert "Invalid liquidity_indicator" in str(e)


def test_fill_to_from_dict():
    """Test deterministic serialization round-trip."""
    from eigencapital.core.models.fill import Fill as FillClass
    original = _make_fill()
    d = original.to_dict()

    assert d["quantity"] == 10
    assert d["side"] == "BUY"

    FillClass._registry.clear()
    roundtrip = FillClass.from_dict(d)
    assert roundtrip.fill_id == original.fill_id
    assert roundtrip.quantity == original.quantity
    assert roundtrip.side == original.side
    assert roundtrip.fill_price == original.fill_price


def test_fill_dict_consistency():
    """Test that to_dict produces consistent output."""
    fill = _make_fill()
    d1 = fill.to_dict()
    d2 = fill.to_dict()
    assert d1 == d2


def test_fill_is_properties():
    """Test convenience properties."""
    fill = _make_fill(fill_type="FULL")
    assert fill.is_full
    assert not fill.is_partial
    assert not fill.is_cancelled

    fill = _make_fill(fill_type="PARTIAL")
    assert fill.is_partial

    fill = _make_fill(fill_type="CANCELLED")
    assert fill.is_cancelled
