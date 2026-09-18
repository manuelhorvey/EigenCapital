"""Combined Evidence Report — R1 Phase B4 Monte Carlo aggregation.

R1 Phase B4 (docs/research/R1_MONTE_CARLO.md): consume the observed historical
path plus the three frozen resampling diagnostics — B1 permutation (order
sensitivity), B2 IID bootstrap (sampling uncertainty), B3 moving-block
bootstrap (dependence-aware sampling uncertainty) — and aggregate them into
ONE reproducible evidence artifact.

B4 is AGGREGATION ONLY. It invents no new statistical test, no new resampling,
and no pass/fail thresholds unless preregistered. It answers the six frozen
questions:

1. Where does the historical path sit within B1?
2. Where does it sit within B2?
3. Where does it sit within B3?
4. How wide are the three distributions?
5. Which diagnostics remain stable across resampling assumptions?
6. Which conclusions change when serial dependence is retained?

Mandatory labels (enforced in structure and rendering):
    OBSERVED HISTORICAL PATH — what actually happened in the observed sequence
    RESAMPLED DIAGNOSTIC DISTRIBUTION — alternative paths under one resampling
        assumption
    INTERPRETATION — what the comparison means, in percentile-of-experiment
        terms only

Wording guard (frozen): a percentile is a statement about the experiment that
was run, never a probability about the future. ``render_markdown`` prints the
correct/incorrect wording pair in every report so the distinction cannot
silently degrade into a forecast.

Scope guard (frozen): the report describes the exact stream it consumed
(id, period, trade count, provenance) and explicitly does NOT generalize the
stream to the strategy's long-run behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from eigencapital.research.monte_carlo.block_bootstrap import (
    BlockBootstrapResult,
)
from eigencapital.research.monte_carlo.bootstrap import BootstrapResult
from eigencapital.research.monte_carlo.permutation import PermutationResult
from eigencapital.research.monte_carlo.schema import TradeStream, TradeStreamError

REPORT_VERSION = "1"


@dataclass(frozen=True)
class MetricComparison:
    """One metric compared across the three resampling assumptions.

    Attributes:
        metric: Metric name.
        historical_value: The observed path's value.
        percentiles: Historical percentile within each resampled distribution
            (B1/B2/B3), expressed as fraction-of-experiment, NOT probability.
        quantiles: Key quantiles (q05/q50/q95) of each distribution.
        width_ratio: (q95 - q05) of each distribution relative to B2's width
            (B2 is the reference point for the dependence effect).
        dependence_delta_q95: B3 q95 minus B2 q95 for worse-is-higher
            metrics (B2 minus B3 for min-equity and total-P&L style metrics
            where lower is worse). Positive = retaining dependence widens
            the adverse tail.
    """

    metric: str
    historical_value: float | None
    percentiles: Dict[str, float | None]  # B1 may be None for set-invariant metrics
    quantiles: Dict[str, Dict[str, float]]
    width_ratio: Dict[str, float]
    dependence_delta_q95: float


@dataclass(frozen=True)
class EvidenceReport:
    """The combined B1/B2/B3 evidence artifact.

    Attributes:
        report_version: Report schema version.
        stream_scope: Exact provenance/coverage of the consumed stream
            (id, strategy, dataset, period, trade count, provenance hash).
        resampling_config: Seeds, iteration counts, and the B3 pre-specified
            block metadata (displayed prominently per the frozen contract).
        historical: OBSERVED HISTORICAL PATH metrics.
        comparisons: Per-metric comparisons across B1/B2/B3.
        stable_metrics: Metrics whose historical percentiles stay within
            ``stability_tolerance`` of each other across B1/B2/B3 (question 5).
        dependence_changed: Metrics whose B2 vs B3 q95 shift exceeds
            ``dependence_tolerance`` — the question-6 evidence.
        interpretation: Written interpretation lines referencing the correct
            wording (experiment-percentiles, never future probabilities).
        methodological_rule: The frozen rule, carried into the artifact.
    """

    report_version: str
    stream_scope: Dict[str, Any]
    resampling_config: Dict[str, Any]
    historical: Dict[str, Any]
    comparisons: List[MetricComparison]
    stable_metrics: List[str]
    dependence_changed: List[str]
    interpretation: List[str]
    methodological_rule: str

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization of the full evidence artifact."""
        return {
            "report_version": self.report_version,
            "stream_scope": self.stream_scope,
            "resampling_config": self.resampling_config,
            "observed_historical_path": self.historical,
            "resampled_diagnostic_distributions": {
                c.metric: {
                    "percentile_in_experiment": c.percentiles,
                    "quantiles": c.quantiles,
                    "width_ratio_vs_b2": c.width_ratio,
                    "dependence_delta_q95": c.dependence_delta_q95,
                }
                for c in self.comparisons
            },
            "stable_metrics": self.stable_metrics,
            "dependence_changed": self.dependence_changed,
            "interpretation": self.interpretation,
            "methodological_rule": self.methodological_rule,
        }


