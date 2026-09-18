"""IID Bootstrap — R1 Phase B2 Monte Carlo diagnostic.

R1 Phase B2 (docs/research/R1_MONTE_CARLO.md): resample the historical trade
population WITH replacement, holding the sample size equal to the observed
trade count, and rebuild an equity path per resample.

H₀ (frozen, review §12): Under the specified resampling mechanism, the
observed historical path is statistically consistent with the distribution of
alternative paths generated from the same trade population.

What bootstrap answers that permutation (B1) cannot: **sample uncertainty**.
B1 holds the realized trade population fixed and varies only its ordering.
B2 deliberately breaks that invariant — the resampled sequence may contain
duplicates and omissions — so **total P&L is expected to vary** across
resamples. This cleanly separates ordering uncertainty (B1) from sample
uncertainty (B2): where the historical total P&L and final equity sit inside
the bootstrap distribution indicates how sensitive the realized result is to
which trades happened to occur.

Shared machinery with B1: identical path metrics, identical provenance
refusal, identical historical-vs-simulated labeling and methodological rule.
The deliberately different invariant is explicit in code and output:
``set_invariance_expected = False``.

Methodological rule (NOT a falsification criterion): outputs are conditional
diagnostics under the resampling assumptions — never forecasts of future
returns, never a probability of future profitability.

IID caveat (recorded, enforced in B3): independent-with-replacement resampling
destroys serial clustering. If R4's outcomes are regime-dependent, IID
bootstrap understates path risk relative to block bootstrap; compare B2 and
B3 outputs rather than treating them as interchangeable.
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

BOOTSTRAP_METHOD = "iid_bootstrap_with_replacement"

# Same path-dependent metrics as B1: these vary across resamples.
PATH_DEPENDENT_METRICS = (
    "max_drawdown",
    "max_drawdown_duration",
    "longest_losing_streak",
    "recovery_time",
    "min_equity",
    "time_under_water",
)

# NEW for B2: set-dependent metrics whose variation is the point of this
# diagnostic. These are collected alongside the path-dependent metrics.
SAMPLE_DEPENDENT_METRICS = ("total_pnl", "final_equity")

# For percentile comparison: True = "higher is worse".
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
class BootstrapResult:
    """Distributional summary of the IID bootstrap diagnostic.

    Attributes:
        method: Resampling method identifier (constant for B2).
        n_resamples: Number of alternative samples simulated.
        seed: RNG seed (None = not reproducible; always pass a seed for
            research evidence).
        sample_size: Trades drawn per resample (equals the historical trade
            count by default).
        set_invariance_expected: Always False for B2 — duplicates and
            omissions are intended; total P&L is expected to vary.
        historical: The observed path metrics and distributional percentiles
            across ALL collected metrics (path- and sample-dependent).
        distributions: Per-metric simulated distributions (raw arrays;
            recovery_time entries may be None = never recovered).
        quantiles: Quantiles per distribution (finite observations only;
            ``n_never_recovered`` reported beside them where applicable).
    """

    method: str
    n_resamples: int
    seed: int | None
    sample_size: int
    set_invariance_expected: bool
    historical: HistoricalSample
    distributions: Dict[str, List[float | None]]
    quantiles: Dict[str, Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization with explicit historical/simulated labeling."""
        return {
            "method": self.method,
            "n_resamples": self.n_resamples,
            "seed": self.seed,
            "sample_size": self.sample_size,
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


@dataclass(frozen=True)
class HistoricalSample:
    """The observed historical path and its percentiles within the B2 distribution.

    Unlike B1, percentiles cover sample-dependent metrics too: the position of
    the realized total P&L / final equity inside the resampling distribution
    is the headline diagnostic of sample uncertainty.
    """

    metrics: PathMetrics
    percentile: Dict[str, float]


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


def run_bootstrap_test(
    stream: TradeStream,
    n_resamples: int = 1000,
    seed: int | None = None,
    initial_equity: float = 1.0,
    use_return_r: bool = False,
    sample_size: int | None = None,
    quantiles: Sequence[float] = (0.05, 0.25, 0.5, 0.75, 0.95),
) -> BootstrapResult:
    """Run the B2 IID bootstrap diagnostic.

    Args:
        stream: A verified persisted TradeStream (provenance must match).
        n_resamples: Number of alternative samples to simulate.
        seed: RNG seed for reproducibility. Required for research evidence;
            allowed as None only for exploratory use.
        initial_equity: Starting equity for path reconstruction (default 1.0,
            return space).
        use_return_r: Use per-trade ``return_r`` instead of ``realized_pnl``.
        sample_size: Trades drawn per resample. Defaults to the historical
            trade count. Must be >= 1.
        quantiles: Quantiles reported for each simulated distribution.

    Returns:
        BootstrapResult with historical metrics, simulated distributions
        (including sample-dependent total P&L and final equity), and
        historical percentiles.

    Raises:
        TradeStreamError: On tampered provenance, invalid argument values, or
            non-finite trade values.
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

    rng = np.random.default_rng(seed)
    pnls_array = np.asarray(pnls, dtype=float)

    all_metrics = PATH_DEPENDENT_METRICS + SAMPLE_DEPENDENT_METRICS
    metric_arrays: Dict[str, List[float | None]] = {name: [] for name in all_metrics}

    for _ in range(n_resamples):
        # IID resample WITH replacement: duplicates and omissions intended.
        sample = rng.choice(pnls_array, size=size, replace=True)
        metrics = compute_path_metrics(sample.tolist(), initial_equity=initial_equity)
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

    return BootstrapResult(
        method=BOOTSTRAP_METHOD,
        n_resamples=n_resamples,
        seed=seed,
        sample_size=size,
        set_invariance_expected=False,
        historical=HistoricalSample(
            metrics=historical,
            percentile=_historical_percentiles(historical, metric_arrays),
        ),
        distributions=metric_arrays,
        quantiles=quantile_report,
    )
