"""Parameter Sensitivity Analysis — robustness of strategy to parameter changes.

A strategy that works only at exact parameter values is likely overfit.
A genuine edge should survive modest perturbations.

Usage:
    result = parameter_sensitivity(
        base_sharpe=1.5,
        parameter_results={"lookback": [1.2, 1.5, 1.4], "threshold": [1.3, 1.5, 1.1]},
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Any


@dataclass(frozen=True)
class ParameterSensitivity:
    """Sensitivity of a single parameter.

    Attributes:
        parameter: Parameter name
        values: Tested values
        sharpes: Corresponding Sharpe ratios
        is_plateau: True if Sharpe remains stable across values
        min_sharpe: Worst-case Sharpe
        max_sharpe: Best-case Sharpe
        sharpe_std: Std of Sharpe across values
    """
    parameter: str
    values: List[float] = field(default_factory=list)
    sharpes: List[float] = field(default_factory=list)
    is_plateau: bool = True
    min_sharpe: float = 0.0
    max_sharpe: float = 0.0
    sharpe_std: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "parameter": self.parameter,
            "values": self.values,
            "sharpes": [round(s, 4) for s in self.sharpes],
            "is_plateau": self.is_plateau,
            "min_sharpe": round(self.min_sharpe, 4),
            "max_sharpe": round(self.max_sharpe, 4),
            "sharpe_std": round(self.sharpe_std, 4),
        }


@dataclass(frozen=True)
class SensitivityResult:
    """Results of parameter sensitivity analysis.

    Attributes:
        base_sharpe: Sharpe at default parameters
        parameters: Per-parameter sensitivity analysis
        overall_robust: True if all parameters are plateau
        degradation_threshold: Max acceptable Sharpe drop from base
        worst_case_sharpe: Worst Sharpe across all parameter combinations
    """
    base_sharpe: float = 0.0
    parameters: List[ParameterSensitivity] = field(default_factory=list)
    overall_robust: bool = True
    degradation_threshold: float = 0.3
    worst_case_sharpe: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "base_sharpe": round(self.base_sharpe, 4),
            "overall_robust": self.overall_robust,
            "worst_case_sharpe": round(self.worst_case_sharpe, 4),
            "degradation_threshold": self.degradation_threshold,
            "parameters": [p.to_dict() for p in self.parameters],
        }


def parameter_sensitivity(
    base_sharpe: float,
    parameter_results: Dict[str, List[float]],
    values_per_param: Dict[str, List[float]] = None,
    degradation_threshold: float = 0.3,
) -> SensitivityResult:
    """Analyze parameter sensitivity.

    For each parameter, checks if Sharpe remains stable (plateau)
    or collapses (spike) as the parameter changes.

    Args:
        base_sharpe: Sharpe at default parameter values
        parameter_results: Dict mapping parameter name → list of Sharpes
                          at perturbed values
        values_per_param: Dict mapping parameter name → list of tested values
        degradation_threshold: Max acceptable Sharpe drop from base (default: 0.3)

    Returns:
        SensitivityResult with per-parameter and overall analysis
    """
    sensitivities = []
    worst_sharpe = base_sharpe
    all_plateau = True

    for param_name, sharpes in parameter_results.items():
        if not sharpes:
            continue

        values = values_per_param.get(param_name, list(range(len(sharpes)))) if values_per_param else list(range(len(sharpes)))

        min_s = min(sharpes)
        max_s = max(sharpes)
        worst_sharpe = min(worst_sharpe, min_s)

        # Compute std
        mean_s = sum(sharpes) / len(sharpes)
        var_s = sum((s - mean_s) ** 2 for s in sharpes) / len(sharpes)
        std_s = math.sqrt(var_s)

        # Plateau check: Sharpe should not drop more than threshold from base
        max_drop = base_sharpe - min_s
        is_plateau = max_drop <= degradation_threshold

        if not is_plateau:
            all_plateau = False

        sensitivities.append(ParameterSensitivity(
            parameter=param_name,
            values=values,
            sharpes=sharpes,
            is_plateau=is_plateau,
            min_sharpe=min_s,
            max_sharpe=max_s,
            sharpe_std=std_s,
        ))

    return SensitivityResult(
        base_sharpe=base_sharpe,
        parameters=sensitivities,
        overall_robust=all_plateau,
        degradation_threshold=degradation_threshold,
        worst_case_sharpe=worst_sharpe,
    )
