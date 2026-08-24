"""Unit tests for EigenCapital domain models — Order.

Tests positive quantity, side not signed, signed derivation, lifecycle invariants,
serialization, and deterministic behavior.
"""

from eigencapital.core.models.order import Order


def _make_order(order_id="O1", **overrides):
    """Helper to create an Order with sensible defaults."""
    defaults = dict(
        order_id=order_id,
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        order_type="MARKET",
        side="BUY",
        quantity=100,
        strategy_id="test_strategy",
    )
    defaults.update(overrides)
    return Order(**defaults)


def test_order_creation_buy():
    """Test Order creation with BUY side."""
    order = _make_order()
    assert order.order_id == "O1"
    assert order.instrument_id == "ES"
    assert order.side == "BUY"
    assert order.quantity == 100
    assert order.status == "SUBMITTED"
    assert order.filled_quantity == 0
    assert order.remaining_quantity == 100


def test_order_creation_sell():
    """Test Order creation with SELL side."""
    order = _make_order(
        order_id="O2", side="SELL", limit_price=18000.0, order_type="LIMIT"
    )
    assert order.side == "SELL"
    assert order.quantity == 100
    assert order.limit_price == 18000.0
    assert order.stop_price is None


def test_order_quantity_always_positive():
    """Test that quantity is always positive (or zero for cancel)."""
    order = _make_order(order_id="O3")
    assert order.quantity == 100

    order = _make_order(order_id="O4", quantity=0)
    assert order.quantity == 0

    try:
        _make_order(order_id="O5", quantity=-10)
        assert False, "Should reject negative quantity"
    except ValueError:
        pass


def test_order_side_not_signed():
    """Test that side is BUY/SELL, not signed quantity."""
    order = _make_order(order_id="O6")
    assert order.side == "BUY"
    assert order.signed_quantity == 100

    order = _make_order(order_id="O7", side="SELL")
    assert order.side == "SELL"
    assert order.signed_quantity == -100


def test_order_signed_quantity_derivation():
    """Test signed_quantity property derivation."""
    order = _make_order(order_id="O8")
    assert order.signed_quantity == 100

    order = _make_order(order_id="O9", side="SELL")
    assert order.signed_quantity == -100

    order = _make_order(order_id="O10", quantity=10)
    assert order.signed_quantity == 10

    order = _make_order(order_id="O11", side="SELL", quantity=10)
    assert order.signed_quantity == -10


def test_order_remaining_quantity():
    """Test remaining_quantity property."""
    order = _make_order(order_id="O12")
    assert order.remaining_quantity == 100


def test_order_limit_stop_validation():
    """Test limit_price and stop_price validation."""
    order = _make_order(order_id="O13", order_type="LIMIT", limit_price=4500.0)
    assert order.limit_price == 4500.0

    order = _make_order(order_id="O14", order_type="STOP", stop_price=4550.0)
    assert order.stop_price == 4550.0

    order = _make_order(
        order_id="O15", order_type="STOP_LIMIT", limit_price=4500.0, stop_price=4550.0
    )
    assert order.limit_price == 4500.0
    assert order.stop_price == 4550.0


def test_order_filled_price_validation():
    """Test filled_price validation."""
    order = _make_order(
        order_id="O16",
        filled_price=4500.0,
        filled_quantity=50,
        average_fill_price=4500.0,
    )
    assert order.filled_price == 4500.0
    assert order.filled_quantity == 50
    assert order.average_fill_price == 4500.0
    assert order.remaining_quantity == 50


def test_order_average_fill_price_matches_filled_price():
    """Test that average_fill_price matches filled_price."""
    order = _make_order(
        order_id="O17",
        filled_price=4500.0,
        filled_quantity=100,
        average_fill_price=4500.0,
    )
    assert order.average_fill_price == order.filled_price


def test_order_status_transitions():
    """Test order status validation."""
    for i, status in enumerate(
        ["SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"]
    ):
        _make_order(order_id=f"O18_{i}", status=status)

    try:
        _make_order(order_id="O19", status="INVALID")
        assert False, "Should reject invalid status"
    except ValueError:
        pass


def test_order_instrument_id_required():
    """Test that instrument_id is non-empty."""
    try:
        _make_order(order_id="O20", instrument_id="")
        assert False, "Should reject empty instrument_id"
    except ValueError:
        pass


def test_order_strategy_id_required():
    """Test that strategy_id is non-empty."""
    try:
        _make_order(order_id="O21", strategy_id="")
        assert False, "Should reject empty strategy_id"
    except ValueError:
        pass


def test_order_to_from_dict():
    """Test deterministic serialization round-trip."""
    original = _make_order(
        order_id="O22",
        order_type="LIMIT",
        side="BUY",
        limit_price=4500.0,
        strategy_id="trend_v1",
    )

    d = original.to_dict()
    assert "order_id" in d
    assert "side" in d
    assert "quantity" in d
    assert "limit_price" in d
    assert "status" in d

    roundtrip = Order.from_dict(d)
    assert roundtrip.order_id == original.order_id
    assert roundtrip.instrument_id == original.instrument_id
    assert roundtrip.side == original.side
    assert roundtrip.quantity == original.quantity
    assert roundtrip.limit_price == original.limit_price
    assert roundtrip.status == original.status
    assert roundtrip.strategy_id == original.strategy_id


def test_order_dict_consistency():
    """Test that to_dict produces consistent output."""
    original = _make_order(order_id="O23", side="SELL", quantity=50)
    d1 = original.to_dict()
    d2 = original.to_dict()
    assert d1 == d2
    assert list(d1.keys()) == list(d2.keys())


def test_order_config_hash_not_present():
    """Test that Order does NOT have config_hash."""
    order = _make_order(order_id="O24")
    d = order.to_dict()
    assert "config_hash" not in d
    assert "strategy_config_hash" not in d
