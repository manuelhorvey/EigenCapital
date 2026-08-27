"""Unit tests for EigenCapital domain models — Position.

Tests signed quantity invariants, average_entry_price None when flat,
serialization, and deterministic behavior.
"""

from eigencapital.core.models.position import Position

_counter = 0


def _next_instrument():
    """Generate unique instrument_id for each test case."""
    global _counter
    _counter += 1
    return f"ES_{_counter}"


def test_position_creation_long():
    """Test Position creation with LONG quantity (positive)."""
    pos = Position(
        instrument_id=_next_instrument(),
        quantity=1,
        average_entry_price=4000.0,
        market_value=4000.0,
    )
    assert pos.quantity == 1
    assert pos.side == "LONG"
    assert pos.is_long
    assert not pos.is_flat
    assert not pos.is_short


def test_position_creation_short():
    """Test Position creation with SHORT quantity (negative)."""
    pos = Position(
        instrument_id=_next_instrument(),
        quantity=-1,
        average_entry_price=4000.0,
        market_value=4000.0,
    )
    assert pos.quantity == -1
    assert pos.side == "SHORT"
    assert pos.is_short
    assert not pos.is_long
    assert not pos.is_flat


def test_position_creation_flat():
    """Test Position creation with FLAT quantity (zero)."""
    pos = Position(
        instrument_id=_next_instrument(),
        quantity=0,
        average_entry_price=None,
    )
    assert pos.quantity == 0
    assert pos.side == "FLAT"
    assert pos.is_flat
    assert not pos.is_long
    assert not pos.is_short


def test_position_flat_invariant():
    """Test invariant: quantity == 0 => average_entry_price is None or 0."""
    # Valid: average_entry_price=None
    Position(instrument_id=_next_instrument(), quantity=0, average_entry_price=None)

    # Valid: average_entry_price=0
    Position(instrument_id=_next_instrument(), quantity=0, average_entry_price=0)

    # Invalid: average_entry_price=4000.0 with quantity=0
    try:
        Position(
            instrument_id=_next_instrument(),
            quantity=0,
            average_entry_price=4000.0,
        )
        raise AssertionError("Should reject")
    except ValueError as e:
        assert "Invariant violated" in str(e)


def test_position_short_invariant():
    """Test that short position has negative quantity."""
    pos = Position(
        instrument_id=_next_instrument(),
        quantity=-5,
        average_entry_price=3500.0,
        market_value=17500.0,
    )
    assert pos.quantity == -5
    assert pos.side == "SHORT"
    assert pos.is_short


def test_position_not_nan_inf():
    """Test NaN/inf quantities are rejected."""
    try:
        Position(instrument_id=_next_instrument(), quantity=float("nan"))
        raise AssertionError("Should reject NaN quantity")
    except ValueError:
        pass

    try:
        Position(instrument_id=_next_instrument(), quantity=float("inf"))
        raise AssertionError("Should reject inf quantity")
    except ValueError:
        pass


def test_position_to_from_dict():
    """Test deterministic serialization round-trip."""
    original = Position(
        instrument_id=_next_instrument(),
        quantity=2,
        average_entry_price=4100.0,
        market_value=8200.0,
        unrealized_pnl=150.0,
        realized_pnl_today=50.0,
        overnight=True,
    )

    d = original.to_dict()
    assert "instrument_id" in d
    assert "quantity" in d

    # Verify dict fields match
    assert d["instrument_id"] == original.instrument_id
    assert d["quantity"] == original.quantity
    assert d["average_entry_price"] == original.average_entry_price
    assert d["market_value"] == original.market_value


def test_position_dict_consistency():
    """Test that to_dict produces consistent output."""
    original = Position(
        instrument_id=_next_instrument(),
        quantity=-1,
        average_entry_price=12000.0,
        market_value=12000.0,
        unrealized_pnl=-50.0,
    )
    d1 = original.to_dict()
    d2 = original.to_dict()
    assert d1 == d2


def test_position_side_property():
    """Test Position.side property from quantity sign."""
    assert Position(instrument_id=_next_instrument(), quantity=3).side == "LONG"
    assert Position(instrument_id=_next_instrument(), quantity=-3).side == "SHORT"
    assert Position(instrument_id=_next_instrument(), quantity=0).side == "FLAT"


def test_position_is_properties():
    """Test Position.is_long, .is_short, .is_flat properties."""
    pos = Position(instrument_id=_next_instrument(), quantity=5)
    assert pos.is_long
    assert not pos.is_short
    assert not pos.is_flat

    pos = Position(instrument_id=_next_instrument(), quantity=-5)
    assert pos.is_short
    assert not pos.is_long
    assert not pos.is_flat

    pos = Position(instrument_id=_next_instrument(), quantity=0)
    assert pos.is_flat
    assert not pos.is_long
    assert not pos.is_short


def test_position_notional():
    """Test Position.notional property."""
    pos = Position(instrument_id=_next_instrument(), quantity=2, market_value=4100.0)
    assert pos.notional == 4100.0

    pos = Position(instrument_id=_next_instrument(), quantity=2, market_value=0.0)
    assert pos.notional == 0.0


def test_position_negative_quantity():
    """Test negative quantity is valid for SHORT."""
    pos = Position(instrument_id=_next_instrument(), quantity=-1)
    assert pos.quantity == -1
    assert pos.is_short


def test_position_overnight():
    """Test overnight flag."""
    pos = Position(instrument_id=_next_instrument(), quantity=1, overnight=True)
    assert pos.overnight is True

    pos = Position(instrument_id=_next_instrument(), quantity=1, overnight=False)
    assert pos.overnight is False


def test_position_to_dict_roundtrip_with_none_avg_entry():
    """Test round-trip with average_entry_price=None (flat position)."""
    original = Position(
        instrument_id=_next_instrument(),
        quantity=0,
        average_entry_price=None,
    )
    d = original.to_dict()
    assert d["average_entry_price"] is None
    assert d["quantity"] == 0


def test_position_no_position_side_field():
    """Test that Position does NOT have position_side field (sign encodes direction)."""
    pos = Position(instrument_id=_next_instrument(), quantity=5)
    d = pos.to_dict()
    assert "position_side" not in d
    assert pos.side == "LONG"
