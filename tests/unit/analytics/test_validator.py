"""Tests for the validation orchestrator."""

from eigencapital.analytics.validation.evidence_gate import EvidenceVerdict
from eigencapital.analytics.validation.validator import ValidationEngine


def _make_uptrend_equity(n: int = 500) -> list:
    """Create equity curve with uptrend and noise."""
    import random

    rng = random.Random(42)
    equity = [100_000.0]
    for i in range(n - 1):
        noise = rng.gauss(0, 0.008)
        equity.append(equity[-1] * (1 + 0.002 + noise))
    return equity


class TestValidationEngine:
    """Tests for the validation orchestrator."""

    def test_insufficient_data(self):
        """Test validation with insufficient data."""
        engine = ValidationEngine()
        result = engine.validate(equity_curve=[100, 101])
        assert result.verdict == EvidenceVerdict.REJECTED

    def test_basic_validation(self):
        """Test basic validation run."""
        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            walk_forward_purge=5,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_uptrend_equity(300)
        result = engine.validate(
            experiment_id="TEST-001",
            equity_curve=equity,
        )
        assert result.experiment_id == "TEST-001"
        assert result.baseline_metrics is not None
        assert result.walk_forward is not None
        assert result.bootstrap_iid is not None
        assert result.permutation is not None
        assert result.verdict in [
            EvidenceVerdict.CANDIDATE,
            EvidenceVerdict.VALIDATED,
            EvidenceVerdict.REJECTED,
            EvidenceVerdict.INCONCLUSIVE,
        ]

    def test_with_instrument_returns(self):
        """Test validation with per-instrument returns."""
        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_uptrend_equity(300)
        instrument_returns = {
            "ES": [0.002 + (i % 3 - 1) * 0.001 for i in range(100)],
            "NQ": [0.001 + (i % 5 - 2) * 0.001 for i in range(100)],
        }
        result = engine.validate(
            experiment_id="TEST-002",
            equity_curve=equity,
            instrument_returns=instrument_returns,
        )
        assert result.universe is not None
        assert result.universe.robustness_score >= 0

    def test_with_regime_returns(self):
        """Test validation with regime returns."""
        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_uptrend_equity(300)
        import random

        rng = random.Random(42)
        regime_returns = {
            "trending": [0.005 + rng.gauss(0, 0.005) for _ in range(100)],
            "choppy": [0.001 + rng.gauss(0, 0.005) for _ in range(100)],
        }
        result = engine.validate(
            experiment_id="TEST-003",
            equity_curve=equity,
            regime_returns=regime_returns,
        )
        assert result.regime is not None

    def test_serialization(self):
        """Test deterministic serialization."""
        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_uptrend_equity(300)
        result = engine.validate(experiment_id="TEST-004", equity_curve=equity)
        d = result.to_dict()
        assert "experiment_id" in d
        assert "verdict" in d
        assert "baseline_metrics" in d
        assert "walk_forward" in d
