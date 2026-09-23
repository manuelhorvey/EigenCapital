"""Meta-Labeling Baselines — R6-B1 deterministic filter evaluation.

R6 Phase B1 (docs/research/R6_META_LABELING.md, frozen contract). Pure
evaluation machinery for the ONE preregistered filter:

    take event  iff  vol_scale < 1.0   (vol60 < VOL_SCALE_REFERENCE)
    skip event  iff  vol_scale == 1.0  (entry weight was vol-capped)

The headline statistic is the favorable-label rate difference
rate(taken) − rate(skipped) over the full preregistered event population,
with a preregistered moving-block bootstrap CI (block_length = 20, seed 42,
reusing the R1 B3 engine) over the date-ordered paired signed-label
sequence. WF-geometry OOS slices over event time are reported alongside —
they are descriptive, and the frozen success criterion applies to the
full-period difference.

Everything here is a filter-quality measurement. No take/skip strategy
verdict, no forecast (contract item 6/8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from eigencapital.research.monte_carlo.block_bootstrap import moving_block_sample

BLOCK_LENGTH = 20
BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 42


class BaselineError(ValueError):
    """Raised on invalid baseline evaluation inputs."""


@dataclass(frozen=True)
class FilterSplit:
    """Taken/skipped partition under the preregistered filter."""

    n_taken: int
    n_skipped: int
    favorable_taken: int
    favorable_skipped: int
    rate_taken: float | None
    rate_skipped: float | None


@dataclass(frozen=True)
class OosWindowSlice:
    """One WF-window OOS slice over event time (descriptive)."""

    window: int
    oos_start: int
    oos_end: int
    n_taken: int
    n_skipped: int
    rate_diff: float | None


@dataclass(frozen=True)
class B1Result:
    """Full R6-B1 evaluation result."""

    split: FilterSplit
    rate_difference: float | None
    ci_low: float | None
    ci_high: float | None
    ci_excludes_zero_positive: bool
    verdict: str  # SUCCESS | FAILURE | INCONCLUSIVE
    verdict_statement: str
    oos_slices: Tuple[OosWindowSlice, ...]
    n_bootstrap: int
    block_length: int
    seed: int


def filter_split(vol_scales: Sequence[float], signed_labels: Sequence[int]) -> FilterSplit:
    """Split events by the preregistered vol-cap filter and count rates.

    A favorable label is +1 (PT first or favorable vertical). The R5
    population contains no label-0 events (exact equality never occurred);
    any 0 arriving here counts as NOT favorable and is reported through the
    rates, never dropped.
    """
    if len(vol_scales) != len(signed_labels):
        raise BaselineError(f"vol_scales ({len(vol_scales)}) and signed_labels ({len(signed_labels)}) must align 1:1")
    n_taken = n_skipped = fav_taken = fav_skipped = 0
    for vs, lab in zip(vol_scales, signed_labels):
        if not np.isfinite(vs) or vs < 0.0:
            raise BaselineError(f"vol_scale must be finite and non-negative, got {vs!r}")
        if lab not in (-1, 0, 1):
            raise BaselineError(f"labels must be in {{-1, 0, +1}}, got {lab!r}")
        if vs < 1.0:
            n_taken += 1
            if lab == 1:
                fav_taken += 1
        else:
            n_skipped += 1
            if lab == 1:
                fav_skipped += 1
    return FilterSplit(
        n_taken=n_taken,
        n_skipped=n_skipped,
        favorable_taken=fav_taken,
        favorable_skipped=fav_skipped,
        rate_taken=(fav_taken / n_taken) if n_taken else None,
        rate_skipped=(fav_skipped / n_skipped) if n_skipped else None,
    )


def rate_difference(split: FilterSplit) -> float | None:
    """rate(taken) − rate(skipped); None when either side is empty."""
    if split.rate_taken is None or split.rate_skipped is None:
        return None
    return split.rate_taken - split.rate_skipped


def paired_block_bootstrap_ci(
    signed_labels: Sequence[int],
    taken_mask: Sequence[bool],
    n_resamples: int = BOOTSTRAP_N,
    block_length: int = BLOCK_LENGTH,
    seed: int = BOOTSTRAP_SEED,
) -> Tuple[float | None, float | None]:
    """Preregistered 90% CI for the rate difference under resampling.

    Resamples the DATE-ORDERED paired (label, taken-mask) sequence by moving
    blocks (R1 B3 engine), recomputing the rate difference per resample.
    Overlap caveat (frozen): block resampling mitigates but does not
    eliminate label-interval dependence. Returns (None, None) when the
    resample cannot be formed or one class is absent in the sample —
    missing evidence stays missing.
    """
    n = len(signed_labels)
    if not (n == len(taken_mask)) or n == 0:
        raise BaselineError("signed_labels and taken_mask must be non-empty and aligned")
    labels = np.asarray(signed_labels, dtype=float)
    mask = np.asarray(taken_mask, dtype=bool)
    taken_present = bool(mask.any())
    skipped_present = bool((~mask).any())
    if not (taken_present and skipped_present):
        return None, None
    if n < block_length:
        return None, None
    rng = np.random.default_rng(seed)
    diffs: List[float] = []
    for _ in range(n_resamples):
        idx = np.asarray(moving_block_sample(list(range(n)), block_length, n, rng), dtype=int)
        lab_s, mask_s = labels[idx], mask[idx]
        rt = lab_s[mask_s].mean() if mask_s.any() else None
        rs = lab_s[~mask_s].mean() if (~mask_s).any() else None
        if rt is None or rs is None:
            continue
        diffs.append(rt - rs)
    if len(diffs) < 2:
        return None, None
    low, high = np.percentile(diffs, [5.0, 95.0])
    return float(low), float(high)


def oos_window_slices(
    event_dates: Sequence[object],
    vol_scales: Sequence[float],
    signed_labels: Sequence[int],
    train_bars: int,
    purge_bars: int,
    embargo_bars: int,
    test_bars: int,
) -> Tuple[OosWindowSlice, ...]:
    """Descriptive rate-difference slices under the frozen WF geometry.

    Windows are anchored over EVENT positions: train [0, t0), OOS
    [t0 + purge + embargo, t0 + purge + embargo + test). The purge/embargo
    gap separates train labels from OOS events (R5 overlap constraint);
    interval-end-aware purging arrives with B2's fitted models, which need
    it for training; this descriptive slice uses the frozen geometry
    directly over event positions.
    """
    n = len(event_dates)
    if not (n == len(vol_scales) == len(signed_labels)):
        raise BaselineError("inputs must align 1:1")
    stride = max(1, test_bars // 2)
    slices: List[OosWindowSlice] = []
    t0, window = 0, 1
    while True:
        oos_start = t0 + purge_bars + embargo_bars
        oos_end = min(oos_start + test_bars, n)
        if oos_start >= n:
            break
        vs_o, lab_o = vol_scales[oos_start:oos_end], signed_labels[oos_start:oos_end]
        nt = sum(1 for v in vs_o if v < 1.0)
        ns = len(vs_o) - nt
        ft = sum(1 for v, lab in zip(vs_o, lab_o) if v < 1.0 and lab == 1)
        fs = sum(1 for v, lab in zip(vs_o, lab_o) if v >= 1.0 and lab == 1)
        rt = (ft / nt) if nt else None
        rs = (fs / ns) if ns else None
        slices.append(
            OosWindowSlice(
                window=window,
                oos_start=oos_start,
                oos_end=oos_end,
                n_taken=nt,
                n_skipped=ns,
                rate_diff=(rt - rs) if (rt is not None and rs is not None) else None,
            )
        )
        if oos_end >= n:
            break
        t0 += stride
        window += 1
    del train_bars  # geometry documented; anchored start is position 0
    return tuple(slices)


def evaluate_b1(
    vol_scales: Sequence[float],
    signed_labels: Sequence[int],
    event_dates: Sequence[object],
    train_bars: int,
    purge_bars: int,
    embargo_bars: int,
    test_bars: int,
    n_resamples: int = BOOTSTRAP_N,
    block_length: int = BLOCK_LENGTH,
    seed: int = BOOTSTRAP_SEED,
) -> B1Result:
    """Full preregistered B1 evaluation (success criterion frozen in §5)."""
    split = filter_split(vol_scales, signed_labels)
    diff = rate_difference(split)
    low, high = paired_block_bootstrap_ci(signed_labels, [v < 1.0 for v in vol_scales], n_resamples, block_length, seed)
    if diff is None or low is None or high is None:
        verdict = "INCONCLUSIVE"
        statement = (
            "missing evidence (empty filter class or unformable resample) — INCONCLUSIVE, never promoted to a pass"
        )
    elif diff > 0.0 and low > 0.0:
        verdict = "SUCCESS"
        statement = (
            f"rate difference {diff:+.4f} with 90% block-bootstrap CI "
            f"[{low:+.4f}, {high:+.4f}] excluding 0 on the positive side — the "
            "preregistered criterion is met on this dataset"
        )
    else:
        verdict = "FAILURE"
        statement = (
            f"rate difference {diff:+.4f} with 90% block-bootstrap CI "
            f"[{low:+.4f}, {high:+.4f}] — the preregistered criterion is NOT met "
            "on this dataset"
        )
    slices = oos_window_slices(event_dates, vol_scales, signed_labels, train_bars, purge_bars, embargo_bars, test_bars)
    return B1Result(
        split=split,
        rate_difference=diff,
        ci_low=low,
        ci_high=high,
        ci_excludes_zero_positive=(verdict == "SUCCESS"),
        verdict=verdict,
        verdict_statement=statement,
        oos_slices=slices,
        n_bootstrap=n_resamples,
        block_length=block_length,
        seed=seed,
    )


def summarize(result: B1Result) -> Dict[str, object]:
    """JSON-safe summary for artifacts."""
    return {
        "n_taken": result.split.n_taken,
        "n_skipped": result.split.n_skipped,
        "rate_taken": result.split.rate_taken,
        "rate_skipped": result.split.rate_skipped,
        "rate_difference": result.rate_difference,
        "ci_90": [result.ci_low, result.ci_high],
        "verdict": result.verdict,
        "verdict_statement": result.verdict_statement,
        "n_oos_windows": len(result.oos_slices),
        "oos_window_rate_diffs": [s.rate_diff for s in result.oos_slices],
        "bootstrap": {"n": result.n_bootstrap, "block_length": result.block_length, "seed": result.seed},
    }
