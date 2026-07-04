import os
import tempfile

import numpy as np
import pytest

from monitoring.importance_tracker import (
    ImportanceStore,
    compute_jaccard_top_n,
    compute_spearman_rank_corr,
    compute_stability_penalty,
    STABILITY_PENALTIES,
)


class TestComputeJaccard:
    def test_full_overlap(self):
        cur = [{"feature": "a", "importance_score": 0.5}, {"feature": "b", "importance_score": 0.3},
               {"feature": "c", "importance_score": 0.2}]
        prev = [{"feature": "a", "importance_score": 0.4}, {"feature": "b", "importance_score": 0.35},
                {"feature": "c", "importance_score": 0.25}]
        assert compute_jaccard_top_n(cur, prev, n=3) == pytest.approx(1.0)

    def test_no_overlap(self):
        cur = [{"feature": "a", "importance_score": 0.5}, {"feature": "b", "importance_score": 0.3}]
        prev = [{"feature": "c", "importance_score": 0.5}, {"feature": "d", "importance_score": 0.3}]
        assert compute_jaccard_top_n(cur, prev, n=2) == pytest.approx(0.0)

    def test_partial_overlap(self):
        cur = [{"feature": "a", "importance_score": 0.5}, {"feature": "b", "importance_score": 0.3},
               {"feature": "c", "importance_score": 0.2}]
        prev = [{"feature": "a", "importance_score": 0.4}, {"feature": "d", "importance_score": 0.35},
                {"feature": "e", "importance_score": 0.25}]
        # union = {a,b,c,d,e} = 5, intersection = {a} = 1 => 1/5 = 0.2
        assert compute_jaccard_top_n(cur, prev, n=3) == pytest.approx(0.2)

    def test_empty_union_returns_one(self):
        cur = []
        prev = []
        assert compute_jaccard_top_n(cur, prev, n=3) == pytest.approx(1.0)

    def test_n_greater_than_features(self):
        cur = [{"feature": "a", "importance_score": 1.0}]
        prev = [{"feature": "a", "importance_score": 1.0}]
        assert compute_jaccard_top_n(cur, prev, n=10) == pytest.approx(1.0)


class TestComputeSpearman:
    def test_perfect_positive_corr(self):
        cur = [{"feature": "a", "rank": 1}, {"feature": "b", "rank": 2}, {"feature": "c", "rank": 3}]
        prev = [{"feature": "a", "rank": 1}, {"feature": "b", "rank": 2}, {"feature": "c", "rank": 3}]
        assert compute_spearman_rank_corr(cur, prev) == pytest.approx(1.0)

    def test_perfect_negative_corr(self):
        cur = [{"feature": "a", "rank": 1}, {"feature": "b", "rank": 2}, {"feature": "c", "rank": 3}]
        prev = [{"feature": "a", "rank": 3}, {"feature": "b", "rank": 2}, {"feature": "c", "rank": 1}]
        assert compute_spearman_rank_corr(cur, prev) == pytest.approx(-1.0)

    def test_no_common_features(self):
        cur = [{"feature": "a", "rank": 1}]
        prev = [{"feature": "b", "rank": 1}]
        assert compute_spearman_rank_corr(cur, prev) == pytest.approx(0.0)

    def test_fewer_than_three_common(self):
        cur = [{"feature": "a", "rank": 1}, {"feature": "b", "rank": 2}]
        prev = [{"feature": "a", "rank": 2}, {"feature": "c", "rank": 1}]
        assert compute_spearman_rank_corr(cur, prev) == pytest.approx(0.0)


class TestComputePenalty:
    def test_no_penalty_when_above_thresholds(self):
        p = compute_stability_penalty(jaccard=0.8, spearman=0.9)
        assert p == 0.0

    def test_jaccard_soft_triggers(self):
        p = compute_stability_penalty(jaccard=0.5, spearman=0.8)
        assert p == pytest.approx(STABILITY_PENALTIES["jaccard_soft"][1])

    def test_jaccard_hard_triggers(self):
        p = compute_stability_penalty(jaccard=0.35, spearman=0.8)
        assert p == pytest.approx(STABILITY_PENALTIES["jaccard_hard"][1])

    def test_spearman_soft_triggers(self):
        p = compute_stability_penalty(jaccard=0.8, spearman=0.65)
        assert p == pytest.approx(STABILITY_PENALTIES["spearman_soft"][1])

    def test_spearman_hard_triggers(self):
        p = compute_stability_penalty(jaccard=0.8, spearman=0.45)
        assert p == pytest.approx(STABILITY_PENALTIES["spearman_hard"][1])

    def test_both_triggers_uses_most_negative(self):
        p = compute_stability_penalty(jaccard=0.35, spearman=0.45)
        expected = min(STABILITY_PENALTIES["jaccard_hard"][1], STABILITY_PENALTIES["spearman_hard"][1])
        assert p == pytest.approx(expected)

    def test_edge_case_exactly_at_threshold(self):
        p = compute_stability_penalty(jaccard=0.6, spearman=0.7)
        assert p == 0.0


class TestImportanceStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield ImportanceStore(tmp)

    def test_log_snapshot_creates_file(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b", "c"],
            importances=np.array([0.5, 0.3, 0.2]),
            window_id="w1_2026-01-01",
            train_start="2021-01-01", train_end="2026-01-01",
        )
        assert os.path.exists(store.path)

    def test_log_snapshot_roundtrip(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["x", "y", "z"],
            importances=np.array([0.6, 0.3, 0.1]),
            window_id="w1_2026-06-01",
        )
        df = store.load_history(asset="TEST")
        assert len(df) == 3
        assert sorted(df["feature"].tolist()) == ["x", "y", "z"]

    def test_load_empty_when_no_file(self, store):
        df = store.load_history(asset="MISSING")
        assert df.empty

    def test_log_mismatched_lengths_does_not_crash(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b"],
            importances=np.array([0.5, 0.3, 0.2]),
            window_id="w1",
        )
        assert not os.path.exists(store.path)

    def test_log_empty_features_does_not_crash(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=[],
            importances=np.array([]),
            window_id="w1",
        )
        assert not os.path.exists(store.path)

    def test_log_two_windows(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b"],
            importances=np.array([0.7, 0.3]),
            window_id="w1_2025-01-01",
        )
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b"],
            importances=np.array([0.6, 0.4]),
            window_id="w2_2026-01-01",
        )
        latest, prev = store.get_latest_two_snapshots("TEST")
        assert latest is not None
        assert prev is not None
        assert latest["window_id"].iloc[0] == "w2_2026-01-01"
        assert prev["window_id"].iloc[0] == "w1_2025-01-01"

    def test_get_latest_two_snapshots_single_window(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a"],
            importances=np.array([1.0]),
            window_id="w1_2026-01-01",
        )
        latest, prev = store.get_latest_two_snapshots("TEST")
        assert latest is not None
        assert prev is None

    def test_get_latest_two_snapshots_no_data(self, store):
        latest, prev = store.get_latest_two_snapshots("MISSING")
        assert latest is None
        assert prev is None

    def test_stability_result(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b", "c", "d"],
            importances=np.array([0.4, 0.3, 0.2, 0.1]),
            window_id="w1_2025-01-01",
        )
        store.log_snapshot(
            asset="TEST", feature_names=["a", "b", "e", "f"],
            importances=np.array([0.4, 0.3, 0.2, 0.1]),
            window_id="w2_2026-01-01",
        )
        result = store.compute_stability("TEST")
        assert result is not None
        assert result.jaccard_top_10 == pytest.approx(0.3333, abs=0.001)  # {a,b} / {a,b,c,d,e,f} = 2/6
        assert result.previous_window_id == "w1_2025-01-01"
        assert result.window_id == "w2_2026-01-01"

    def test_stability_result_single_window_returns_none(self, store):
        store.log_snapshot(
            asset="TEST", feature_names=["a"],
            importances=np.array([1.0]),
            window_id="w1_2026-01-01",
        )
        result = store.compute_stability("TEST")
        assert result is None

    def test_per_asset_isolation(self, store):
        store.log_snapshot(
            asset="A", feature_names=["a", "b"],
            importances=np.array([0.6, 0.4]),
            window_id="w1_2026-01-01",
        )
        store.log_snapshot(
            asset="A", feature_names=["a", "b"],
            importances=np.array([0.7, 0.3]),
            window_id="w2_2026-06-01",
        )
        store.log_snapshot(
            asset="B", feature_names=["x", "y"],
            importances=np.array([0.8, 0.2]),
            window_id="w1_2026-01-01",
        )

        # B only has 1 window → no stability
        result_a = store.compute_stability("A")
        result_b = store.compute_stability("B")
        assert result_a is not None
        assert result_b is None
