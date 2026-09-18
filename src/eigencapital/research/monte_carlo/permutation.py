"""Trade-Sequence Permutation — R1 Phase B1 Monte Carlo diagnostic.

R1 Phase B1 (docs/research/R1_MONTE_CARLO.md): permute the ORDER of the
historical closed trades and rebuild the equity path for each permutation.

H₀ (frozen, review §12): Under the specified resampling mechanism, the
observed historical path is statistically consistent with the distribution of
alternative paths generated from the same trade population.

What permutation answers: **sequence risk** — how the SAME realized trades
behave under alternative orderings. It does not introduce new trades; the
resampled population is identical to the historical one.

Core invariant (frozen handoff, B1):

> Pure permutation must preserve the exact set of trades. Metrics that depend
> only on the unordered trade set (total P&L, trade count) are invariant;
> path-dependent metrics (drawdown, streaks, recovery) can change.

This module enforces that invariant numerically on every run and refuses to
produce results from a tampered or mismatched stream.

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

PERMUTATION_METHOD = "trade_sequence_permutation"

# Metric fields that must be IDENTICAL across all permutations (set-invariant).
SET_INVARIANT_FIELDS = ("total_pnl", "trade_count")


@dataclass(frozen=True)
class HistoricalPath:
    """The observed historical path and its metrics.

    Attributes:
        metrics: Path metrics of the chronological (as-observed) ordering.
        percentile: Position of the historical path WITHIN the simulated
            distribution for each path-dependent metric, expressed as the
            fraction of simulated paths strictly WORSE than historical
            (higher percentile = historical path was comparatively lucky/
            benign for that metric). Set-invariant metrics are 1.0 by
            construction (identical across permutations).
    """

    metrics: PathMetrics
    percentile: Dict[str, float]


@dataclass(frozen=True)
class PermutationResult:
    """Distributional summary of the permutation diagnostic.

    Attributes:
        method: Resampling method identifier (constant for B1).
        n_permutations: Number of alternative orderings simulated.
        seed: RNG seed (None = run was seeded from OS entropy and is not
            reproducible — always pass a seed for research evidence).
        historical: The observed path metrics and distributional percentiles.
        distributions: Per-metric simulated distributions (raw arrays;
            recovery_time entries may be None = never recovered).
        quantiles: Requested quantiles of each simulated distribution
            (computed over finite observations; never-recovered count reported
            separately as ``n_never_recovered``).
        set_invariance_verified: True when every permutation reproduced the
            historical total_pnl/trade_count exactly (enforced numerically).
    """

    method: str
    n_permutations: int
    seed: int | None
    historical: HistoricalPath
    distributions: Dict[str, List[float | None]]
    quantiles: Dict[str, Dict[str, float]]
    set_invariance_verified: bool

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization with explicit historical/simulated labeling."""
        return {
            "method": self.method,
            "n_permutations": self.n_permutations,
            "seed": self.seed,
            "historical": {
                "metrics": vars(self.historical.metrics),
                "percentile_in_simulated_distribution": self.historical.percentile,
            },
            "simulated_distributions": {metric: list(values) for metric, values in self.distributions.items()},
            "simulated_quantiles": self.quantiles,
            "set_invariance_verified": self.set_invariance_verified,
            "methodological_rule": (
                "Conditional diagnostic under the resampling assumption. "
                "NOT a forecast of future returns or probability of profitability."
            ),
        }


# Metrics whose simulated distribution is used for historical percentile
# comparison. Set-invariant metrics are excluded (constant by construction).
PATH_DEPENDENT_METRICS = (
    "max_drawdown",
    "max_drawdown_duration",
    "longest_losing_streak",
    "recovery_time",
    "min_equity",
    "time_under_water",
)

# For each metric: True = "higher is worse" (percentile = fraction of
# simulations worse than historical), False = "lower is worse".
_WORSE_IS_HIGHER: Dict[str, bool] = {
    "max_drawdown": True,
    "max_drawdown_duration": True,
    "longest_losing_streak": True,
    "recovery_time": True,
    "min_equity": False,
    "time_under_water": True,
}


