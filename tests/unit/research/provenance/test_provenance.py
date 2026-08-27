"""Unit tests for provenance hashing and manifest."""

import pytest

from eigencapital.research.provenance.hashing import (
    canonical_json_dumps,
    compute_provenance_hash,
    verify_provenance,
)
from eigencapital.research.provenance.manifest import ResearchManifest


class TestProvenanceHashing:
    def test_deterministic(self):
        inputs = {"a": 1, "b": 2, "c": 3}
        h1 = compute_provenance_hash(inputs)
        h2 = compute_provenance_hash(inputs)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_order_independent(self):
        h1 = compute_provenance_hash({"a": 1, "b": 2})
        h2 = compute_provenance_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = compute_provenance_hash({"a": 1})
        h2 = compute_provenance_hash({"a": 2})
        assert h1 != h2

    def test_nested_determinism(self):
        inputs = {"params": {"x": 10, "y": 20}, "commit": "abc"}
        h1 = compute_provenance_hash(inputs)
        h2 = compute_provenance_hash(inputs)
        assert h1 == h2

    def test_verify_provenance(self):
        inputs = {"a": 1, "b": 2}
        h = compute_provenance_hash(inputs)
        assert verify_provenance(inputs, h) is True
        assert verify_provenance({"a": 1, "b": 3}, h) is False

    def test_canonical_json_dumps(self):
        s1 = canonical_json_dumps({"b": 2, "a": 1})
        s2 = canonical_json_dumps({"a": 1, "b": 2})
        assert s1 == s2
        assert '"a":1' in s1


class TestResearchManifest:
    def test_creation(self):
        m = ResearchManifest(experiment_id="EXP-000001")
        assert m.experiment_id == "EXP-000001"

    def test_required_fields(self):
        with pytest.raises(ValueError, match="experiment_id"):
            ResearchManifest(experiment_id="")

    def test_from_experiment(self):
        from eigencapital.research.experiments.registry import ExperimentRecord

        exp = ExperimentRecord(
            experiment_id="EXP-000001",
            hypothesis_id="HYP-000001",
            git_commit="abc123",
            dataset_id="equities_daily_v1",
            dataset_version="1.0.0",
            dataset_hash="hash1",
            strategy_id="trend_v1",
            strategy_version="0.1.0",
            strategy_config_hash="cfg",
            strategy_artifact_hash="art",
            parameters={"lookback": 100},
            random_seed=42,
            train_start="2020-01-01T00:00:00Z",
            train_end="2022-12-31T00:00:00Z",
        )
        manifest = ResearchManifest.from_experiment(exp)
        assert manifest.experiment_id == "EXP-000001"
        assert manifest.provenance_hash != ""
        assert "train" in manifest.periods

    def test_to_json(self):
        m = ResearchManifest(experiment_id="EXP-000001", code_git_commit="abc")
        j = m.to_json()
        assert "EXP-000001" in j
        assert "abc" in j

    def test_to_from_dict(self):
        m = ResearchManifest(
            experiment_id="EXP-000001",
            strategy_id="trend_v1",
            parameters={"lookback": 100},
        )
        d = m.to_dict()
        m2 = ResearchManifest.from_dict(d)
        assert m2.experiment_id == m.experiment_id
        assert m2.strategy_id == m.strategy_id

    def test_provenance_deterministic(self):
        m1 = ResearchManifest(
            experiment_id="EXP-000001",
            code_git_commit="abc",
            parameters={"x": 1},
        )
        m2 = ResearchManifest(
            experiment_id="EXP-000001",
            code_git_commit="abc",
            parameters={"x": 1},
        )
        assert m1.provenance_hash == m2.provenance_hash

    def test_different_params_different_hash(self):
        m1 = ResearchManifest(experiment_id="EXP-000001", parameters={"x": 1})
        m2 = ResearchManifest(experiment_id="EXP-000001", parameters={"x": 2})
        assert m1.provenance_hash != m2.provenance_hash
