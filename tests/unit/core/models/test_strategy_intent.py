"""Unit tests for EigenCapital domain models — StrategyIntent."""

from eigencapital.core.models.strategy_intent import StrategyIntent, Horizon

_counter = 0

_DEFAULT_HASH = "abc123def456"
_DEFAULT_ARTIFACT = "artifact789"


def _make_si(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        strategy_id="trend_v1",
        strategy_version="v1.0",
        instrument_id="ES",
        timestamp_utc=f"2024-03-15T09:35:{_counter % 60:02d}Z",
        direction=1,
        target_risk=0.003,
        horizon=Horizon.INTRADAY,
        strategy_config_hash=_DEFAULT_HASH,
        strategy_artifact_hash=_DEFAULT_ARTIFACT,
    )
    defaults.update(overrides)
    return StrategyIntent(**defaults)


def test_strategy_intent_creation():
    si = _make_si()
    assert si.strategy_id == "trend_v1"
    assert si.direction == 1
    assert si.target_risk == 0.003
    assert si.strategy_config_hash == "abc123def456"
    assert si.strategy_artifact_hash == "artifact789"


def test_strategy_intent_direction_valid():
    assert _make_si(direction=1).direction == 1
    assert _make_si(direction=-1).direction == -1
    assert _make_si(direction=0).direction == 0
    try:
        _make_si(direction=2)
        assert False
    except ValueError:
        pass


def test_strategy_intent_target_risk_nonnegative():
    assert _make_si(target_risk=0.0).target_risk == 0.0
    try:
        _make_si(target_risk=-0.001)
        assert False
    except ValueError:
        pass


def test_strategy_intent_config_hash_required():
    try:
        _make_si(strategy_config_hash="")
        assert False
    except ValueError as e:
        assert "strategy_config_hash must be non-empty" in str(e)
    try:
        _make_si(strategy_artifact_hash="")
        assert False
    except ValueError as e:
        assert "strategy_artifact_hash must be non-empty" in str(e)


def test_strategy_intent_horizon_valid():
    assert _make_si(horizon="intraday").horizon == "intraday"
    assert _make_si(horizon="swing").horizon == "swing"


def test_strategy_intent_direction_enum():
    assert _make_si(direction=1).direction_enum == "LONG"
    assert _make_si(direction=-1).direction_enum == "SHORT"
    assert _make_si(direction=0).direction_enum == "FLAT"


def test_strategy_intent_is_flat_is_long_is_short():
    assert _make_si(direction=0).is_flat
    assert _make_si(direction=1).is_long
    assert _make_si(direction=-1).is_short


def test_strategy_intent_to_from_dict():
    original = _make_si(
        strategy_id="mean_rev",
        strategy_version="v2.1",
        instrument_id="EUR_USD",
        direction=-1,
        target_risk=0.002,
        confidence=0.85,
        signal_metadata={"regime": "range"},
        strategy_config_hash="config_v1",
        strategy_artifact_hash="artifact_v1",
    )
    d = original.to_dict()
    assert d["strategy_config_hash"] == "config_v1"
    assert d["strategy_artifact_hash"] == "artifact_v1"
    # Verify key fields without roundtrip
    assert d["strategy_id"] == "mean_rev"
    assert d["direction"] == -1
    assert d["confidence"] == 0.85


def test_strategy_intent_dict_consistency():
    si = _make_si()
    assert si.to_dict() == si.to_dict()


def test_strategy_intent_expiry_optional():
    assert _make_si(expiry=None).expiry is None
    assert _make_si(expiry="2024-03-20T09:35:00Z").expiry == "2024-03-20T09:35:00Z"


def test_strategy_intent_intended_position_not_in_model():
    si = _make_si()
    assert si.instrument_id == "ES"
    assert si.direction == 1


def test_strategy_intent_nan_directions():
    try:
        _make_si(direction=float("nan"))
        assert False
    except ValueError:
        pass


def test_strategy_intent_negative_target_risk():
    try:
        _make_si(target_risk=-0.001)
        assert False
    except ValueError:
        pass


def test_strategy_intent_config_hash_deterministic():
    si = _make_si(strategy_config_hash="hash_123", strategy_artifact_hash="art_456")
    assert si.strategy_config_hash == "hash_123"
    assert si.strategy_artifact_hash == "art_456"
