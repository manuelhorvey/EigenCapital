"""Adversarial tests for Phase 1I-G Multi-Strategy / Alpha Combination.

Tests cover:
- AlphaCandidate creation and eligibility gate
- Return stream extraction and metrics
- Dependence analysis (Pearson, Spearman, downside)
- 1/N equal-weight portfolio
- Risk-scaled portfolio
- Portfolio return combination
- Portfolio metrics computation
- Edge cases: empty streams, single stream, identical returns
"""

import pytest

from eigencapital.research.combination.candidate import (
    AlphaCandidate,
    EligibilityStatus,
)
from eigencapital.research.combination.returns import (
    ReturnStream,
    compute_pearson_correlation,
    compute_spearman_correlation,
    compute_downside_correlation,
    build_dependence_matrix,
)
from eigencapital.research.combination.portfolio import (
    PortfolioResult,
    compute_equal_weight,
    compute_risk_scaled,
    combine_returns,
    compute_portfolio_metrics,
)
from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────


def _make_streams(n: int = 3, length: int = 100, seed: int = 42):
    """Create n correlated return streams."""
    import random

    rng = random.Random(seed)
    streams = []
    for i in range(n):
        returns = [rng.gauss(0.0005, 0.01) for _ in range(length)]
        timestamps = [f"2025-01-{15 + j:02d}T10:00:00Z" for j in range(length)]
        streams.append(
            ReturnStream(
                stream_id=f"RS-{i}",
                candidate_id=f"AC-{i}",
                returns=tuple(returns),
                timestamps=tuple(timestamps),
            )
        )
    return streams


def _make_execution_record(
    exec_id: str = "EXEC-001",
    hyp_id: str = "HYP-001",
    verdict: str = "CANDIDATE",
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=exec_id,
        hypothesis_id=hyp_id,
        hypothesis_hash="abc",
        experiment_id="EXP-001",
        experiment_hash="def",
        trial_group_id="TG-001",
        trial_index=1,
        status=ExecutionStatus.COMPLETED,
        evidence_gate_verdict=verdict,
    )


# ═══════════════════════════════════════════════
#  ALPHA CANDIDATE
# ═══════════════════════════════════════════════


class TestAlphaCandidate:
    def test_basic_creation(self):
        candidate = AlphaCandidate(
            candidate_id="AC-001",
            hypothesis_id="HYP-001",
            execution_record_id="EXEC-001",
            evidence_verdict="CANDIDATE",
            eligibility_status=EligibilityStatus.ELIGIBLE,
            eligibility_reason="CANDIDATE verdict is eligible",
        )
        assert candidate.is_eligible

    def test_from_execution_record_candidate(self):
        record = _make_execution_record(verdict="CANDIDATE")
        candidate = AlphaCandidate.from_execution_record("AC-001", record)
        assert candidate.is_eligible
        assert candidate.evidence_verdict == "CANDIDATE"

    def test_from_execution_record_rejected(self):
        record = _make_execution_record(verdict="REJECTED")
        candidate = AlphaCandidate.from_execution_record("AC-001", record)
        assert not candidate.is_eligible
        assert candidate.eligibility_status == EligibilityStatus.EXCLUDED

    def test_from_execution_record_inconclusive(self):
        record = _make_execution_record(verdict="INCONCLUSIVE")
        candidate = AlphaCandidate.from_execution_record("AC-001", record)
        assert not candidate.is_eligible

    def test_from_execution_record_validated(self):
        record = _make_execution_record(verdict="VALIDATED")
        candidate = AlphaCandidate.from_execution_record("AC-001", record)
        assert candidate.is_eligible

    def test_missing_candidate_id(self):
        with pytest.raises(ValueError, match="candidate_id"):
            AlphaCandidate(
                candidate_id="",
                hypothesis_id="HYP-001",
                execution_record_id="EXEC-001",
                evidence_verdict="CANDIDATE",
            )

    def test_deterministic_serialization(self):
        candidate = AlphaCandidate(
            candidate_id="AC-001",
            hypothesis_id="HYP-001",
            execution_record_id="EXEC-001",
            evidence_verdict="CANDIDATE",
        )
        d1 = candidate.to_dict()
        d2 = candidate.to_dict()
        assert d1 == d2

    def test_serialization_roundtrip(self):
        candidate = AlphaCandidate(
            candidate_id="AC-001",
            hypothesis_id="HYP-001",
            execution_record_id="EXEC-001",
            evidence_verdict="CANDIDATE",
            eligibility_status=EligibilityStatus.ELIGIBLE,
        )
        d = candidate.to_dict()
        c2 = AlphaCandidate.from_dict(d)
        assert c2.candidate_id == candidate.candidate_id
        assert c2.is_eligible

    def test_hash_deterministic(self):
        candidate = AlphaCandidate(
            candidate_id="AC-001",
            hypothesis_id="HYP-001",
            execution_record_id="EXEC-001",
            evidence_verdict="CANDIDATE",
        )
        h1 = candidate.compute_hash()
        h2 = candidate.compute_hash()
        assert h1 == h2
        assert len(h1) == 64


