"""Unit tests for R6 Phase B1 — deterministic meta-labeling filter.

Covers the frozen R6 contract (docs/research/R6_META_LABELING.md §5):
- the preregistered vol-cap filter split (take iff vol_scale < 1.0)
- favorable-rate arithmetic against hand-computed values
- the preregistered paired moving-block bootstrap CI (block 20, seed 42),
  including degenerate-class and too-short-sequence missing-evidence paths
- WF-geometry OOS slices over event time (descriptive)
- determinism under the frozen seed
- label-0 handling: counted as NOT favorable, never dropped
- input validation
"""

from __future__ import annotations

import math

import pytest

from eigencapital.research.meta_labeling import (
    BLOCK_LENGTH,
    B1Result,
    BaselineError,
    evaluate_b1,
    filter_split,
    paired_block_bootstrap_ci,
    rate_difference,
    summarize,
)

# ── Filter split (hand-computed) ─────────────────────────────────────────────


def test_filter_split_hand_computed() -> None:
    vs = [0.8, 1.0, 0.5, 1.0, 0.9]
    labs = [1, 1, -1, -1, 1]
    split = filter_split(vs, labs)
    assert (split.n_taken, split.n_skipped) == (3, 2)
    assert (split.favorable_taken, split.favorable_skipped) == (2, 1)
    assert math.isclose(split.rate_taken, 2 / 3, rel_tol=1e-12)
    assert math.isclose(split.rate_skipped, 0.5, rel_tol=1e-12)
    assert math.isclose(rate_difference(split), 2 / 3 - 0.5, rel_tol=1e-12)


def test_filter_zero_vol_scale_counts_as_capped() -> None:
    # vol_scale == 0.0 is finite, non-negative, and < 1.0 → taken.
    split = filter_split([0.0], [1])
    assert split.n_taken == 1


def test_filter_label_zero_is_not_favorable_and_not_dropped() -> None:
    split = filter_split([0.9, 1.0], [0, 0])
    assert split.favorable_taken == 0
    assert split.favorable_skipped == 0
    assert split.rate_taken == 0.0  # counted, produced rate 0 — not dropped


def test_filter_empty_class_gives_none_rate() -> None:
    split = filter_split([0.9, 0.8], [1, -1])  # nothing capped → skipped empty
    assert split.n_skipped == 0
    assert split.rate_skipped is None
    assert rate_difference(split) is None


def test_filter_validation() -> None:
    with pytest.raises(BaselineError, match="align"):
        filter_split([0.5], [1, -1])
    with pytest.raises(BaselineError, match="vol_scale"):
        filter_split([-0.1], [1])
    with pytest.raises(BaselineError, match="labels"):
        filter_split([0.5], [2])


# ── Block-bootstrap CI (preregistered engine + seed) ─────────────────────────


def test_ci_deterministic_under_frozen_seed() -> None:
    vs = [0.9, 1.0] * 40
    labs = [1, -1] * 40
    mask = [v < 1.0 for v in vs]
    c1 = paired_block_bootstrap_ci(labs, mask, n_resamples=200, block_length=10, seed=42)
    c2 = paired_block_bootstrap_ci(labs, mask, n_resamples=200, block_length=10, seed=42)
    assert c1 == c2


def test_ci_excludes_zero_for_perfect_separation() -> None:
    # Taken events always favorable, skipped never → every resample diff > 0.
    vs = [0.9] * 50 + [1.0] * 50
    labs = [1] * 50 + [-1] * 50
    low, high = paired_block_bootstrap_ci(labs, [v < 1.0 for v in vs], n_resamples=200, block_length=20, seed=42)
    assert low is not None and high is not None
    assert low > 0.0


def test_ci_missing_evidence_when_one_class_absent() -> None:
    low, high = paired_block_bootstrap_ci([1, -1], [True, True], n_resamples=100, seed=42)
    assert low is None and high is None


def test_ci_missing_evidence_when_sequence_shorter_than_block() -> None:
    low, high = paired_block_bootstrap_ci([1, -1], [True, False], n_resamples=100, block_length=20, seed=42)
    assert low is None and high is None


def test_ci_default_block_length_is_the_frozen_twenty() -> None:
    assert BLOCK_LENGTH == 20


# ── OOS slices (descriptive, hand-computed) ──────────────────────────────────


def test_oos_slices_hand_computed() -> None:
    # 30 events; geometry purge=2 embargo=1 test=10 → first OOS [3, 13).
    dates = list(range(30))
    vs = [0.5] * 10 + [1.0] * 10 + [0.5] * 10
    labs = [1] * 10 + [-1] * 10 + [1] * 10
    slices = evaluate_b1(
        vs, labs, dates, train_bars=504, purge_bars=2, embargo_bars=1, test_bars=10, n_resamples=50
    ).oos_slices
    first = slices[0]
    assert (first.oos_start, first.oos_end) == (3, 13)
    assert first.n_taken == 7 and first.n_skipped == 3
    assert first.rate_diff is not None and first.rate_diff > 0  # taken all +1, skipped all −1
    assert slices[-1].oos_end == 30


# ── Full evaluation + verdict logic ──────────────────────────────────────────


def test_evaluate_success_path() -> None:
    vs = [0.9] * 60 + [1.0] * 60
    labs = [1] * 60 + [-1] * 60
    result = evaluate_b1(vs, labs, list(range(120)), train_bars=504, purge_bars=2, embargo_bars=1, test_bars=10, n_resamples=200)
    assert isinstance(result, B1Result)
    assert result.verdict == "SUCCESS"
    assert result.ci_low is not None and result.ci_low > 0.0
    assert result.rate_difference is not None and result.rate_difference > 0.0


def test_evaluate_failure_path() -> None:
    vs = [0.9] * 60 + [1.0] * 60
    labs = [-1] * 60 + [1] * 60  # skipped events are the favorable ones
    result = evaluate_b1(vs, labs, list(range(120)), train_bars=504, purge_bars=2, embargo_bars=1, test_bars=10, n_resamples=200)
    assert result.verdict == "FAILURE"
    assert result.rate_difference is not None and result.rate_difference < 0.0


def test_evaluate_inconclusive_when_one_class_empty() -> None:
    result = evaluate_b1(
        [0.9] * 24, [1] * 24, list(range(24)), train_bars=504, purge_bars=2, embargo_bars=1, test_bars=10, n_resamples=50
    )
    assert result.verdict == "INCONCLUSIVE"
    assert result.ci_low is None and result.ci_high is None


def test_summarize_is_json_safe() -> None:
    vs = [0.9] * 30 + [1.0] * 30
    labs = [1] * 30 + [-1] * 30
    result = evaluate_b1(vs, labs, list(range(60)), train_bars=504, purge_bars=2, embargo_bars=1, test_bars=10, n_resamples=50)
    summary = summarize(result)
    assert summary["verdict"] in ("SUCCESS", "FAILURE", "INCONCLUSIVE")
    assert len(summary["oos_window_rate_diffs"]) == len(result.oos_slices)
