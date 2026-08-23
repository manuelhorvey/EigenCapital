"""Unit tests for EigenCapital domain models — RiskCheckResult."""

import math
from eigencapital.core.models.risk_check_result import RiskCheckResult, RISK_CHECK_IDS

_counter = 0


def _make_check(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        check_id=f"check_{_counter}",
        status="PASS",
        observed=0.84,
        limit=2.0,
        unit="x",
        message="Gross leverage within limit",
    )
    defaults.update(overrides)
    return RiskCheckResult(**defaults)


def test_risk_check_creation():
    rc = _make_check(check_id="max_leverage")
    assert rc.check_id == "max_leverage"
    assert rc.status == "PASS"
    assert rc.observed == 0.84
    assert rc.limit == 2.0
    assert rc.unit == "x"
    assert rc.version == "v1"


def test_risk_check_status_validation():
    for status in ("PASS", "WARN", "FAIL"):
        rc = _make_check(status=status)
        assert rc.status == status
    try:
        _make_check(status="UNKNOWN")
        assert False
    except ValueError as e:
        assert "Invalid risk check status" in str(e)


def test_risk_check_passed_failed_warned():
    assert _make_check(status="PASS").passed
    assert _make_check(status="FAIL").failed
    assert _make_check(status="WARN").warned


def test_risk_check_observed_finite():
    _make_check(observed=0.5)
    try:
        _make_check(observed=float("nan"))
        assert False
    except ValueError:
        pass
    try:
        _make_check(observed=float("inf"))
        assert False
    except ValueError:
        pass


def test_risk_check_limit_finite():
    _make_check(limit=2.0)
    try:
        _make_check(limit=float("nan"))
        assert False
    except ValueError:
        pass


def test_risk_check_required_fields():
    try:
        _make_check(check_id="")
        assert False
    except ValueError as e:
        assert "check_id must be non-empty" in str(e)
    try:
        _make_check(unit="")
        assert False
    except ValueError as e:
        assert "unit must be non-empty" in str(e)
    try:
        _make_check(message="")
        assert False
    except ValueError as e:
        assert "message must be non-empty" in str(e)


def test_risk_check_to_from_dict():
    from eigencapital.core.models.risk_check_result import RiskCheckResult as RCR
    original = _make_check(status="WARN", observed=1.5, limit=2.0)
    d = original.to_dict()
    RCR._registry.clear()
    roundtrip = RCR.from_dict(d)
    assert roundtrip.check_id == original.check_id
    assert roundtrip.status == original.status
    assert roundtrip.observed == original.observed


def test_risk_check_dict_consistency():
    rc = _make_check()
    assert rc.to_dict() == rc.to_dict()


def test_risk_check_ids_set():
    expected = {
        "max_position", "gross_exposure", "net_exposure",
        "leverage", "drawdown", "daily_loss", "weekly_loss",
        "correlation", "asset_class", "liquidity",
        "volatility_shock", "concentration",
    }
    assert RISK_CHECK_IDS == expected