# ═══════════════════════════════════════════════
#  RETURN STREAM
# ═══════════════════════════════════════════════


class TestReturnStream:
    def test_basic_creation(self):
        stream = ReturnStream(
            stream_id="RS-001",
            candidate_id="AC-001",
            returns=(0.01, -0.005, 0.02),
            timestamps=("t1", "t2", "t3"),
        )
        assert stream.length == 3
        # mean of (0.01, -0.005, 0.02) = 0.025/3 = 0.00833...
        assert stream.mean_return == pytest.approx(0.025 / 3, abs=1e-10)

    def test_mismatched_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            ReturnStream(
                stream_id="RS-001",
                candidate_id="AC-001",
                returns=(0.01, -0.005),
                timestamps=("t1",),
            )

    def test_volatility(self):
        stream = ReturnStream(
            stream_id="RS-001",
            candidate_id="AC-001",
            returns=(0.01, -0.01, 0.01, -0.01),
            timestamps=("t1", "t2", "t3", "t4"),
        )
        assert stream.volatility > 0

    def test_sharpe(self):
        stream = ReturnStream(
            stream_id="RS-001",
            candidate_id="AC-001",
            returns=(0.01, 0.01, 0.01, 0.01),
            timestamps=("t1", "t2", "t3", "t4"),
        )
        # Constant positive returns → zero vol → zero Sharpe
        assert stream.sharpe == 0.0

    def test_cumulative_return(self):
        stream = ReturnStream(
            stream_id="RS-001",
            candidate_id="AC-001",
            returns=(0.1, -0.05),
            timestamps=("t1", "t2"),
        )
        # (1.1 * 0.95) - 1 = 0.045
        assert stream.cumulative_return == pytest.approx(0.045, abs=1e-10)

    def test_empty_stream(self):
        stream = ReturnStream(
            stream_id="RS-001",
            candidate_id="AC-001",
            returns=(),
            timestamps=(),
        )
        assert stream.length == 0
        assert stream.mean_return == 0.0


# ═══════════════════════════════════════════════
#  CORRELATION
# ═══════════════════════════════════════════════


