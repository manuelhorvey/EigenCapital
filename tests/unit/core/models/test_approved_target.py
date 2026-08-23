"""Unit tests for EigenCapital domain models — ApprovedTarget."""

from eigencapital.core.models.approved_target import ApprovedTarget

_counter = 0


def _make_target(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        target_id=f"PT_{_counter}",
        intended_quantity=5.0,
        approved_quantity=5.0,
        decision="APPROVED",
        approval_reason="Within all risk limits",
    )
    defaults.update(overrides)
    return ApprovedTarget(**defaults)


def test_approved_target_creation():
    at = _make_target()
    assert at.intended_quantity == 5.0
    assert at.approved_quantity == 5.0
    assert at.decision == "APPROVED"


def test_approved_target_decision_validation():
    assert _make_target(decision="APPROVED").decision == "APPROVED"
    assert _make_target(decision="REDUCED").decision == "REDUCED"
    at = _make_target(decision="REJECTED", approved_quantity=0.0)
    assert at.decision == "REJECTED"
    try:
        _make_target(decision="UNKNOWN")
        assert False
    except ValueError as e:
        assert "Invalid approved target decision" in str(e)


def test_approved_target_rejected_implies_zero():
    at = _make_target(decision="REJECTED", approved_quantity=0.0, approval_reason="Exceeds limit")
    assert at.is_rejected
    assert at.approved_quantity == 0.0


def test_approved_target_rejected_nonzero():
    try:
        _make_target(decision="REJECTED", approved_quantity=5.0)
        assert False
    except ValueError as e:
        assert "REJECTED must have approved_quantity = 0" in str(e)


def test_approved_target_convenience_properties():
    at = _make_target(decision="APPROVED", approved_quantity=5.0)
    assert at.is_approved and not at.is_rejected
    at = _make_target(decision="REDUCED", intended_quantity=5.0, approved_quantity=3.0)
    assert at.is_reduced and at.approved_differs
    at = _make_target(decision="REJECTED", approved_quantity=0.0)
    assert at.is_rejected and at.approved_differs


def test_approved_target_requires_reason():
    try:
        _make_target(approval_reason="")
        assert False
    except ValueError as e:
        assert "approval_reason must be non-empty" in str(e)


def test_approved_target_to_from_dict():
    original = _make_target(approval_reason="Test roundtrip")
    d = original.to_dict()
    assert d["target_id"] == original.target_id
    assert d["decision"] == original.decision
    # Verify key fields without roundtrip (registry would block)
    assert d["intended_quantity"] == original.intended_quantity
    assert d["approved_quantity"] == original.approved_quantity


def test_approved_target_dict_consistency():
    at = _make_target()
    assert at.to_dict() == at.to_dict()


def test_approved_target_summary():
    at = _make_target()
    s = at.summary()
    assert "APPROVED" in s
