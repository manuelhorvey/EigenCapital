"""Unit tests for EigenCapital domain models — DecisionSnapshot."""

from eigencapital.core.models.strategy_intent import StrategyIntent, Horizon
from eigencapital.core.models.risk_check_result import RiskCheckResult
from eigencapital.core.models.risk_decision import RiskDecision
from eigencapital.core.models.decision_snapshot import DecisionSnapshot

_counter = 0


def _make_risk_decision():
    global _counter
    _counter += 1
    return RiskDecision(
        decision_id=f"RD_{_counter}",
        timestamp_utc="2024-03-15T09:35:01Z",
        instrument_id="ES",
        intended_position=5.0,
        approved_position=5.0,
        decision="APPROVED",
        reason="Within all limits",
        var=1250.0,
        var_method="gaussian_99",
        risk_checks=[
            RiskCheckResult(
                check_id=f"chk_{_counter}",
                status="PASS",
                observed=0.84,
                limit=2.0,
                unit="x",
                message="OK",
            )
        ],
        decision_snapshot_id="",
    )


def _make_signal():
    global _counter
    _counter += 1
    return StrategyIntent(
        strategy_id=f"trend_{_counter}",
        strategy_version="v1.0",
        instrument_id="ES",
        timestamp_utc=f"2024-03-15T09:35:{_counter % 60:02d}Z",
        direction=1,
        target_risk=0.003,
        horizon=Horizon.INTRADAY,
        strategy_config_hash=f"cfg_{_counter}",
        strategy_artifact_hash=f"art_{_counter}",
    )


def _make_snapshot(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        snapshot_id=f"DS_{_counter}",
        signal_timestamp_utc=f"2024-03-15T09:35:{_counter % 60:02d}Z",
        risk_decision_timestamp_utc="2024-03-15T09:35:01Z",
        execution_timestamp_utc="2024-03-15T09:35:03Z",
        strategy_id="trend_v1",
        strategy_version="v1.0",
        strategy_config_hash="config_abc123",
        strategy_artifact_hash="artifact_def456",
        provenance_hash="prov_ghi789",
        instrument_id="ES",
        signal=_make_signal(),
        risk_state=_make_risk_decision(),
        risk_decision_reason="Within all limits",
        execution_context="PAPER",
        git_commit="abc123def456789",
        dataset_version="equities_daily_v3",
    )
    defaults.update(overrides)
    return DecisionSnapshot(**defaults)


def test_snapshot_creation():
    ds = _make_snapshot()
    assert ds.strategy_config_hash == "config_abc123"
    assert ds.strategy_artifact_hash == "artifact_def456"
    assert ds.provenance_hash == "prov_ghi789"


def test_snapshot_three_timestamps():
    ds = _make_snapshot(
        signal_timestamp_utc="2024-03-15T09:30:00Z",
        risk_decision_timestamp_utc="2024-03-15T09:30:01Z",
        execution_timestamp_utc="2024-03-15T09:30:03Z",
    )
    assert ds.signal_timestamp_utc == "2024-03-15T09:30:00Z"
    assert ds.execution_timestamp_utc == "2024-03-15T09:30:03Z"


def test_snapshot_three_hashes():
    ds = _make_snapshot(
        strategy_config_hash="c1", strategy_artifact_hash="a1", provenance_hash="p1"
    )
    assert ds.strategy_config_hash == "c1"
    assert ds.strategy_artifact_hash == "a1"
    assert ds.provenance_hash == "p1"
    d = ds.to_dict()
    assert "strategy_config_hash" in d
    assert "strategy_artifact_hash" in d
    assert "provenance_hash" in d


def test_snapshot_hash_required():
    for field, val in [
        ("strategy_config_hash", ""),
        ("strategy_artifact_hash", ""),
        ("provenance_hash", ""),
    ]:
        try:
            _make_snapshot(**{field: val})
            assert False
        except ValueError:
            pass


def test_snapshot_execution_context():
    for ctx in ("PAPER", "LIVE", "BACKTEST"):
        ds = _make_snapshot(execution_context=ctx)
        assert ds.execution_context == ctx
    try:
        _make_snapshot(execution_context="PRODUCTION")
        assert False
    except ValueError:
        pass


def test_snapshot_convenience_properties():
    ds = _make_snapshot()
    assert ds.is_approved
    assert not ds.is_rejected


def test_snapshot_to_dict():
    ds = _make_snapshot()
    d = ds.to_dict()
    assert isinstance(d, dict)
    assert "strategy_config_hash" in d
    assert "provenance_hash" in d


def test_snapshot_summary():
    ds = _make_snapshot()
    s = ds.summary
    assert "APPROVED" in s
    assert "ES" in s
