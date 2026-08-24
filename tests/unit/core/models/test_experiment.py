"""Unit tests for Experiment domain model — including trial accounting.

Covers lifecycle fields, split invariants, uniqueness registry,
parent lineage, and TrialMetadata integration.
"""

from datetime import date

import pytest

from eigencapital.core.models.experiment import Experiment, ExperimentStatus
from eigencapital.core.models.trial_metadata import TrialMetadata

_counter = 0


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset the Experiment uniqueness ledger between tests."""
    if hasattr(Experiment, "_registry"):
        Experiment._registry.clear()
    yield
    if hasattr(Experiment, "_registry"):
        Experiment._registry.clear()


def _make_experiment(**overrides):
    """Helper with sensible defaults; auto-generates unique experiment_id."""
    global _counter
    _counter += 1
    defaults = dict(
        experiment_id=f"EXP-{_counter:06d}",
        git_commit="a" * 40,
        dataset_version="equities_daily_v3",
        strategy_id="trend_v1",
        strategy_version="0.1.0",
        parameters={"lookback": 100},
        cost_model="cost_model_v2",
    )
    defaults.update(overrides)
    return Experiment(**defaults)


def _make_tm(**overrides):
    defaults = dict(
        trial_group_id="HYP-TREND-001/lookback-stop-grid",
        trial_index=2,
        hypothesis_family="trend",
        selection_method="best_validation_sharpe",
        trials_in_family=8,
    )
    defaults.update(overrides)
    return TrialMetadata(**defaults)


class TestExperimentCreation:
    def test_creation_minimal(self):
        exp = _make_experiment()
        assert exp.status == ExperimentStatus.PRE_REGISTERED
        assert exp.horizon == "swing"
        assert exp.trial_metadata is None
        assert exp.parent_experiment_id is None

    def test_required_fields_must_be_non_empty(self):
        for field in ("experiment_id", "git_commit", "dataset_version", "strategy_id",
                      "strategy_version", "cost_model"):
            with pytest.raises(ValueError):
                _make_experiment(**{field: ""})

    def test_invalid_horizon_rejected(self):
        with pytest.raises(ValueError, match="horizon"):
            _make_experiment(horizon="weekly")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            _make_experiment(status="FINISHED")

    def test_duplicate_experiment_id_rejected(self):
        exp = _make_experiment()
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            Experiment(
                **{**exp.__dict__, "parameters": dict(exp.parameters)}
            )


class TestExperimentSplits:
    def test_valid_split_triple(self):
        exp = _make_experiment(
            train_split=(date(2020, 1, 1), date(2022, 12, 31)),
            validation_split=(date(2023, 1, 1), date(2023, 6, 30)),
            test_split=(date(2023, 7, 1), date(2023, 12, 31)),
        )
        assert exp.is_complete is False  # status not COMPLETED yet
        assert exp.full_split_triple is not None

    def test_inverted_train_split_rejected(self):
        with pytest.raises(ValueError, match="train_split"):
            _make_experiment(train_split=(date(2022, 1, 1), date(2020, 1, 1)))

    def test_overlapping_splits_rejected(self):
        with pytest.raises(ValueError, match="overlap"):
            _make_experiment(
                train_split=(date(2020, 1, 1), date(2023, 3, 31)),
                validation_split=(date(2023, 1, 1), date(2023, 6, 30)),
                test_split=(date(2023, 7, 1), date(2023, 12, 31)),
            )

    def test_negative_seed_rejected(self):
        with pytest.raises(ValueError, match="random_seed"):
            _make_experiment(random_seed=-1)


class TestExperimentTrialAccounting:
    def test_attach_trial_metadata(self):
        tm = _make_tm()
        exp = _make_experiment(trial_metadata=tm)
        assert exp.has_trial_metadata is True
        assert exp.trial_family_size == 8
        assert exp.trial_metadata.trial_index == 2

    def test_non_trial_metadata_type_rejected(self):
        with pytest.raises(ValueError, match="trial_metadata"):
            _make_experiment(trial_metadata={"trial_index": 1})

    def test_parent_lineage(self):
        exp = _make_experiment(parent_experiment_id="EXP-000001")
        assert exp.parent_experiment_id == "EXP-000001"

    def test_empty_parent_id_rejected(self):
        with pytest.raises(ValueError, match="parent_experiment_id"):
            _make_experiment(parent_experiment_id="")


class TestExperimentSerialization:
    def test_round_trip_with_trial_metadata(self):
        exp = _make_experiment(
            parent_experiment_id="EXP-000001",
            trial_metadata=_make_tm(),
            start_date=date(2020, 1, 1),
            end_date=date(2023, 12, 31),
            train_split=(date(2020, 1, 1), date(2022, 12, 31)),
            validation_split=(date(2023, 1, 1), date(2023, 6, 30)),
            test_split=(date(2023, 7, 1), date(2023, 12, 31)),
        )
        d = exp.to_dict()
        Experiment._registry.pop(exp.experiment_id, None)  # allow same-process reload
        restored = Experiment.from_dict(d)
        assert restored == exp
        assert restored.trial_metadata == exp.trial_metadata
        assert restored.parent_experiment_id == "EXP-000001"

    def test_round_trip_without_trial_metadata(self):
        exp = _make_experiment()
        d = exp.to_dict()
        assert d["trial_metadata"] is None
        Experiment._registry.pop(exp.experiment_id, None)  # allow same-process reload
        restored = Experiment.from_dict(d)
        assert restored == exp
        assert restored.trial_metadata is None

    def test_summary_mentions_trials_when_present(self):
        exp = _make_experiment(trial_metadata=_make_tm())
        s = exp.summary()
        assert "trials=" in s
        assert "HYP-TREND-001" in s
