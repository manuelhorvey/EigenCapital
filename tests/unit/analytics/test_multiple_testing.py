"""Tests for multiple-testing correction."""

import pytest

from eigencapital.analytics.validation.multiple_testing import (
    benjamini_hochberg,
    bonferroni,
    holm,
    multiple_testing_correction,
)


class TestMultipleTesting:
    """Tests for multiple-testing correction methods."""

    def test_bonferroni_basic(self):
        """Test Bonferroni correction."""
        adjusted = bonferroni([0.01, 0.04, 0.03], alpha=0.05)
        assert adjusted[0] == pytest.approx(0.03)
        assert adjusted[1] == pytest.approx(0.12)
        assert adjusted[2] == pytest.approx(0.09)

    def test_bonferroni_caps_at_1(self):
        """Test that Bonferroni caps adjusted p-values at 1.0."""
        adjusted = bonferroni([0.5, 0.6])
        assert all(p <= 1.0 for p in adjusted)

    def test_holm_basic(self):
        """Test Holm correction."""
        adjusted = holm([0.01, 0.04, 0.03])
        assert all(0 <= p <= 1 for p in adjusted)
        # Holm should be less conservative than Bonferroni
        bonf = bonferroni([0.01, 0.04, 0.03])
        assert adjusted[0] <= bonf[0] + 0.001

    def test_bh_basic(self):
        """Test Benjamini-Hochberg correction."""
        adjusted = benjamini_hochberg([0.01, 0.04, 0.03, 0.10, 0.50])
        assert all(0 <= p <= 1 for p in adjusted)
        assert len(adjusted) == 5

    def test_empty_p_values(self):
        """Test with empty p-values."""
        result = multiple_testing_correction([], method="bonferroni")
        assert result.n_tests == 0
        assert result.adjusted_p_values == []

    def test_single_p_value(self):
        """Test with single p-value."""
        result = multiple_testing_correction([0.03], method="bonferroni")
        assert result.n_tests == 1
        assert result.adjusted_p_values[0] == pytest.approx(0.03)

    def test_rejection_logic(self):
        """Test rejection logic at alpha=0.05."""
        result = multiple_testing_correction(
            [0.01, 0.04, 0.10],
            method="bonferroni",
            alpha=0.05,
        )
        # 0.01*3=0.03 < 0.05, 0.04*3=0.12 > 0.05, 0.10*3=0.30 > 0.05
        assert result.rejected[0] is True
        assert result.rejected[1] is False
        assert result.rejected[2] is False

    def test_serialization(self):
        """Test deterministic serialization."""
        result = multiple_testing_correction([0.01, 0.04, 0.03])
        d = result.to_dict()
        assert "method" in d
        assert "adjusted_p_values" in d
        assert "n_rejected" in d

    def test_invalid_method_raises(self):
        """Test that invalid method raises ValueError."""
        with pytest.raises(ValueError, match="Unknown correction method"):
            multiple_testing_correction([0.05], method="invalid")
