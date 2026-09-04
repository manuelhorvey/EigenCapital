"""Universe Perturbation & Concentration Analysis.

Tests whether strategy depends excessively on specific instruments
or if performance is concentrated in a small subset.

Usage:
    result = universe_perturbation(
        instrument_returns={"ES": [0.01, 0.02], "NQ": [0.005, 0.01]},
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ConcentrationMetrics:
    """Concentration metrics for a portfolio of instruments.

    Attributes:
        instrument_contributions: P&L contribution per instrument
        top_n_concentration: % of P&L from top N instruments
        herfindahl_index: Herfindahl-Hirschman concentration index
        most_concentrated_instrument: Instrument with highest contribution
        concentration_warning: True if >50% from single instrument
    """

    instrument_contributions: Dict[str, float] = field(default_factory=dict)
    top_n_concentration: Dict[str, float] = field(default_factory=dict)
    herfindahl_index: float = 0.0
    most_concentrated_instrument: str = ""
    concentration_warning: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_contributions": {k: round(v, 6) for k, v in self.instrument_contributions.items()},
            "top_n_concentration": {str(k): round(v, 4) for k, v in self.top_n_concentration.items()},
            "herfindahl_index": round(self.herfindahl_index, 4),
            "most_concentrated_instrument": self.most_concentrated_instrument,
            "concentration_warning": self.concentration_warning,
        }


@dataclass(frozen=True)
class UniversePerturbationResult:
    """Results of universe perturbation analysis.

    Attributes:
        base_metrics: Metrics with full universe
        exclusion_results: Metrics when each instrument is excluded
        concentration: Concentration analysis
        single_instrument_dependency: True if one instrument dominates
        robustness_score: % of exclusion runs where Sharpe remains positive
    """

    base_metrics: Dict[str, float] = field(default_factory=dict)
    exclusion_results: Dict[str, Dict[str, float]] = field(default_factory=dict)
    concentration: ConcentrationMetrics = field(default_factory=ConcentrationMetrics)
    single_instrument_dependency: bool = False
    robustness_score: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_metrics": {k: round(v, 4) for k, v in self.base_metrics.items()},
            "exclusion_results": {
                k: {mk: round(mv, 4) for mk, mv in v.items()} for k, v in self.exclusion_results.items()
            },
            "concentration": self.concentration.to_dict(),
            "single_instrument_dependency": self.single_instrument_dependency,
            "robustness_score": round(self.robustness_score, 2),
        }


def compute_concentration(
    instrument_returns: Dict[str, List[float]],
) -> ConcentrationMetrics:
    """Compute concentration metrics.

    Args:
        instrument_returns: Dict mapping instrument → list of returns

    Returns:
        ConcentrationMetrics with concentration analysis
    """
    # Compute cumulative return per instrument
    contributions = {}
    for instrument, returns in instrument_returns.items():
        cumulative = 1.0
        for r in returns:
            cumulative *= 1 + r
        contributions[instrument] = cumulative - 1.0

    total_contribution = sum(abs(v) for v in contributions.values())
    if total_contribution == 0:
        return ConcentrationMetrics(instrument_contributions=contributions)

    # Normalize contributions
    normalized = {k: abs(v) / total_contribution for k, v in contributions.items()}

    # Herfindahl index
    hhi = sum(v**2 for v in normalized.values())

    # Top N concentration
    sorted_instruments = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
    top_n: Dict[str, float] = {}
    cumulative = 0.0
    for n in [1, 3, 5]:
        for i in range(min(n, len(sorted_instruments))):
            cumulative += sorted_instruments[i][1]
        top_n[str(n)] = cumulative
        cumulative = 0.0

    most_concentrated = sorted_instruments[0][0] if sorted_instruments else ""
    concentration_warning = sorted_instruments[0][1] > 0.5 if sorted_instruments else False

    return ConcentrationMetrics(
        instrument_contributions=contributions,
        top_n_concentration=top_n,
        herfindahl_index=hhi,
        most_concentrated_instrument=most_concentrated,
        concentration_warning=concentration_warning,
    )


def universe_perturbation(
    instrument_returns: Dict[str, List[float]],
) -> UniversePerturbationResult:
    """Perform universe perturbation analysis.

    Tests whether removing individual instruments significantly changes results.

    Args:
        instrument_returns: Dict mapping instrument → list of returns

    Returns:
        UniversePerturbationResult with exclusion analysis
    """
    if not instrument_returns:
        return UniversePerturbationResult()

    # Compute base metrics (full universe)
    all_returns = []
    for returns in instrument_returns.values():
        all_returns.extend(returns)

    base_sharpe = 0.0
    if len(all_returns) >= 2:
        mean_r = sum(all_returns) / len(all_returns)
        var_r = sum((r - mean_r) ** 2 for r in all_returns) / (len(all_returns) - 1)
        std_r = var_r**0.5
        if std_r > 1e-15:
            base_sharpe = mean_r / std_r * (252**0.5)

    base_metrics = {
        "sharpe": base_sharpe,
        "mean_return": sum(all_returns) / len(all_returns) if all_returns else 0.0,
    }

    # Exclusion analysis
    exclusion_results = {}
    sharpe_with_exclusion = []

    for excluded in instrument_returns:
        excluded_returns = []
        for inst, returns in instrument_returns.items():
            if inst != excluded:
                excluded_returns.extend(returns)

        if excluded_returns and len(excluded_returns) >= 2:
            mean_r = sum(excluded_returns) / len(excluded_returns)
            var_r = sum((r - mean_r) ** 2 for r in excluded_returns) / (len(excluded_returns) - 1)
            std_r = var_r**0.5
            excl_sharpe = mean_r / std_r * (252**0.5) if std_r > 1e-15 else 0.0
        else:
            excl_sharpe = 0.0

        exclusion_results[excluded] = {"sharpe_without": excl_sharpe}
        sharpe_with_exclusion.append(excl_sharpe)

    # Concentration
    concentration = compute_concentration(instrument_returns)

    # Single instrument dependency
    single_dep = concentration.concentration_warning

    # Robustness score: % of exclusions where Sharpe remains positive
    if sharpe_with_exclusion:
        positive_count = sum(1 for s in sharpe_with_exclusion if s > 0)
        robustness = (positive_count / len(sharpe_with_exclusion)) * 100
    else:
        robustness = 100.0

    return UniversePerturbationResult(
        base_metrics=base_metrics,
        exclusion_results=exclusion_results,
        concentration=concentration,
        single_instrument_dependency=single_dep,
        robustness_score=robustness,
    )
