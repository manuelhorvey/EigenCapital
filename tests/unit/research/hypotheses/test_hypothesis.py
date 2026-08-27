"""Unit tests for Hypothesis model."""

import pytest

from eigencapital.research.hypotheses.hypothesis import Hypothesis


def _make_hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="HYP-000001",
        claim="Assets exhibiting X tend to exhibit Y over horizon Z.",
        economic_rationale="Mean reversion",
        falsification_criteria="If Sharpe < 0.5 after costs, reject.",
    )
    defaults.update(overrides)
    return Hypothesis(**defaults)


class TestHypothesis:
    def test_creation(self):
        h = _make_hypothesis()
        assert h.hypothesis_id == "HYP-000001"
        assert h.status == "DRAFT"

    def test_required_fields(self):
        with pytest.raises(ValueError, match="hypothesis_id"):
            Hypothesis(hypothesis_id="", claim="test")
        with pytest.raises(ValueError, match="claim"):
            Hypothesis(hypothesis_id="H1", claim="")

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            _make_hypothesis(status="INVALID")

    def test_register(self):
        h = _make_hypothesis()
        registered = h.register()
        assert registered.status == "REGISTERED"
        assert h.status == "DRAFT"  # original unchanged

    def test_register_non_draft_fails(self):
        h = _make_hypothesis(status="REGISTERED")
        with pytest.raises(ValueError, match="Cannot register"):
            h.register()

    def test_to_from_dict(self):
        h = _make_hypothesis()
        d = h.to_dict()
        assert d["hypothesis_id"] == "HYP-000001"
        assert d["falsification_criteria"] == "If Sharpe < 0.5 after costs, reject."
        h2 = Hypothesis.from_dict(d)
        assert h2.hypothesis_id == h.hypothesis_id
        assert h2.claim == h.claim
