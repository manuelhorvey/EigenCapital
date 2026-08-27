"""Tests for universe perturbation and concentration analysis."""

from eigencapital.analytics.validation.universe import (
    compute_concentration,
    universe_perturbation,
)


class TestConcentration:
    """Tests for concentration metrics."""

    def test_equal_distribution(self):
        """Test with equal instrument contributions."""
        result = compute_concentration(
            {
                "ES": [0.01, 0.01, 0.01],
                "NQ": [0.01, 0.01, 0.01],
                "GC": [0.01, 0.01, 0.01],
            }
        )
        assert result.herfindahl_index < 0.5
        assert not result.concentration_warning

    def test_concentrated(self):
        """Test with concentrated distribution."""
        result = compute_concentration(
            {
                "ES": [0.10, 0.10, 0.10],
                "NQ": [0.001, 0.001, 0.001],
            }
        )
        assert result.concentration_warning
        assert result.most_concentrated_instrument == "ES"

    def test_empty(self):
        """Test with empty data."""
        result = compute_concentration({})
        assert result.herfindahl_index == 0.0


class TestUniversePerturbation:
    """Tests for universe perturbation analysis."""

    def test_basic(self):
        """Test basic universe perturbation."""
        result = universe_perturbation(
            {
                "ES": [0.01, 0.02, 0.01, 0.02],
                "NQ": [0.005, 0.01, 0.005, 0.01],
            }
        )
        assert result.robustness_score >= 0
        assert len(result.exclusion_results) == 2

    def test_empty(self):
        """Test with empty data."""
        result = universe_perturbation({})
        assert result.robustness_score == 100.0

    def test_single_instrument(self):
        """Test with single instrument."""
        result = universe_perturbation(
            {
                "ES": [0.01, 0.02, 0.03],
            }
        )
        assert len(result.exclusion_results) == 1
        # Removing only instrument leaves empty → Sharpe 0
        assert result.exclusion_results["ES"]["sharpe_without"] == 0.0

    def test_serialization(self):
        """Test deterministic serialization."""
        result = universe_perturbation({"ES": [0.01, 0.02], "NQ": [0.005, 0.01]})
        d = result.to_dict()
        assert "concentration" in d
        assert "robustness_score" in d
