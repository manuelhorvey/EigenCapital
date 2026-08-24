"""Unit tests for TrialMetadata — multiple-testing accounting.

Invariants under test:
- trial_group_id / hypothesis_family / selection_method must be non-empty
- trial_index must be an int >= 1
- trials_in_family, when set, must be an int >= trial_index
- parameter_search_space must be a dict
- deterministic to_dict/from_dict round-trip
"""

import pytest
from eigencapital.core.models.trial_metadata import TrialMetadata


def _make_tm(**overrides):
    defaults = dict(
        trial_group_id="HYP-TREND-001/lookback-stop-grid",
        trial_index=3,
        hypothesis_family="trend",
        selection_method="best_validation_sharpe",
        trials_in_family=8,
        parameter_search_space={"lookback": [20, 40, 60, 80], "stop_atr": [1.0, 1.5, 2.0]},
    )
    defaults.update(overrides)
    return TrialMetadata(**defaults)


class TestTrialMetadataCreation:
    def test_creation_with_full_metadata(self):
        tm = _make_tm()
        assert tm.trial_group_id == "HYP-TREND-001/lookback-stop-grid"
        assert tm.trial_index == 3
        assert tm.trials_in_family == 8
        assert tm.hypothesis_family == "trend"
        assert tm.selection_method == "best_validation_sharpe"
        assert tm.parameter_search_space["lookback"] == [20, 40, 60, 80]

    def test_single_shot_experiment_defaults(self):
        """Single-candidate experiments: index 1, open family, no search space."""
        tm = TrialMetadata(
            trial_group_id="HYP-MR-002",
            trial_index=1,
            hypothesis_family="mean_reversion",
            selection_method="single_candidate",
        )
        assert tm.is_first_trial is True
        assert tm.family_is_open is True
        assert tm.parameter_search_space == {}

    def test_frozen_immutability(self):
        tm = _make_tm()
        with pytest.raises(Exception):
            tm.trial_index = 99


class TestTrialMetadataInvariants:
    def test_empty_trial_group_id_rejected(self):
        with pytest.raises(ValueError, match="trial_group_id"):
            _make_tm(trial_group_id="")

    def test_empty_hypothesis_family_rejected(self):
        with pytest.raises(ValueError, match="hypothesis_family"):
            _make_tm(hypothesis_family="")

    def test_empty_selection_method_rejected(self):
        with pytest.raises(ValueError, match="selection_method"):
            _make_tm(selection_method="")

    @pytest.mark.parametrize("bad_index", [0, -1, 2.5, "3", None])
    def test_invalid_trial_index_rejected(self, bad_index):
        with pytest.raises(ValueError, match="trial_index"):
            _make_tm(trial_index=bad_index)

    def test_trials_in_family_below_index_rejected(self):
        with pytest.raises(ValueError, match="trials_in_family"):
            _make_tm(trial_index=5, trials_in_family=4)

    @pytest.mark.parametrize("bad_size", [0, -3, 7.5, "12"])
    def test_invalid_trials_in_family_rejected(self, bad_size):
        with pytest.raises(ValueError, match="trials_in_family"):
            _make_tm(trials_in_family=bad_size)

    def test_trials_in_family_equal_to_index_allowed(self):
        """The last trial of a closed family may know its own position."""
        tm = _make_tm(trial_index=8, trials_in_family=8)
        assert tm.trials_in_family == tm.trial_index

    def test_non_dict_search_space_rejected(self):
        with pytest.raises(ValueError, match="parameter_search_space"):
            _make_tm(parameter_search_space=["lookback"])


class TestTrialMetadataSerialization:
    def test_to_dict_deterministic_round_trip(self):
        tm = _make_tm()
        d = tm.to_dict()
        assert d["trial_group_id"] == "HYP-TREND-001/lookback-stop-grid"
        restored = TrialMetadata.from_dict(d)
        assert restored == tm

    def test_none_fields_survive_round_trip(self):
        tm = _make_tm(trials_in_family=None)
        restored = TrialMetadata.from_dict(tm.to_dict())
        assert restored.trials_in_family is None
        assert restored.family_is_open is True


class TestTrialMetadataSemantics:
    def test_is_first_trial(self):
        assert _make_tm(trial_index=1).is_first_trial is True
        assert _make_tm(trial_index=2).is_first_trial is False

    def test_summary_contains_context(self):
        s = _make_tm().summary()
        assert "HYP-TREND-001" in s
        assert "trend" in s
        assert "3/8" in s
