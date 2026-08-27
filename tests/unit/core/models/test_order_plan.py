"""Unit tests for EigenCapital domain models — OrderPlan."""

from eigencapital.core.models.order_plan import OrderPlan, Urgency

_counter = 0


def _make_plan(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        plan_id=f"OP_{_counter}",
        instrument_id="ES",
        target_quantity=5.0,
        current_quantity=2.0,
        quantity_delta=3.0,
        execution_policy_version="v1",
        urgency=Urgency.SESSION,
    )
    defaults.update(overrides)
    return OrderPlan(**defaults)


def test_order_plan_creation():
    op = _make_plan()
    assert op.target_quantity == 5.0
    assert op.quantity_delta == 3.0
    assert op.urgency == Urgency.SESSION


def test_order_plan_delta_invariant():
    op = _make_plan(target_quantity=10.0, current_quantity=3.0, quantity_delta=7.0)
    assert op.quantity_delta == 7.0
    try:
        _make_plan(target_quantity=10.0, current_quantity=3.0, quantity_delta=5.0)
        raise AssertionError()
    except ValueError as e:
        assert "quantity_delta" in str(e)


def test_order_plan_urgency_validation():
    for urg in (Urgency.IMMEDIATE, Urgency.SESSION, Urgency.END_OF_DAY):
        op = _make_plan(urgency=urg)
        assert op.urgency == urg
    try:
        _make_plan(urgency="LATER")
        raise AssertionError()
    except ValueError as e:
        assert "Invalid urgency" in str(e)


def test_order_plan_fulfillable():
    assert _make_plan(quantity_delta=3.0).is_fulfillable
    op = _make_plan(target_quantity=2.0, current_quantity=2.0, quantity_delta=0.0)
    assert not op.is_fulfillable


def test_order_plan_delta_sign():
    assert _make_plan(quantity_delta=3.0).delta_sign == "BUY"
    assert _make_plan(target_quantity=-2.0, current_quantity=1.0, quantity_delta=-3.0).delta_sign == "SELL"
    op = _make_plan(target_quantity=2.0, current_quantity=2.0, quantity_delta=0.0)
    assert op.delta_sign == "FLAT"


def test_order_plan_to_from_dict():
    original = _make_plan()
    d = original.to_dict()
    assert d["target_quantity"] == original.target_quantity
    assert d["quantity_delta"] == original.quantity_delta


def test_order_plan_dict_consistency():
    op = _make_plan()
    assert op.to_dict() == op.to_dict()
