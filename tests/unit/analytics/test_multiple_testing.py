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


class TestHolmBHCorrectness:
    """Known-answer and invariant tests for the step-down/step-up algorithms."""

    def test_holm_hand_calculated(self):
        """Holm([0.001, 0.04, 0.03]) = [0.003, 0.06, 0.06]."""
        assert holm([0.001, 0.04, 0.03]) == pytest.approx(
            [0.003, 0.06, 0.06], abs=1e-12
        )

    def test_holm_preserves_caller_order(self):
        """Unsorted input maps adjusted values back to their own indices."""
        adjusted = holm([0.04, 0.001, 0.03])
        assert adjusted == pytest.approx([0.06, 0.003, 0.06], abs=1e-12)

    def test_holm_cumulative_maximum(self):
        """Later ranks cannot fall below an earlier adjusted value."""
        adjusted = holm([0.01, 0.02, 0.03, 0.04, 0.05])
        assert adjusted == pytest.approx(
            [0.05, 0.08, 0.09, 0.09, 0.09], abs=1e-12
        )

    def test_bh_hand_calculated(self):
        """BH([0.001, 0.04, 0.03]) = [0.003, 0.04, 0.04]."""
        assert benjamini_hochberg([0.001, 0.04, 0.03]) == pytest.approx(
            [0.003, 0.04, 0.04], abs=1e-12
        )

    def test_bh_preserves_caller_order(self):
        """Unsorted input maps adjusted values back to their own indices."""
        adjusted = benjamini_hochberg([0.04, 0.001, 0.03])
        assert adjusted == pytest.approx([0.04, 0.003, 0.04], abs=1e-12)

    def test_bh_cumulative_minimum(self):
        """From the largest p-value down, adjusted values cannot increase."""
        adjusted = benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05])
        assert adjusted == pytest.approx([0.05] * 5, abs=1e-12)

    def test_holm_rejects_only_step_down_hypotheses(self):
        """p=0.03 is retained by correct Holm at alpha=0.05."""
        result = multiple_testing_correction(
            [0.001, 0.04, 0.03], method="holm", alpha=0.05
        )
        assert result.rejected == [True, False, False]

    def test_bh_rejects_all_three_in_example(self):
        """Correct BH adjusted values are all <= 0.05 in this example."""
        result = multiple_testing_correction(
            [0.001, 0.04, 0.03], method="benjamini-hochberg", alpha=0.05
        )
        assert result.rejected == [True, True, True]

    def test_holm_fwer_bound(self):
        """If the smallest p exceeds alpha/n, Holm rejects nothing."""
        n = 5
        alpha = 0.05
        p_values = [alpha / n + 1e-9] * n
        assert holm(p_values) == pytest.approx([p_values[0] * n] * n, abs=1e-9)
        assert all(p > alpha for p in holm(p_values))

    def test_bh_fdr_bound(self):
        """If every p_(k) > k*alpha/n, BH rejects nothing at alpha."""
        alpha = 0.05
        p_values = [0.02, 0.03, 0.04, 0.06, 0.08]
        n = len(p_values)
        assert all(p > (k + 1) * alpha / n for k, p in enumerate(p_values))
        assert all(p > alpha for p in benjamini_hochberg(p_values))

    def test_bh_never_more_conservative_than_holm(self):
        """Pointwise, BH adjusted p-values are <= Holm adjusted p-values."""
        p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        bh = benjamini_hochberg(p_values)
        hm = holm(p_values)
        assert all(b <= h + 1e-12 for b, h in zip(bh, hm))

    def test_ties_receive_equal_adjusted_values(self):
        """Tied raw p-values must remain tied after correction."""
        for method in (holm, benjamini_hochberg):
            adjusted = method([0.02, 0.02, 0.5])
            assert adjusted[0] == pytest.approx(adjusted[1], abs=1e-12)

    def test_input_list_is_not_mutated(self):
        """Correction must not reorder or alter the caller's list."""
        p_values = [0.04, 0.001, 0.03]
        original = list(p_values)
        holm(p_values)
        benjamini_hochberg(p_values)
        bonferroni(p_values)
        assert p_values == original

    @pytest.mark.parametrize(
        "bad_value",
        [-0.001, 1.001, float("nan"), float("inf"), float("-inf")],
    )
    def test_invalid_p_values_fail_closed(self, bad_value):
        """Out-of-range or non-finite p-values raise instead of being corrected."""
        for method in (holm, benjamini_hochberg, bonferroni):
            with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
                method([0.01, bad_value])

    def test_non_numeric_p_value_fails_closed(self):
        """A non-numeric entry is rejected with an explicit error."""
        with pytest.raises(ValueError, match="not numeric"):
            holm([0.01, None])  # type: ignore[list-item]