def _q(data: Dict[str, Dict[str, float]], key: str) -> float | None:
    entry = data.get(key)
    if entry is None:
        return None
    value = entry.get("q0.95")
    return float(value) if value is not None else None


def _worse_is_higher(metric: str) -> bool:
    return metric not in ("min_equity", "total_pnl", "final_equity")


def build_evidence_report(
    stream: TradeStream,
    permutation: PermutationResult,
    bootstrap: BootstrapResult,
    block_bootstrap: BlockBootstrapResult,
    stability_tolerance: float = 0.20,
    dependence_tolerance: float = 0.0,
) -> EvidenceReport:
    """Aggregate B1/B2/B3 into the combined evidence artifact.

    Args:
        stream: The persisted stream the diagnostics ran on (must match the
            strategy identity recorded in each result's owning experiment).
        permutation: B1 result.
        bootstrap: B2 result.
        block_bootstrap: B3 result (block length must be pre-specified).
        stability_tolerance: Max spread of historical percentiles across
            B1/B2/B3 for a metric to count as stable (question 5).
        dependence_tolerance: Min |B3-q95 - B2-q95| delta for a metric to
            count as materially changed by dependence (question 6). Default 0
            = report the sorted deltas, flag any positive one.

    Returns:
        The EvidenceReport artifact.

    Raises:
        TradeStreamError: On tampered stream provenance or mismatched
            historical metrics between the three diagnostics.
    """
    if stream.provenance_hash != stream.compute_provenance_hash():
        raise TradeStreamError(f"refusing to report: stream {stream.stream_id} provenance hash does not match content")
    # The three diagnostics must agree on the historical path they resampled.
    if (
        permutation.historical.metrics != bootstrap.historical.metrics
        or permutation.historical.metrics != block_bootstrap.historical.metrics
    ):
        raise TradeStreamError(
            "historical metrics disagree between B1/B2/B3 results — they were not run on the same stream/parameters"
        )

    hist = permutation.historical.metrics
    b1_pct = permutation.historical.percentile
    b2_pct = bootstrap.historical.percentile
    b3_pct = block_bootstrap.historical.percentile

    # B1 reports percentiles for PATH-DEPENDENT metrics only: set-invariant
    # metrics (total_pnl, final_equity) are identical in every permutation, so
    # the historical path is not "at a position" in B1 for them. We record
    # that fact explicitly (B1 percentile = None, rendered as "n/a (invariant)")
    # instead of manufacturing a number.

    comparisons: List[MetricComparison] = []
    for metric in (
        "max_drawdown",
        "max_drawdown_duration",
        "longest_losing_streak",
        "recovery_time",
        "min_equity",
        "time_under_water",
        "total_pnl",
        "final_equity",
    ):
        if metric not in bootstrap.quantiles or metric not in block_bootstrap.quantiles:
            continue
        q2 = bootstrap.quantiles[metric]
        q3 = block_bootstrap.quantiles[metric]
        width_b2 = (q2.get("q0.95", 0.0) - q2.get("q0.05", 0.0)) or 1e-12
        width_b3 = q3.get("q0.95", 0.0) - q3.get("q0.05", 0.0)
        width_b1 = (
            permutation.quantiles[metric].get("q0.95", 0.0) - permutation.quantiles[metric].get("q0.05", 0.0)
            if metric in permutation.quantiles
            else None
        )
        b2_q95 = _q(bootstrap.quantiles, metric)
        b3_q95 = _q(block_bootstrap.quantiles, metric)
        delta: float | None = None
        if b2_q95 is not None and b3_q95 is not None:
            delta = (b3_q95 - b2_q95) if _worse_is_higher(metric) else (b2_q95 - b3_q95)

        width_ratio: Dict[str, float] = {}
        if width_b1 is not None:
            width_ratio["B1"] = width_b1 / width_b2
        width_ratio["B2"] = 1.0
        width_ratio["B3"] = width_b3 / width_b2

        b1_percentile = b1_pct.get(metric)
        percentiles: Dict[str, float | None] = {
            "B1": b1_percentile,
            "B2": b2_pct[metric],
            "B3": b3_pct[metric],
        }

        comparisons.append(
            MetricComparison(
                metric=metric,
                historical_value=getattr(hist, metric),
                percentiles=percentiles,
                quantiles={
                    "B1": permutation.quantiles.get(metric, {}),
                    "B2": q2,
                    "B3": q3,
                },
                width_ratio=width_ratio,
                dependence_delta_q95=float(delta) if delta is not None else 0.0,
            )
        )

    # Question 5: metrics stable across assumptions (percentile spread small).
    # Set-invariant-under-B1 metrics have no B1 percentile; their spread is
    # computed across B2/B3 only — recorded as such, not silently filled.
    stable_metrics = []
    for c in comparisons:
        available = [p for p in c.percentiles.values() if p is not None]
        if available and (max(available) - min(available)) <= stability_tolerance:
            stable_metrics.append(c.metric)
    # Question 6: metrics materially changed by retaining dependence.
    dependence_changed = [c.metric for c in comparisons if c.dependence_delta_q95 > dependence_tolerance]
    dependence_changed.sort(key=lambda m: -next(c.dependence_delta_q95 for c in comparisons if c.metric == m))

    first_date = stream.trades[0].entry_timestamp
    last_date = stream.trades[-1].exit_timestamp
    stream_scope = {
        "stream_id": stream.stream_id,
        "experiment_id": stream.experiment_id,
        "strategy_id": stream.strategy_id,
        "strategy_version": stream.strategy_version,
        "dataset_id": stream.dataset_id,
        "dataset_version": stream.dataset_version,
        "git_commit": stream.git_commit,
        "cost_model_id": stream.cost_model_id,
        "period": {"first_entry": first_date, "last_exit": last_date},
        "n_trades": len(stream.trades),
        "provenance_hash": stream.provenance_hash,
        "scope_statement": (
            "This report describes exactly the persisted trade stream identified "
            "above. It is a persisted historical trade stream and NOT a claim "
            "about the strategy's long-run behavior."
        ),
    }

    resampling_config = {
        "B1": {
            "method": permutation.method,
            "n_permutations": permutation.n_permutations,
            "seed": permutation.seed,
        },
        "B2": {
            "method": bootstrap.method,
            "n_resamples": bootstrap.n_resamples,
            "seed": bootstrap.seed,
            "sample_size": bootstrap.sample_size,
        },
        "B3": {
            "method": block_bootstrap.method,
            "n_resamples": block_bootstrap.n_resamples,
            "seed": block_bootstrap.seed,
            "sample_size": block_bootstrap.sample_size,
            # Prominent per frozen contract: auditability of the pre-specification.
            "block_length_prespecified": block_bootstrap.block_length,
            "block_method": block_bootstrap.block_method,
            "blocks_per_resample": block_bootstrap.n_blocks_per_resample,
            "block_length_note": (
                "Block length was pre-specified, not selected. It is not claimed "
                "to be universally optimal; its interaction with the dependence "
                "structure is a separate later study."
            ),
        },
        "stability_tolerance": stability_tolerance,
        "dependence_tolerance": dependence_tolerance,
    }

    interpretation = _build_interpretation(comparisons, stable_metrics, dependence_changed)

    return EvidenceReport(
        report_version=REPORT_VERSION,
        stream_scope=stream_scope,
        resampling_config=resampling_config,
        historical={
            "metrics": vars(hist),
            "percentile_note": (
                "Percentiles below are the position of the OBSERVED path inside "
                "each RESAMPLED DIAGNOSTIC DISTRIBUTION — a statement about the "
                "experiment that was run."
            ),
        },
        comparisons=comparisons,
        stable_metrics=stable_metrics,
        dependence_changed=dependence_changed,
        interpretation=interpretation,
        methodological_rule=(
            "Monte Carlo diagnoses robustness of the realized evidence under "
            "specified resampling assumptions. It does NOT produce a probability "
            "that the strategy will make money in the future."
        ),
    )


