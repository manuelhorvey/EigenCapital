"""Unit tests for EigenCapital domain models — RiskDecision."""

from eigencapital.core.models.risk_check_result import RiskCheckResult
from eigencapital.core.models.risk_decision import RiskDecision

_counter = 0


def _make_check(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        check_id=f"chk_{_counter}",
        status="PASS",
        observed=0.84,
        limit=2.0,
        unit="x",
        message="OK",
    )
    defaults.update(overrides)
    return RiskCheckResult(**defaults)


def _make_decision(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        decision_id=f"RD_{_counter}",
        timestamp_utc="2024-03-15T09:35:01Z",
        instrument_id="ES",
        intended_position=5.0,
        approved_position=5.0,
        decision="APPROVED",
        reason="Within all limits",
        var=1250.0,
        var_method="gaussian_99",
        risk_checks=[_make_check()],
        decision_snapshot_id="DS0",
    )
    defaults.update(overrides)
    return RiskDecision(**defaults)


def test_risk_decision_creation():
    rd = _make_decision()
    assert rd.decision == "APPROVED"
    assert rd.intended_position == 5.0
    assert rd.var == 1250.0
    assert rd.var_method == "gaussian_99"
    assert len(rd.risk_checks) == 1


def test_risk_decision_status_validation():
    assert _make_decision(decision="APPROVED").decision == "APPROVED"
    assert _make_decision(decision="REDUCED").decision == "REDUCED"
    rd = _make_decision(decision="REJECTED", approved_position=0.0)
    assert rd.decision == "REJECTED"
    try:
        _make_decision(decision="UNKNOWN")
        assert False
    except ValueError as e:
        assert "Invalid risk decision" in str(e)


def test_risk_decision_rejected_implies_zero():
    rd = _make_decision(decision="REJECTED", approved_position=0.0, reason="Exceeds max leverage")
    assert rd.is_rejected
    assert rd.approved_position == 0.0


def test_risk_decision_rejected_nonzero_rejected():
    try:
        _make_decision(decision="REJECTED", approved_position=5.0)
        assert False
    except ValueError as e:
        assert "REJECTED must have approved_position = 0" in str(e)


def test_risk_decision_no_var_breach():
    rd = _make_decision()
    assert "var_breach" not in rd.to_dict()


def test_risk_decision_risk_checks_is_list():
    checks = [_make_check(check_id="a"), _make_check(check_id="b", status="WARN", observed=0.08, limit=0.10, message="Near limit")]
    rd = _make_decision(risk_checks=checks)
    assert isinstance(rd.risk_checks, list)
    assert len(rd.risk_checks) == 2
    assert all(isinstance(c, RiskCheckResult) for c in rd.risk_checks)


def test_risk_decision_check_status_method():
    checks = [_make_check(check_id="lev", status="PASS"), _make_check(check_id="dd", status="FAIL", observed=0.12, limit=0.10, message="Breached")]
    rd = _make_decision(risk_checks=checks)
    assert rd.check_status("lev") is not None
    assert rd.check_status("lev").status == "PASS"
    assert rd.check_status("dd") is not None
    assert rd.check_status("dd").status == "FAIL"
    assert rd.check_status("nonexistent") is None


def test_risk_decision_var_diagnostic():
    rd = _make_decision(var=5000.0, var_method="historical_95")
    assert rd.var_diagnostic == 5000.0


def test_risk_decision_convenience_properties():
    assert _make_decision(decision="APPROVED").is_approved
    assert _make_decision(decision="REJECTED", approved_position=0.0).is_rejected
    assert _make_decision(decision="REDUCED", approved_position=3.0).is_reduced


def test_risk_decision_to_from_dict():
    from eigencapital.core.models.risk_check_result import RiskCheckResult as RCR
    from eigencapital.core.models.risk_decision import RiskDecision as RD
    checks = [_make_check(check_id=f"a_{_counter}"), _make_check(check_id=f"b_{_counter}")]
    original = _make_decision(risk_checks=checks)
    d = original.to_dict()
    RCR._registry.clear()
    RD._registry.clear()
    roundtrip = RD.from_dict(d)
    assert roundtrip.decision_id == original.decision_id
    assert roundtrip.decision == original.decision
    assert roundtrip.var == original.var
    assert len(roundtrip.risk_checks) == len(original.risk_checks)


def test_risk_decision_dict_consistency():
    rd = _make_decision()
    assert rd.to_dict() == rd.to_dict()
