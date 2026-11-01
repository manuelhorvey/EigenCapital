"""Tests for Probability of Backtest Overfitting (CSCV)."""

import pytest

from eigencapital.analytics.validation.pbo import compute_pbo


def _constant_matrix(n_periods: int, means: list[float]) -> list[list[float]]:
    return [[mean for mean in means] for _ in range(n_periods)]


class TestPBOInsufficient:
    """Inputs that cannot support a PBO estimate must not produce one."""

    def test_insufficient_experiments(self):
        result = compute_pbo(
            [
                {"in_sample_sharpe": 2.0, "out_of_sample_sharpe": 0.3},
                {"in_sample_sharpe": 1.5, "out_of_sample_sharpe": 1.2},
            ]
        )
        assert not result.sufficient_experiments
        assert "INSUFFICIENT" in result.message

    def test_summary_input_is_unsupported(self):
        """A single IS/OOS split cannot estimate PBO."""
        candidates = [
            {"in_sample_sharpe": 2.0 + i * 0.1, "out_of_sample_sharpe": 1.5 - i * 0.2}
            for i in range(15)
        ]
        result = compute_pbo(candidates)
        assert not result.sufficient_experiments
        assert result.method == "UNSUPPORTED_INPUT"
        assert "no value is reported" in result.message
        assert result.total_partitions == 0


class TestCSCVKnownAnswers:
    """Hand-reasoned CSCV cases."""

    def test_no_overfitting_when_best_in_sample_is_best_out_of_sample(self):
        """The old implementation returned 1.0 here; CSCV must return 0.0."""
        matrix = _constant_matrix(4, [3.0, 2.0, 1.0])
        result = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        assert result.sufficient_experiments
        assert result.method == "CSCV"
        assert result.total_partitions == 2
        assert result.overfit_count == 0
        assert result.pbo == 0.0

    def test_full_overfitting_when_rankings_reverse(self):
        """Each half is best in-sample and worst out-of-sample."""
        matrix = [
            [3.0, 0.0],
            [3.0, 0.0],
            [0.0, 3.0],
            [0.0, 3.0],
        ]
        result = compute_pbo(
            performance_matrix=matrix,
            min_candidates=2,
            n_blocks=2,
            statistic="mean",
        )
        assert result.total_partitions == 2
        assert result.overfit_count == 2
        assert result.pbo == 1.0

    def test_default_blocks_uses_available_history(self):
        matrix = _constant_matrix(4, [3.0, 2.0, 1.0])
        result = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            statistic="mean",
        )
        assert result.n_blocks == 4
        assert result.total_partitions == 6
        assert result.pbo == 0.0


class TestCSCVMechanics:
    """Validation, determinism, and input forms."""

    def test_candidate_return_series_are_accepted(self):
        matrix = _constant_matrix(6, [3.0, 2.0, 1.0])
        candidates = [{"returns": [row[column] for row in matrix]} for column in range(3)]
        result = compute_pbo(
            candidates,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        expected = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        assert result.pbo == expected.pbo
        assert result.total_partitions == expected.total_partitions

    def test_deterministic(self):
        matrix = [
            [3.0, 0.0, 1.0],
            [2.0, 1.0, 0.0],
            [0.0, 2.0, 1.0],
            [0.0, 3.0, 1.0],
        ]
        first = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        second = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        assert first == second

    def test_partition_cap_is_deterministic(self):
        matrix = _constant_matrix(32, [3.0, 2.0])
        result = compute_pbo(
            performance_matrix=matrix,
            min_candidates=2,
            n_blocks=16,
            n_partitions=10,
            statistic="mean",
        )
        assert result.total_partitions == 10
        assert result.pbo == 0.0

    def test_ragged_candidate_series_rejected(self):
        with pytest.raises(ValueError, match="same length"):
            compute_pbo(
                [{"returns": [1.0, 2.0]}, {"returns": [1.0]}],
                min_candidates=2,
            )

    def test_ragged_matrix_rejected(self):
        with pytest.raises(ValueError, match="expected 2"):
            compute_pbo(
                performance_matrix=[[1.0, 2.0], [3.0]],
                min_candidates=2,
            )

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), "x", None])
    def test_invalid_matrix_values_rejected(self, bad_value):
        with pytest.raises(ValueError):
            compute_pbo(
                performance_matrix=[[1.0, bad_value], [2.0, 3.0]],
                min_candidates=2,
            )

    def test_odd_blocks_rejected(self):
        with pytest.raises(ValueError, match="even"):
            compute_pbo(
                performance_matrix=_constant_matrix(6, [1.0, 0.0]),
                min_candidates=2,
                n_blocks=3,
            )

    def test_blocks_cannot_exceed_periods(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            compute_pbo(
                performance_matrix=_constant_matrix(4, [1.0, 0.0]),
                min_candidates=2,
                n_blocks=6,
            )

    def test_unknown_statistic_rejected(self):
        with pytest.raises(ValueError, match="Unknown statistic"):
            compute_pbo(
                performance_matrix=_constant_matrix(4, [1.0, 0.0]),
                min_candidates=2,
                n_blocks=2,
                statistic="sortino",
            )


class TestPBOSerialization:
    def test_serialization_includes_method_and_blocks(self):
        matrix = _constant_matrix(4, [3.0, 2.0, 1.0])
        result = compute_pbo(
            performance_matrix=matrix,
            min_candidates=3,
            n_blocks=2,
            statistic="mean",
        )
        data = result.to_dict()
        assert data["method"] == "CSCV"
        assert data["n_blocks"] == 2
        assert 0.0 <= data["pbo"] <= 1.0
        assert data["sufficient_experiments"] is True