def _build_interpretation(
    comparisons: List[MetricComparison],
    stable_metrics: List[str],
    dependence_changed: List[str],
) -> List[str]:
    """Written interpretation lines using only experiment-percentile wording."""
    lines: List[str] = []
    for c in comparisons:
        if c.metric == "max_drawdown":
            lines.append(
                f"The observed maximum drawdown lies at the "
                f"{c.percentiles['B1']:.0%} / {c.percentiles['B2']:.0%} / "
                f"{c.percentiles['B3']:.0%} percentile of the B1/B2/B3 resampled "
                "maximum-drawdown distributions."
            )
    if stable_metrics:
        lines.append(
            "Stable across resampling assumptions (historical percentile spread "
            f"<= tolerance): {', '.join(stable_metrics)}."
        )
    if dependence_changed:
        lines.append(
            "Materially changed when serial dependence is retained (B3 vs B2 "
            f"adverse q95): {', '.join(dependence_changed)}. This difference "
            "itself is evidence: IID resampling understates these tails for "
            "this stream."
        )
    else:
        lines.append(
            "No diagnostic materially changed when serial dependence was "
            "retained (B3 vs B2 adverse q95 deltas within tolerance) for this "
            "stream."
        )
    lines.append(
        "All percentiles in this report describe the experiment that was run. "
        "None is a probability about future outcomes."
    )
    return lines


