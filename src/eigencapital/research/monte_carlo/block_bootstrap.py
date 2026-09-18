"""Block Bootstrap (moving-block) — R1 Phase B3 Monte Carlo diagnostic.

R1 Phase B3 (docs/research/R1_MONTE_CARLO.md, contract frozen before
implementation): resample CONTIGUOUS BLOCKS of the historical trade sequence
with replacement, preserving short-run serial dependence that IID bootstrap
(B2) destroys.

H₀ (frozen, review §12): Under the specified resampling mechanism, the
observed historical path is statistically consistent with the distribution of
alternative paths generated from the same trade population.

Frozen conceptual contract (verbatim from the ledger):

> B3 tests sampling uncertainty while preserving contiguous short-run trade
> dependence through block resampling. It does not test future profitability,
> parameter robustness, overfitting, or regime stationarity.

The one question this module answers: **does the evidence materially change
when the IID assumption is relaxed?** Not: "does B3 produce a better-looking
distribution?"

Implementation contract (frozen):
- ``block_length`` is REQUIRED and PRE-SPECIFIED. There is deliberately no
  default and no search: candidate-size selection would create a researcher
  degree of freedom ("we found the correct block size"). Block-length
  sensitivity belongs to a separate later study if evidence warrants it.
- Moving-block construction: all contiguous blocks of length L are formed
  from the historical sequence, sampled with replacement, concatenated until
  the requested sample length is reached, then truncated to exactly that
  length.
- Contract boundary: B1 holds the trade set fixed (total P&L invariant); B2
  samples trades with replacement (P&L varies); B3 samples BLOCKS with
  replacement — blocks duplicated/omitted, therefore individual trades
  duplicated/omitted, therefore total P&L varies. The result exposes
  ``set_invariance_expected = False`` plus ``block_length`` and
  ``block_method`` so B1/B2/B3 are structurally comparable.

Methodological rule (NOT a falsification criterion): outputs are conditional
diagnostics under the resampling assumptions — never forecasts of future
returns, never a probability of future profitability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

import numpy as np

from eigencapital.research.monte_carlo.path_metrics import (
    PathMetrics,
    compute_path_metrics,
    trade_pnls,
)
from eigencapital.research.monte_carlo.schema import TradeStream, TradeStreamError

BLOCK_BOOTSTRAP_METHOD = "moving_block_bootstrap"

# Same metric families as B2: sample-dependent metrics are collected because
# total P&L / final equity vary under block resampling.
PATH_DEPENDENT_METRICS = (
    "max_drawdown",
    "max_drawdown_duration",
    "longest_losing_streak",
    "recovery_time",
    "min_equity",
    "time_under_water",
)
SAMPLE_DEPENDENT_METRICS = ("total_pnl", "final_equity")

_WORSE_IS_HIGHER: Dict[str, bool] = {
    "max_drawdown": True,
    "max_drawdown_duration": True,
    "longest_losing_streak": True,
    "recovery_time": True,
    "min_equity": False,
    "time_under_water": True,
    "total_pnl": False,
    "final_equity": False,
}


@dataclass(frozen=True)
class HistoricalBlockSample:
    """Observed path metrics and percentiles within the B3 distribution."""

    metrics: PathMetrics
    percentile: Dict[str, float]


@dataclass(frozen=True)
class BlockBootstrapResult:
    """Distributional summary of the moving-block bootstrap diagnostic.

    Attributes:
        method: Resampling method identifier (constant for B3).
        n_resamples: Number of alternative block-samples simulated.
        seed: RNG seed (None = not reproducible; always pass a seed for
            research evidence).
        sample_size: Trades drawn per resample (default: historical count).
        block_length: Pre-specified contiguous block length L (required arg).
        block_method: Block construction method ("moving_block").
        n_blocks_per_resample: Blocks concatenated before truncation.
        set_invariance_expected: Always False for B3 — blocks duplicated or
            omitted; total P&L is expected to vary.
        historical: Observed path metrics and percentiles across all
            collected metrics (path- and sample-dependent).
        distributions: Per-metric simulated distributions (raw arrays;
            recovery_time entries may be None = never recovered).
        quantiles: Quantiles per distribution (finite observations only;
            ``n_never_recovered`` reported beside them where applicable).
    """

    method: str
    n_resamples: int
    seed: int | None
    sample_size: int
    block_length: int
    block_method: str
    n_blocks_per_resample: int
    set_invariance_expected: bool
    historical: HistoricalBlockSample
    distributions: Dict[str, List[float | None]]
    quantiles: Dict[str, Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization with explicit historical/simulated labeling."""
        return {
            "method": self.method,
            "n_resamples": self.n_resamples,
            "seed": self.seed,
            "sample_size": self.sample_size,
            "block_length": self.block_length,
            "block_method": self.block_method,
            "n_blocks_per_resample": self.n_blocks_per_resample,
            "set_invariance_expected": self.set_invariance_expected,
            "historical": {
                "metrics": vars(self.historical.metrics),
                "percentile_in_simulated_distribution": self.historical.percentile,
            },
            "simulated_distributions": {metric: list(values) for metric, values in self.distributions.items()},
            "simulated_quantiles": self.quantiles,
            "methodological_rule": (
                "Conditional diagnostic under the resampling assumption. "
                "NOT a forecast of future returns or probability of profitability."
            ),
        }


