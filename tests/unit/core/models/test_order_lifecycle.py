"""Unit tests for EigenCapital domain models — OrderLifecycle."""

from eigencapital.core.models.order_lifecycle import OrderLifecycle

_counter = 0


def _make_fill(fill_id="F1", quantity=10.0, side="BUY"):
    class MockFill:
        pass

    f = MockFill()
    f.fill_id = fill_id
    f.quantity = quantity
    f.side = side
    f.instrument_id = "ES"
    f.order_id = "O1"
    return f


def _next_id():
    global _counter
    _counter += 1
    return f"LC_{_counter}"


def _make_lifecycle(**overrides):
    defaults = dict(
        order_id=_next_id(),
        order_instrument_id="ES",
        order_side="BUY",
        order_quantity=100.0,
    )
    defaults.update(overrides)
    return OrderLifecycle(**defaults)


def test_lifecycle_creation():
    lc = _make_lifecycle()
    assert lc.order_instrument_id == "ES"
    assert lc.order_side == "BUY"
    assert lc.order_quantity == 100.0
    assert lc.filled_quantity == 0.0
    assert lc.remaining_quantity == 100.0
    assert lc.status == "SUBMITTED"


def test_lifecycle_add_fill():
    lc = _make_lifecycle()
    f1 = _make_fill(fill_id=f"F_{_counter}_1", quantity=30.0)
    lc.add_fill(f1)
    assert lc.filled_quantity == 30.0
    assert lc.remaining_quantity == 70.0
    assert lc.status == "PARTIALLY_FILLED"


def test_lifecycle_fill_aggregate_invariant():
    lc = _make_lifecycle(order_quantity=100.0)
    f1 = _make_fill(fill_id=f"F_{_counter}_1", quantity=60.0)
    f2 = _make_fill(fill_id=f"F_{_counter}_2", quantity=40.0)
    lc.add_fill(f1)
    lc.add_fill(f2)
    assert lc.filled_quantity == 100.0
    assert lc.is_fully_filled
    assert lc.status == "FILLED"
    f3 = _make_fill(fill_id=f"F_{_counter}_3", quantity=10.0)
    try:
        lc.add_fill(f3)
        assert False
    except ValueError as e:
        assert "invariant violated" in str(e).lower()


def test_lifecycle_individual_fills_valid_but_overfill():
    lc = _make_lifecycle(order_quantity=100.0)
    f1 = _make_fill(fill_id=f"F_{_counter}_1", quantity=60.0)
    lc.add_fill(f1)
    f2 = _make_fill(fill_id=f"F_{_counter}_2", quantity=60.0)
    try:
        lc.add_fill(f2)
        assert False
    except ValueError as e:
        assert "exceed order quantity" in str(e).lower()


def test_lifecycle_status_transitions():
    lc = _make_lifecycle(order_quantity=100.0)
    assert lc.status == "SUBMITTED"
    lc.add_fill(_make_fill(fill_id=f"F_{_counter}_1", quantity=50.0))
    assert lc.status == "PARTIALLY_FILLED"
    lc.add_fill(_make_fill(fill_id=f"F_{_counter}_2", quantity=50.0))
    assert lc.status == "FILLED"


def test_lifecycle_remove_fill():
    lc = _make_lifecycle(order_quantity=100.0)
    f1 = _make_fill(fill_id=f"F_{_counter}_1", quantity=50.0)
    lc.add_fill(f1)
    lc.remove_fill(f1.fill_id)
    assert lc.filled_quantity == 0.0
    assert lc.status == "SUBMITTED"


def test_lifecycle_remove_fill_not_found():
    lc = _make_lifecycle()
    try:
        lc.remove_fill("NONEXISTENT")
        assert False
    except ValueError as e:
        assert "not found" in str(e)


def test_lifecycle_duplicate_fill_rejected():
    lc = _make_lifecycle()
    f1 = _make_fill(fill_id=f"F_{_counter}_1", quantity=10.0)
    lc.add_fill(f1)
    try:
        lc.add_fill(f1)
        assert False
    except ValueError as e:
        assert "already exists" in str(e)


def test_lifecycle_properties():
    lc = _make_lifecycle(order_side="BUY")
    assert lc.is_buy and not lc.is_sell
    lc = _make_lifecycle(order_side="SELL")
    assert lc.is_sell and not lc.is_buy


def test_lifecycle_repr():
    lc = _make_lifecycle(order_quantity=100.0)
    r = repr(lc)
    assert "BUY" in r
    assert "100.0" in r
