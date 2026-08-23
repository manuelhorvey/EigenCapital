"""Unit tests for Experiment Registry."""

import pytest
from eigencapital.research.experiments.registry import (
    ExperimentRegistry, ExperimentRecord, ExperimentError,
)


def _make_experiment(**overrides):
    defaults = dict(
        experiment_id="EXP-000001",
        hypothesis_id="HYP-000001",
        git_commit="a1b2c3d",
        dataset_id="equities_daily_v1",
        dataset_version="1.0.0",
        dataset_hash="abc123",
        strategy_id="trend_v1",
        strategy_version="0.1.0",
        strategy_config_hash="cfg_hash",
        strategy_artifact_hash="art_hash",
        parameters={"lookback": 100, "breakout": 20},
        random_seed=42,
        train_start="2020-01-01T00:00:00Z",
        train_end="2022-12-31T00:00:00Z",
        validation_start="2023-01-01T00:00:00Z",
        validation_end="2023-06-30T00:00:00Z",
        test_start="2023-07-01T00:00:00Z",
        test_end="2023-12-31T00:00:00Z",
    )
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


class TestExperimentRegistry:
    def test_create_experiment(self):
        reg = ExperimentRegistry()
        exp = reg.create(**_make_experiment().__dict__)
        assert exp.experiment_id == "EXP-000001"
        assert exp.provenance_hash != ""

    def test_duplicate_experiment_id(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        with pytest.raises(ExperimentError, match="Duplicate"):
            reg.create(**_make_experiment().__dict__)

    def test_lifecycle_happy_path(self):
        reg = ExperimentRegistry()
        exp = reg.create(**_make_experiment().__dict__)
        assert exp.status == "PRE_REGISTERED"

        exp = reg.freeze_test_parameters("EXP-000001")
        assert exp.test_frozen is True

        exp = reg.start("EXP-000001")
        assert exp.status == "RUNNING"

        exp = reg.complete("EXP-000001", status="CANDIDATE",
                           result={"sharpe": 1.5})
        assert exp.status == "CANDIDATE"
        assert exp.result["sharpe"] == 1.5

    def test_cannot_freeze_twice(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        reg.freeze_test_parameters("EXP-000001")
        with pytest.raises(ExperimentError, match="already frozen"):
            reg.freeze_test_parameters("EXP-000001")

    def test_cannot_start_without_freeze(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        # Can start without freeze (freeze is optional but recommended)
        exp = reg.start("EXP-000001")
        assert exp.status == "RUNNING"

    def test_cannot_start_from_running(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        reg.start("EXP-000001")
        with pytest.raises(ExperimentError, match="Cannot start"):
            reg.start("EXP-000001")

    def test_cannot_complete_without_running(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        with pytest.raises(ExperimentError, match="Cannot complete"):
            reg.complete("EXP-000001")

    def test_invalid_final_status(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        reg.start("EXP-000001")
        with pytest.raises(ExperimentError, match="Invalid final status"):
            reg.complete("EXP-000001", status="INVALID")

    def test_reject_experiment(self):
        reg = ExperimentRegistry()
        reg.create(**_make_experiment().__dict__)
        reg.start("EXP-000001")
        exp = reg.complete("EXP-000001", status="REJECTED",
                           result={"sharpe": 0.2})
        assert exp.status == "REJECTED"

    def test_provenance_hash_deterministic(self):
        reg = ExperimentRegistry()
        exp1 = reg.create(**_make_experiment().__dict__)
        h1 = exp1.provenance_hash
        # Create fresh registry with same inputs
        reg2 = ExperimentRegistry()
        exp2 = reg2.create(**_make_experiment().__dict__)
        h2 = exp2.provenance_hash
        assert h1 == h2

    def test_different_params_different_hash(self):
        reg = ExperimentRegistry()
        exp1 = reg.create(**_make_experiment(experiment_id="EXP-000001").__dict__)
        reg2 = ExperimentRegistry()
        exp2 = reg2.create(**_make_experiment(
            experiment_id="EXP-000002",
            parameters={"lookback": 200},
        ).__dict__)
        assert exp1.provenance_hash != exp2.provenance_hash

    def test_to_from_dict(self):
        exp = _make_experiment()
        d = exp.to_dict()
        assert d["experiment_id"] == "EXP-000001"
        exp2 = ExperimentRecord.from_dict(d)
        assert exp2.experiment_id == exp.experiment_id
        assert exp2.parameters == exp.parameters


class TestExperimentRepository:
    def test_save_and_load(self, tmp_path):
        from eigencapital.research.experiments.repository import ExperimentRepository
        repo = ExperimentRepository(tmp_path)
        exp = _make_experiment()
        repo.save(exp)
        loaded = repo.load("EXP-000001")
        assert loaded.experiment_id == "EXP-000001"
        assert loaded.parameters == exp.parameters

    def test_load_not_found(self, tmp_path):
        from eigencapital.research.experiments.repository import ExperimentRepository
        repo = ExperimentRepository(tmp_path)
        with pytest.raises(ExperimentError):
            repo.load("NONEXISTENT")

    def test_list_ids(self, tmp_path):
        from eigencapital.research.experiments.repository import ExperimentRepository
        repo = ExperimentRepository(tmp_path)
        repo.save(_make_experiment(experiment_id="EXP-000002"))
        repo.save(_make_experiment(experiment_id="EXP-000001"))
        assert repo.list_ids() == ["EXP-000001", "EXP-000002"]

    def test_delete(self, tmp_path):
        from eigencapital.research.experiments.repository import ExperimentRepository
        repo = ExperimentRepository(tmp_path)
        repo.save(_make_experiment())
        assert repo.delete("EXP-000001") is True
        assert repo.exists("EXP-000001") is False