class TestCorrelation:
    def test_pearson_perfect(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        assert compute_pearson_correlation(x, y) == pytest.approx(1.0)

    def test_pearson_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert compute_pearson_correlation(x, y) == pytest.approx(-1.0)

    def test_pearson_zero(self):
        x = [1.0, -1.0, 1.0, -1.0]
        y = [1.0, 1.0, -1.0, -1.0]
        assert compute_pearson_correlation(x, y) == pytest.approx(0.0)

    def test_pearson_insufficient_data(self):
        assert compute_pearson_correlation([1.0], [2.0]) == 0.0

    def test_spearman_monotonic(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert compute_spearman_correlation(x, y) == pytest.approx(1.0)

    def test_downside_correlation(self):
        x = [0.01, -0.02, 0.03, -0.01]
        y = [0.02, -0.01, 0.01, -0.02]
        dc = compute_downside_correlation(x, y, threshold=0.0)
        assert isinstance(dc, float)

    def test_dependence_matrix(self):
        streams = _make_streams(3, length=50)
        matrix = build_dependence_matrix(streams)
        assert len(matrix.stream_ids) == 3
        assert matrix.pearson[0][0] == pytest.approx(1.0)
        assert matrix.pearson[0][1] == matrix.pearson[1][0]  # Symmetric


# ═══════════════════════════════════════════════
#  PORTFOLIO CONSTRUCTORS
# ═══════════════════════════════════════════════


class TestPortfolioConstructors:
    def test_equal_weight(self):
        streams = _make_streams(3)
        weights = compute_equal_weight(streams)
        assert weights.weight_sum == pytest.approx(1.0)
        assert weights.num_constituents == 3
        assert weights.method == "equal_weight"

    def test_equal_weight_empty(self):
        weights = compute_equal_weight([])
        assert weights.num_constituents == 0

    def test_risk_scaled(self):
        streams = _make_streams(3, length=100)
        weights = compute_risk_scaled(streams)
        assert weights.weight_sum == pytest.approx(1.0)
        assert weights.method == "risk_scaled"

    def test_risk_scaled_concentration(self):
        streams = _make_streams(3, length=100)
        weights = compute_risk_scaled(streams)
        # Risk-scaled should be less concentrated than single asset
        assert weights.concentration < 1.0

    def test_equal_weight_concentration(self):
        streams = _make_streams(4)
        weights = compute_equal_weight(streams)
        # Equal weight: HHI = 1/N
        assert weights.concentration == pytest.approx(0.25)

    def test_weights_serialization(self):
        weights = compute_equal_weight(_make_streams(3))
        d = weights.to_dict()
        assert d["method"] == "equal_weight"
        assert len(d["weights"]) == 3


# ═══════════════════════════════════════════════
#  PORTFOLIO COMBINATION
# ═══════════════════════════════════════════════


class TestPortfolioCombination:
    def test_combine_returns(self):
        streams = _make_streams(2, length=50)
        weights = compute_equal_weight(streams)
        combined, timestamps = combine_returns(streams, weights)
        assert len(combined) == 50
        assert len(timestamps) == 50

    def test_combine_returns_empty(self):
        combined, timestamps = combine_returns([], compute_equal_weight([]))
        assert len(combined) == 0

    def test_combine_returns_deterministic(self):
        streams = _make_streams(2, length=50)
        weights = compute_equal_weight(streams)
        c1, _ = combine_returns(streams, weights)
        c2, _ = combine_returns(streams, weights)
        assert c1 == c2

    def test_portfolio_metrics(self):
        returns = tuple([0.01, -0.005, 0.02, -0.01, 0.015] * 20)
        metrics = compute_portfolio_metrics(returns)
        assert "sharpe" in metrics
        assert "max_drawdown" in metrics
        assert "cagr" in metrics
        assert metrics["num_periods"] == 100

    def test_portfolio_metrics_empty(self):
        metrics = compute_portfolio_metrics(())
        assert metrics == {}

    def test_equal_weight_vs_individual(self):
        """Equal weight should have lower vol than individual (diversification)."""
        streams = _make_streams(3, length=200, seed=42)
        weights = compute_equal_weight(streams)
        combined, _ = combine_returns(streams, weights)
        metrics = compute_portfolio_metrics(combined)

        # Portfolio vol should be lower than average individual vol
        avg_vol = sum(s.volatility for s in streams) / len(streams)
        assert metrics["volatility"] < avg_vol

    def test_result_serialization(self):
        streams = _make_streams(2, length=50)
        weights = compute_equal_weight(streams)
        combined, timestamps = combine_returns(streams, weights)
        metrics = compute_portfolio_metrics(combined)

        result = PortfolioResult(
            experiment_id="PE-001",
            method="equal_weight",
            constituents=("RS-0", "RS-1"),
            weights_history=(weights,),
            returns=combined,
            timestamps=timestamps,
            metrics=metrics,
        )
        d = result.to_dict()
        assert d["experiment_id"] == "PE-001"
        assert len(d["returns"]) == 50


# ═══════════════════════════════════════════════
#  ADVERSARIAL — PROPERTIES
# ═══════════════════════════════════════════════


class TestProperties:
    def test_correlation_bounds(self):
        streams = _make_streams(3, length=100)
        matrix = build_dependence_matrix(streams)
        for i in range(len(matrix.stream_ids)):
            for j in range(len(matrix.stream_ids)):
                assert -1.0 <= matrix.pearson[i][j] <= 1.0
                assert -1.0 <= matrix.spearman[i][j] <= 1.0

    def test_weights_sum_to_one(self):
        for n in [1, 2, 5, 10]:
            streams = _make_streams(n)
            w = compute_equal_weight(streams)
            assert w.weight_sum == pytest.approx(1.0)

    def test_diversification_benefit(self):
        """Combining uncorrelated streams should reduce volatility."""
        import random

        rng = random.Random(99)
        streams = []
        for i in range(5):
            returns = [rng.gauss(0.0005, 0.01) for _ in range(200)]
            timestamps = [f"2025-01-{15 + j:02d}T10:00:00Z" for j in range(200)]
            streams.append(
                ReturnStream(
                    stream_id=f"RS-{i}",
                    candidate_id=f"AC-{i}",
                    returns=tuple(returns),
                    timestamps=tuple(timestamps),
                )
            )

        weights = compute_equal_weight(streams)
        combined, _ = combine_returns(streams, weights)
        portfolio_vol = compute_portfolio_metrics(combined)["volatility"]

        avg_vol = sum(s.volatility for s in streams) / len(streams)
        assert portfolio_vol < avg_vol