def _historical_percentiles(
    historical: PathMetrics,
    distributions: Dict[str, List[float | None]],
) -> Dict[str, float]:
    """Fraction of simulated paths strictly worse than the historical path.

    None entries (recovery_time that never recovered within the path) count as
    strictly worse for every "higher is worse" metric, and never worse for
    "lower is worse" metrics — None is not a number and is never coerced.
    """
    percentiles: Dict[str, float] = {}
    n = len(next(iter(distributions.values()))) if distributions else 0
    for metric in PATH_DEPENDENT_METRICS:
        values = distributions.get(metric, [])
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


def run_permutation_test(
    stream: TradeStream,
    n_permutations: int = 1000,
    seed: int | None = None,
    initial_equity: float = 1.0,
    use_return_r: bool = False,
    quantiles: Sequence[float] = (0.05, 0.25, 0.5, 0.75, 0.95),
) -> PermutationResult:
    """Run the B1 trade-sequence permutation diagnostic.

    Args:
        stream: A verified persisted TradeStream (provenance must match).
        n_permutations: Number of alternative orderings to simulate.
        seed: RNG seed for reproducibility. Required for research evidence;
            allowed as None only for exploratory use.
        initial_equity: Starting equity for path reconstruction (default 1.0,
            return space).
        use_return_r: Use per-trade ``return_r`` instead of ``realized_pnl``.
        quantiles: Quantiles reported for each simulated distribution.

    Returns:
        PermutationResult with historical metrics, simulated distributions,
        and historical percentiles within the simulated distributions.

    Raises:
        TradeStreamError: On tampered provenance, invalid argument values, or
            violation of the set-invariance invariant.
    """
    if stream.provenance_hash != stream.compute_provenance_hash():
        raise TradeStreamError(f"refusing to run: stream {stream.stream_id} provenance hash does not match content")
    if n_permutations < 1:
        raise TradeStreamError(f"n_permutations must be >= 1, got {n_permutations}")
    for q in quantiles:
        if not 0.0 <= q <= 1.0:
            raise TradeStreamError(f"quantiles must be within [0, 1], got {q}")

    pnls = trade_pnls(stream, use_return_r=use_return_r)
    historical = compute_path_metrics(pnls, initial_equity=initial_equity)

    rng = np.random.default_rng(seed)
    pnls_array = np.asarray(pnls, dtype=float)

    metric_arrays: Dict[str, List[float | None]] = {name: [] for name in PATH_DEPENDENT_METRICS}

    for _ in range(n_permutations):
        permuted = rng.permutation(pnls_array)
        metrics = compute_path_metrics(permuted.tolist(), initial_equity=initial_equity)
        # Enforce the set-preservation invariant numerically.
        for field_name in SET_INVARIANT_FIELDS:
            hist_value = getattr(historical, field_name)
            sim_value = getattr(metrics, field_name)
            if field_name == "total_pnl":
                if abs(sim_value - hist_value) > 1e-9:
                    raise TradeStreamError(
                        f"set-invariance violation: permutation changed total P&L ({hist_value} -> {sim_value})"
                    )
            elif sim_value != hist_value:
                raise TradeStreamError("set-invariance violation: permutation changed trade count")
        for name in PATH_DEPENDENT_METRICS:
            metric_arrays[name].append(getattr(metrics, name))

    distributions: Dict[str, List[float | None]] = metric_arrays
    quantile_report: Dict[str, Dict[str, float]] = {}
    for name, values in distributions.items():
        # Quantiles computed over the finite (non-None) observations only;
        # the count of None (never-recovered) outcomes is reported beside them.
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

    return PermutationResult(
        method=PERMUTATION_METHOD,
        n_permutations=n_permutations,
        seed=seed,
        historical=HistoricalPath(
            metrics=historical,
            percentile=_historical_percentiles(historical, distributions),
        ),
        distributions=distributions,
        quantiles=quantile_report,
        set_invariance_verified=True,
    )
