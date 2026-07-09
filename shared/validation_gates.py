"""Validation gates for model deployment decisions.

Each gate is a pure function that returns a GateResult with pass/fail status,
metrics, and a recommendation message. The gates are designed to be called
before promoting a shadow model to production via the model registry.

Usage:
    gates = run_validation_gates(asset, incumbent_metrics, candidate_metrics)
    if all(g.passed for g in gates):
        deploy_version(asset, candidate_version)
    else:
        for g in gates:
            if not g.passed:
                logger.warning("Gate failed: %s", g.message)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.validation_gates")


@dataclass
class GateResult:
    """Result of a single validation gate."""

    name: str
    passed: bool
    metric_name: str = ""
    metric_value: float | None = None
    threshold: float | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _paired_t_test(
    incumbent_returns: np.ndarray,
    candidate_returns: np.ndarray,
) -> tuple[float, float]:
    """One-sided paired t-test: candidate > incumbent.

    Returns (t_statistic, p_value).
    """
    diffs = candidate_returns - incumbent_returns
    n = len(diffs)
    if n < 2:
        return 0.0, 1.0
    mean_diff = np.mean(diffs)
    std_diff = np.std(diffs, ddof=1)
    if std_diff < 1e-10:
        return float("inf") if mean_diff > 0 else 0.0, 0.0 if mean_diff > 0 else 1.0
    t_stat = mean_diff / (std_diff / np.sqrt(n))
    # One-sided p-value
    from scipy.stats import t as t_dist
    p_value = 1.0 - t_dist.cdf(t_stat, df=n - 1)
    return float(t_stat), float(p_value)


def gate_sharpe_improvement(
    incumbent_sharpe: float,
    candidate_sharpe: float,
    min_delta: float = 0.0,
    max_degradation: float = 0.2,
) -> GateResult:
    """Gate: candidate Sharpe must not be worse than incumbent by > max_degradation.

    Passes if: candidate_sharpe >= incumbent_sharpe - max_degradation
    """
    delta = candidate_sharpe - incumbent_sharpe
    passed = delta >= -max_degradation
    return GateResult(
        name="sharpe_improvement",
        passed=passed,
        metric_name="sharpe_delta",
        metric_value=round(delta, 4),
        threshold=-max_degradation,
        message=(
            f"Sharpe {incumbent_sharpe:.3f} → {candidate_sharpe:.3f} "
            f"(Δ={delta:+.3f}, threshold={-max_degradation:.1f})"
        ),
        details={"incumbent": incumbent_sharpe, "candidate": candidate_sharpe, "delta": delta},
    )


def gate_ece_not_worse(
    incumbent_ece: float | None,
    candidate_ece: float | None,
    max_degradation: float = 0.05,
) -> GateResult:
    """Gate: candidate ECE must not be worse than incumbent by > max_degradation.

    If either ECE is None (unavailable), the gate passes with a warning.
    """
    if incumbent_ece is None or candidate_ece is None:
        return GateResult(
            name="ece_not_worse",
            passed=True,
            metric_name="ece_delta",
            metric_value=None,
            message="ECE data unavailable — gate deferred",
        )
    delta = candidate_ece - incumbent_ece
    passed = delta <= max_degradation
    return GateResult(
        name="ece_not_worse",
        passed=passed,
        metric_name="ece_delta",
        metric_value=round(delta, 4),
        threshold=max_degradation,
        message=(
            f"ECE {incumbent_ece:.4f} → {candidate_ece:.4f} "
            f"(Δ={delta:+.4f}, threshold={max_degradation:.2f})"
        ),
        details={"incumbent": incumbent_ece, "candidate": candidate_ece, "delta": delta},
    )


def gate_ic_positive(
    candidate_ic: float | None,
    min_ic: float = 0.0,
) -> GateResult:
    """Gate: candidate IC must be positive (or above min_ic).

    Passes if: candidate_ic >= min_ic
    """
    if candidate_ic is None:
        return GateResult(
            name="ic_positive",
            passed=True,
            message="IC data unavailable — gate deferred",
        )
    passed = candidate_ic >= min_ic
    return GateResult(
        name="ic_positive",
        passed=passed,
        metric_name="candidate_ic",
        metric_value=round(candidate_ic, 4),
        threshold=min_ic,
        message=f"IC = {candidate_ic:.4f} (threshold >= {min_ic:.2f})",
        details={"candidate_ic": candidate_ic},
    )


def gate_statistical_significance(
    incumbent_returns: np.ndarray | None,
    candidate_returns: np.ndarray | None,
    p_threshold: float = 0.10,
) -> GateResult:
    """Gate: candidate outperforms incumbent with statistical significance.

    One-sided paired t-test. Passes if p < p_threshold.
    Deferred if insufficient data (< 10 paired observations).
    """
    if incumbent_returns is None or candidate_returns is None:
        return GateResult(
            name="statistical_significance",
            passed=True,
            message="Return data unavailable — gate deferred",
        )
    if len(incumbent_returns) < 10 or len(candidate_returns) < 10:
        return GateResult(
            name="statistical_significance",
            passed=True,
            message=f"Insufficient observations ({len(incumbent_returns)}, {len(candidate_returns)}) — "
                    f"gate deferred (need >= 10)",
        )
    t_stat, p_value = _paired_t_test(incumbent_returns, candidate_returns)
    passed = p_value < p_threshold
    return GateResult(
        name="statistical_significance",
        passed=passed,
        metric_name="p_value",
        metric_value=round(p_value, 4),
        threshold=p_threshold,
        message=f"Paired t-test: t={t_stat:.3f}, p={p_value:.4f} (threshold < {p_threshold:.2f})",
        details={"t_statistic": t_stat, "p_value": p_value, "n": len(incumbent_returns)},
    )


def gate_drawdown_not_worse(
    incumbent_max_dd: float | None,
    candidate_max_dd: float | None,
    max_degradation: float = 0.20,
) -> GateResult:
    """Gate: candidate max drawdown must not exceed incumbent by > max_degradation.

    max_degradation is absolute (e.g., 0.20 = 20 percentage points worse).
    """
    if incumbent_max_dd is None or candidate_max_dd is None:
        return GateResult(
            name="drawdown_not_worse",
            passed=True,
            message="Drawdown data unavailable — gate deferred",
        )
    dd_degradation = abs(candidate_max_dd) - abs(incumbent_max_dd)
    # A more negative DD is worse. Degradation is positive when candidate DD
    # exceeds incumbent DD in absolute terms (e.g., -10% → -40% = +0.30).
    passed = dd_degradation <= max_degradation
    return GateResult(
        name="drawdown_not_worse",
        passed=passed,
        metric_name="dd_degradation",
        metric_value=round(dd_degradation, 4),
        threshold=max_degradation,
        message=(
            f"Max DD {incumbent_max_dd:.2%} → {candidate_max_dd:.2%} "
            f"(degradation={dd_degradation:+.2%}, threshold={max_degradation:.0%})"
        ),
        details={"incumbent": incumbent_max_dd, "candidate": candidate_max_dd, "degradation": dd_degradation},
    )


def run_validation_gates(
    asset: str,
    incumbent: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    incumbent_returns: np.ndarray | None = None,
    candidate_returns: np.ndarray | None = None,
) -> list[GateResult]:
    """Run all validation gates comparing candidate against incumbent.

    Args:
        asset: Asset name (for logging).
        incumbent: Metrics dict for the current production model.
        candidate: Metrics dict for the candidate model.
        incumbent_returns: Per-trade returns for incumbent (R-multiples).
        candidate_returns: Per-trade returns for candidate (R-multiples).

    Returns:
        List of GateResult objects, one per gate.
    """
    results: list[GateResult] = []

    # Sharpe improvement gate
    results.append(gate_sharpe_improvement(
        incumbent_sharpe=float(incumbent.get("oos_sharpe", -999)) if incumbent else -999,
        candidate_sharpe=float(candidate.get("oos_sharpe", -999)) if candidate else -999,
    ))

    # ECE gate
    results.append(gate_ece_not_worse(
        incumbent_ece=incumbent.get("ece") if incumbent else None,
        candidate_ece=candidate.get("ece") if candidate else None,
    ))

    # IC gate
    results.append(gate_ic_positive(
        candidate_ic=candidate.get("oos_ic") if candidate else None,
    ))

    # Statistical significance gate
    results.append(gate_statistical_significance(
        incumbent_returns=incumbent_returns,
        candidate_returns=candidate_returns,
    ))

    # Drawdown gate
    results.append(gate_drawdown_not_worse(
        incumbent_max_dd=incumbent.get("oos_max_dd") if incumbent else None,
        candidate_max_dd=candidate.get("oos_max_dd") if candidate else None,
    ))

    n_passed = sum(1 for r in results if r.passed)
    n_total = len(results)
    logger.info(
        "%s: validation gates %d/%d passed",
        asset, n_passed, n_total,
    )
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        logger.info("  [%s] %s: %s", status, r.name, r.message)

    return results