def moving_block_sample(
    pnls: Sequence[float],
    block_length: int,
    sample_size: int,
    rng: np.random.Generator,
) -> List[float]:
    """One moving-block resample: contiguous blocks, replacement, truncation.

    Pure function of (pnls, block_length, sample_size, rng state).

    Args:
        pnls: Historical trade P&Ls in chronological order.
        block_length: Contiguous block length L (1 <= L <= len(pnls)).
        sample_size: Desired output length (truncation after concatenation).
        rng: Seeded numpy Generator.

    Returns:
        The resampled P&L sequence of exactly ``sample_size`` entries.
    """
    n = len(pnls)
    array = np.asarray(pnls, dtype=float)
    n_blocks = n - block_length + 1  # number of contiguous start positions
    blocks_needed = int(np.ceil(sample_size / block_length))
    starts = rng.integers(0, n_blocks, size=blocks_needed)
    sampled: List[float] = []
    for start in starts:
        sampled.extend(array[start : start + block_length].tolist())
    return sampled[:sample_size]


def _historical_percentiles(
    historical: PathMetrics,
    distributions: Dict[str, List[float | None]],
) -> Dict[str, float]:
    """Fraction of simulated paths strictly worse than the historical path.

    None entries (never-recovered) count as strictly worse for every
    "higher is worse" metric, and never worse for "lower is worse" metrics.
    """
    percentiles: Dict[str, float] = {}
    n = len(next(iter(distributions.values()))) if distributions else 0
    for metric, values in distributions.items():
        if not values:
            percentiles[metric] = 1.0
            continue
        hist_value = getattr(historical, metric)
        worse_higher = _WORSE_IS_HIGHER[metric]
        if worse_higher:
            count = sum(1 for v in values if v is None or (hist_value is not None and v > hist_value))
        else:
            count = sum(1 for v in values if v is not None and hist_value is not None and v < hist_value)
        percentiles[metric] = (count + 1) / (n + 1)  # add-one smoothing
    return percentiles


def run_block_bootstrap_test(
    stream: TradeStream,
    block_length: int,
    n_resamples: int = 1000,
    seed: int | None = None,
    initial_equity: float = 1.0,
    use_return_r: bool = False,
    sample_size: int | None = None,
    quantiles: Sequence[float] = (0.05, 0.25, 0.5, 0.75, 0.95),
) -> BlockBootstrapResult:
    """Run the B3 moving-block bootstrap diagnostic.

    Args:
        stream: A verified persisted TradeStream (provenance must match).
        block_length: PRE-SPECIFIED contiguous block length L
            (1 <= L <= trade count). Required — no default, no search.
        n_resamples: Number of alternative block-samples to simulate.
        seed: RNG seed for reproducibility. Required for research evidence;
            allowed as None only for exploratory use.
        initial_equity: Starting equity for path reconstruction (default 1.0,
            return space).
        use_return_r: Use per-trade ``return_r`` instead of ``realized_pnl``.
        sample_size: Trades drawn per resample. Defaults to the historical
            trade count. Must be >= 1.
        quantiles: Quantiles reported for each simulated distribution.

    Returns:
        BlockBootstrapResult with block metadata, historical metrics,
        simulated distributions, and historical percentiles.

    Raises:
        TradeStreamError: On tampered provenance, invalid argument values
            (including out-of-range block_length), or non-finite values.
    """
    if stream.provenance_hash != stream.compute_provenance_hash():
        raise TradeStreamError(f"refusing to run: stream {stream.stream_id} provenance hash does not match content")
    if n_resamples < 1:
        raise TradeStreamError(f"n_resamples must be >= 1, got {n_resamples}")
    for q in quantiles:
        if not 0.0 <= q <= 1.0:
            raise TradeStreamError(f"quantiles must be within [0, 1], got {q}")

    pnls = trade_pnls(stream, use_return_r=use_return_r)
    historical = compute_path_metrics(pnls, initial_equity=initial_equity)
    size = sample_size if sample_size is not None else len(pnls)
    if size < 1:
        raise TradeStreamError(f"sample_size must be >= 1, got {size}")
    if not 1 <= block_length <= len(pnls):
        raise TradeStreamError(
            f"block_length must be within [1, {len(pnls)}] (pre-specified, no search), got {block_length}"
        )

    rng = np.random.default_rng(seed)
    all_metrics = PATH_DEPENDENT_METRICS + SAMPLE_DEPENDENT_METRICS
    metric_arrays: Dict[str, List[float | None]] = {name: [] for name in all_metrics}

    for _ in range(n_resamples):
        sample = moving_block_sample(pnls, block_length, size, rng)
        metrics = compute_path_metrics(sample, initial_equity=initial_equity)
        for name in all_metrics:
            metric_arrays[name].append(getattr(metrics, name))

    quantile_report: Dict[str, Dict[str, float]] = {}
    for name, values in metric_arrays.items():
        finite = [v for v in values if v is not None]
        if finite:
            arr = np.asarray(finite, dtype=float)
            qs = np.quantile(arr, list(quantiles))
            entry = {f"q{q:g}": float(v) for q, v in zip(quantiles, qs)}
            n_none = len(values) - len(finite)
            if n_none:
                entry["n_never_recovered"] = float(n_none)
            quantile_report[name] = entry
        else:
            quantile_report[name] = {"n_never_recovered": float(len(values))}

    return BlockBootstrapResult(
        method=BLOCK_BOOTSTRAP_METHOD,
        n_resamples=n_resamples,
        seed=seed,
        sample_size=size,
        block_length=block_length,
        block_method="moving_block",
        n_blocks_per_resample=int(np.ceil(size / block_length)),
        set_invariance_expected=False,
        historical=HistoricalBlockSample(
            metrics=historical,
            percentile=_historical_percentiles(historical, metric_arrays),
        ),
        distributions=metric_arrays,
        quantiles=quantile_report,
    )
