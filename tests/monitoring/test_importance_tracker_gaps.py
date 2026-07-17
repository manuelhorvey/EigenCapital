import os
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st, settings

from monitoring.importance_tracker import (
    ImportanceStore,
    StabilityResult,
    compute_jaccard_top_n,
    compute_spearman_rank_corr,
    compute_stability_penalty,
    STABILITY_PENALTIES,
)


# ── Property-based tests for compute_stability_penalty ───────────────────────


@given(
    jaccard=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    spearman=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_stability_penalty_is_non_positive(jaccard, spearman):
    """Stability penalty is always <= 0."""
    p = compute_stability_penalty(jaccard, spearman)
    assert p <= 0.0


@given(
    n=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=50)
def test_jaccard_full_overlap_always_one(n):
    """Jaccard of identical sets is always 1.0 regardless of n."""
    features = [{"feature": f"feat_{i}", "importance_score": float(n - i)} for i in range(n)]
    j = compute_jaccard_top_n(features, features, n=n)
    assert j == pytest.approx(1.0)


@given(
    n=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=50)
def test_jaccard_no_overlap_is_zero(n):
    """Jaccard of disjoint sets is always 0.0."""
    current = [{"feature": f"cur_{i}", "importance_score": float(n - i)} for i in range(n)]
    previous = [{"feature": f"prev_{i}", "importance_score": float(n - i)} for i in range(n)]
    j = compute_jaccard_top_n(current, previous, n=n)
    assert j == pytest.approx(0.0)


# ── Edge cases for compute_jaccard_top_n ─────────────────────────────────────


def test_jaccard_n_greater_than_available():
    """Jaccard handles n > available features gracefully."""
    cur = [{"feature": "a", "importance_score": 1.0}]
    prev = [{"feature": "a", "importance_score": 0.8}]
    j = compute_jaccard_top_n(cur, prev, n=100)
    assert j == pytest.approx(1.0)


def test_jaccard_empty_current():
    """Empty current list returns 0.0 when prev is non-empty."""
    cur = []
    prev = [{"feature": "a", "importance_score": 1.0}]
    j = compute_jaccard_top_n(cur, prev, n=3)
    assert j == pytest.approx(0.0)


def test_jaccard_empty_previous():
    """Empty previous list returns 0.0 when cur is non-empty."""
    cur = [{"feature": "a", "importance_score": 1.0}]
    prev = []
    j = compute_jaccard_top_n(cur, prev, n=3)
    assert j == pytest.approx(0.0)


# ── Edge cases for compute_spearman_rank_corr ────────────────────────────────


def test_spearman_empty_current():
    """Spearman with empty current returns 0.0."""
    cur = []
    prev = [{"feature": "a", "rank": 1}]
    assert compute_spearman_rank_corr(cur, prev) == pytest.approx(0.0)


def test_spearman_empty_previous():
    """Spearman with empty previous returns 0.0."""
    cur = [{"feature": "a", "rank": 1}]
    prev = []
    assert compute_spearman_rank_corr(cur, prev) == pytest.approx(0.0)


def test_spearman_exactly_2_common_returns_zero():
    """Spearman with exactly 2 common features returns 0.0."""
    cur = [{"feature": "a", "rank": 1}, {"feature": "b", "rank": 2}, {"feature": "c", "rank": 3}]
    prev = [{"feature": "a", "rank": 3}, {"feature": "b", "rank": 1}, {"feature": "d", "rank": 2}]
    assert compute_spearman_rank_corr(cur, prev) == pytest.approx(0.0)


# ── Edge cases for compute_stability_penalty ─────────────────────────────────


def test_penalty_jaccard_between_soft_and_hard():
    """Jaccard between soft and hard thresholds triggers only soft penalty."""
    p = compute_stability_penalty(jaccard=0.45, spearman=0.9)
    expected = STABILITY_PENALTIES["jaccard_soft"][1]
    assert p == pytest.approx(expected)


def test_penalty_spearman_between_soft_and_hard():
    """Spearman between soft and hard thresholds triggers only soft penalty."""
    p = compute_stability_penalty(jaccard=0.9, spearman=0.55)
    expected = STABILITY_PENALTIES["spearman_soft"][1]
    assert p == pytest.approx(expected)


def test_penalty_both_soft_triggers_uses_most_negative():
    """Both soft penalties trigger and use the most negative."""
    p = compute_stability_penalty(jaccard=0.5, spearman=0.65)
    expected = min(
        STABILITY_PENALTIES["jaccard_soft"][1],
        STABILITY_PENALTIES["spearman_soft"][1],
    )
    assert p == pytest.approx(expected)


def test_penalty_exact_threshold_no_penalty():
    """Values at exact hard threshold boundaries should not trigger hard penalty."""
    # jaccard=0.4 is exactly at jaccard_hard threshold (0.4), so no hard penalty
    # but 0.4 < 0.6 (jaccard_soft), so soft penalty applies
    p = compute_stability_penalty(jaccard=0.4, spearman=0.9)
    assert p == pytest.approx(-0.10)
    # spearman=0.5 is exactly at spearman_hard threshold (0.5), so no hard penalty
    # but 0.5 < 0.7 (spearman_soft), so soft penalty applies
    p = compute_stability_penalty(jaccard=0.9, spearman=0.5)
    assert p == pytest.approx(-0.08)


# ── Edge cases for ImportanceStore ───────────────────────────────────────────


def test_store_roundtrip(tmp_path):
    """Full roundtrip: log snapshot and verify data integrity."""
    store = ImportanceStore(tmp_path)
    store.log_snapshot(
        asset="EURUSD",
        feature_names=["rsi", "macd", "bb"],
        importances=np.array([0.5, 0.3, 0.2]),
        window_id="w1",
        train_start="2023-01-01",
        train_end="2024-01-01",
    )
    df = store.load_history("EURUSD")
    assert len(df) == 3
    assert sorted(df["feature"].tolist()) == ["bb", "macd", "rsi"]
    assert sorted(df["rank"].tolist()) == [1, 2, 3]


def test_store_load_history_exception_returns_empty(tmp_path):
    """load_history returns empty DataFrame when parquet is corrupt."""
    store = ImportanceStore(tmp_path)
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    with open(store.path, "w") as f:
        f.write("not parquet")
    df = store.load_history("ANY")
    assert df.empty


def test_store_log_corrupt_existing_does_not_crash(tmp_path):
    """log_snapshot overwrites corrupt existing history gracefully."""
    store = ImportanceStore(tmp_path)
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    with open(store.path, "w") as f:
        f.write("not parquet")
    store.log_snapshot(
        asset="TEST",
        feature_names=["a"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    df = store.load_history("TEST")
    assert len(df) == 1


def test_store_get_latest_two_snapshots_same_window(tmp_path):
    """get_latest_two_snapshots with duplicate window IDs."""
    store = ImportanceStore(tmp_path)
    store.log_snapshot(
        asset="TEST",
        feature_names=["a"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    store.log_snapshot(
        asset="TEST",
        feature_names=["b"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    latest, prev = store.get_latest_two_snapshots("TEST")
    assert latest is not None
    assert prev is None


def test_store_get_latest_two_snapshots_no_window_ids(tmp_path):
    """get_latest_two_snapshots returns (None, None) when no window_ids."""
    store = ImportanceStore(tmp_path)
    df = pd.DataFrame({"asset": ["TEST"], "feature": ["a"], "window_id": [None]})
    df.to_parquet(store.path)
    latest, prev = store.get_latest_two_snapshots("TEST")
    assert latest is None
    assert prev is None


def test_store_compute_stability_no_data_returns_none(tmp_path):
    """compute_stability returns None when no data."""
    store = ImportanceStore(tmp_path)
    result = store.compute_stability("MISSING")
    assert result is None


def test_store_compute_stability_single_window_returns_none(tmp_path):
    """compute_stability returns None with only one window."""
    store = ImportanceStore(tmp_path)
    store.log_snapshot(
        asset="TEST",
        feature_names=["a"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    result = store.compute_stability("TEST")
    assert result is None


def test_store_compute_stability_full_pipeline(tmp_path):
    """Full stability computation returns correct structure."""
    store = ImportanceStore(tmp_path)
    store.log_snapshot(
        asset="TEST",
        feature_names=["a", "b", "c", "d"],
        importances=np.array([0.4, 0.3, 0.2, 0.1]),
        window_id="w1",
    )
    store.log_snapshot(
        asset="TEST",
        feature_names=["a", "b", "e", "f"],
        importances=np.array([0.5, 0.3, 0.15, 0.05]),
        window_id="w2",
    )
    result = store.compute_stability("TEST")
    assert isinstance(result, StabilityResult)
    assert result.jaccard_top_10 == pytest.approx(0.3333, abs=0.001)
    # spearman may be 0.0 with only 2 common features (<3 common → returns 0)
    assert result.penalty <= 0.0


def test_store_load_all_assets(tmp_path):
    """load_history without asset filter returns all assets."""
    store = ImportanceStore(tmp_path)
    store.log_snapshot(
        asset="A",
        feature_names=["a"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    store.log_snapshot(
        asset="B",
        feature_names=["b"],
        importances=np.array([1.0]),
        window_id="w1",
    )
    df = store.load_history()
    assert len(df) == 2
    assert set(df["asset"].tolist()) == {"A", "B"}


def test_stability_result_creation():
    result = StabilityResult(
        asset="TEST",
        window_id="w2",
        previous_window_id="w1",
        jaccard_top_10=0.5,
        spearman_rank_corr=0.8,
        n_union=6,
        n_current_top10=10,
        penalty=-0.1,
        timestamp="2026-05-25T00:00:00",
    )
    assert result.asset == "TEST"
    assert result.jaccard_top_10 == 0.5