def render_markdown(report: EvidenceReport) -> str:
    """Render the evidence artifact as an auditable Markdown report.

    Keeps the three frozen labels visible and prints the correct/incorrect
    percentile-wording pair in every report.
    """
    lines: List[str] = []
    scope = report.stream_scope
    b3 = report.resampling_config["B3"]

    lines.append("# R1-B4 Monte Carlo Evidence Report")
    lines.append("")
    lines.append(f"Report version: {report.report_version}")
    lines.append("")
    lines.append("## Scope (exact stream consumed)")
    lines.append("")
    lines.append(f"- Stream: `{scope['stream_id']}` (experiment `{scope['experiment_id']}`)")
    lines.append(
        f"- Strategy: {scope['strategy_id']} {scope['strategy_version']} | "
        f"Dataset: {scope['dataset_id']} {scope['dataset_version']} | "
        f"Cost model: {scope['cost_model_id']}"
    )
    lines.append(
        f"- Period: {scope['period']['first_entry']} → {scope['period']['last_exit']} | "
        f"Trades: {scope['n_trades']} | Provenance: `{scope['provenance_hash'][:16]}...`"
    )
    lines.append(f"- {scope['scope_statement']}")
    lines.append("")
    lines.append("## Resampling configuration (as run)")
    lines.append("")
    for stage in ("B1", "B2", "B3"):
        cfg = report.resampling_config[stage]
        lines.append(
            f"- **{stage}** ({cfg['method']}): n={cfg.get('n_permutations', cfg.get('n_resamples'))}, seed={cfg.get('seed')}"
        )
    lines.append(
        f"- **B3 method: {b3['block_method']} | Block length: "
        f"{b3['block_length_prespecified']} (pre-specified) | Blocks per resample: "
        f"{b3['blocks_per_resample']}**"
    )
    lines.append(f"- {b3['block_length_note']}")
    lines.append("")

    lines.append("## OBSERVED HISTORICAL PATH")
    lines.append("")
    hist = report.historical["metrics"]
    lines.append(
        f"total_pnl={hist['total_pnl']:+.4f} | trades={hist['trade_count']} | "
        f"max_drawdown={hist['max_drawdown']:.4f} | longest_loss_streak={hist['longest_losing_streak']}"
    )
    lines.append(f"- {report.historical['percentile_note']}")
    lines.append("")

    lines.append("## RESAMPLED DIAGNOSTIC DISTRIBUTIONS (comparison per metric)")
    lines.append("")
    lines.append("| Metric | Historical | B1 pct | B2 pct | B3 pct | width B1/B2 | width B3/B2 | dep. Δq95 (B3−B2) |")
    lines.append("|--------|-----------:|-------:|-------:|-------:|------------:|------------:|------------------:|")
    for c in report.comparisons:
        hist_val = "None" if c.historical_value is None else f"{c.historical_value:+.4f}"
        b1_pct_cell = "n/a (invariant)" if c.percentiles["B1"] is None else f"{c.percentiles['B1']:.3f}"
        lines.append(
            f"| {c.metric} | {hist_val} | {b1_pct_cell} | "
            f"{c.percentiles['B2']:.3f} | {c.percentiles['B3']:.3f} | "
            f"{c.width_ratio.get('B1', float('nan')):.2f} | {c.width_ratio['B3']:.2f} | "
            f"{c.dependence_delta_q95:+.4f} |"
        )
    lines.append("")

    lines.append("## INTERPRETATION")
    lines.append("")
    for line in report.interpretation:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "*Note:* B1 percentiles are shown as `n/a (invariant)` for metrics that "
        "are identical in every permutation (set-invariant under order-only "
        "resampling) — no percentile exists there to report."
    )
    lines.append("")
    lines.append("**Wording guard (applies to every number in this report):**")
    lines.append("")
    lines.append(
        '> **Correct:** "The observed maximum drawdown lies at the 72nd percentile of the B3 resampled maximum-drawdown distribution."'
    )
    lines.append(">")
    lines.append('> **Incorrect:** "There is a 72% probability that future maximum drawdown will be worse."')
    lines.append(">")
    lines.append(
        "> The first describes the experiment that was run. The second would turn the resampling diagnostic into a future forecast, which the frozen methodology explicitly rejects."
    )
    lines.append("")
    lines.append(f"**Methodological rule:** {report.methodological_rule}")
    lines.append("")
    return "\n".join(lines)
