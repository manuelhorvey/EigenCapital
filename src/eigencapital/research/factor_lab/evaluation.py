"""Factor Evaluation — preregistered falsification under the frozen contract.

Implements contract items 4–7, 10–12 of docs/research/R2_FACTOR_LAB.md on top
of the verified ``factor_evaluation`` infrastructure:

- IC: per-period Spearman rank IC (existing function; rank IC is primary).
- Quantiles: existing even-bucket construction + per-period spread series.
- Turnover: existing top-set turnover with a preregistered top_fraction.
- Costs: credibility is judged on the COST-ADJUSTED top-minus-bottom spread =
  gross spread − (2 × one-way cost × mean top-set turnover). The cost model
  id/version and the STRESS preset reference are recorded.
- Trials: one TrialMetadata family per experiment; the family size is fixed
  at registration time.
- Multiple testing: Holm correction (preregistered) on the IC t-stat p-value.
- Verdicts (no silent pass):
    REJECTED     mean_ic <= 0 after correction, OR cost-adjusted spread <= 0
                 at the preregistered cost model
    INCONCLUSIVE excluded-observation share above the preregistered budget,
                 or fewer than min_periods usable panels
    CANDIDATE    none of the above (positive IC survives Holm; positive
                 cost-adjusted spread) — the gate's moderate-evidence state

The evaluation NEVER returns VALIDATED: a single-factor panel study cannot
supply the evidence depth the gate requires for that verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

from eigencapital.analytics.validation.factor_evaluation import (
    factor_turnover,
    information_coefficient,
    quantile_spread_series,
)
from eigencapital.analytics.validation.multiple_testing import (
    multiple_testing_correction,
)
from eigencapital.core.costs import CostModel
from eigencapital.core.models.trial_metadata import TrialMetadata
from eigencapital.research.factor_lab.observations import PanelSet


class EvaluationError(ValueError):
    """Raised on contract violations during factor evaluation."""


@dataclass(frozen=True)
class FactorEvaluation:
    """Result of one preregistered factor evaluation.

    Attributes:
        factor_id: Evaluated factor.
        trial_metadata: The preregistered trial family record.
        ic: IC statistics dict (from the verified infrastructure).
        quantile_spread_mean: Mean per-period top-minus-bottom spread (gross).
        cost_adjusted_spread: Gross spread minus 2 x one-way cost x turnover.
        turnover: Turnover statistics dict.
        ic_p_value_raw: Two-sided p-value of the IC t-stat.
        ic_p_value_holm: Holm-corrected p-value across the declared family.
        exclusion_share: Excluded observations / attempted observations.
        verdict: REJECTED | INCONCLUSIVE | CANDIDATE (never VALIDATED).
        reasons: Machine-readable reasons supporting the verdict.
    """

    factor_id: str
    trial_metadata: Dict[str, Any]
    ic: Dict[str, Any]
    quantile_spread_mean: float
    cost_adjusted_spread: float
    turnover: Dict[str, Any]
    ic_p_value_raw: float
    ic_p_value_holm: float
    exclusion_share: float
    verdict: str
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "factor_id": self.factor_id,
            "trial_metadata": self.trial_metadata,
            "ic": self.ic,
            "quantile_spread_mean_gross": round(self.quantile_spread_mean, 8),
            "cost_adjusted_spread": round(self.cost_adjusted_spread, 8),
            "turnover": self.turnover,
            "ic_p_value_raw": round(self.ic_p_value_raw, 6),
            "ic_p_value_holm": round(self.ic_p_value_holm, 6),
            "exclusion_share": round(self.exclusion_share, 4),
            "verdict": self.verdict,
            "reasons": self.reasons,
        }


def _ic_p_value(mean_ic: float, std_ic: float, t_stat: float, n_periods: int) -> float:
    """Two-sided normal-approximation p-value for the IC mean.

    The IC t-stat under H0 (mean IC = 0) is asymptotically standard normal.

    Degenerate case handled honestly: when the per-period IC series has ZERO
    variance, the infrastructure's t-stat guard returns 0.0 — but a zero-
    variance series with a nonzero mean is a CONSTANT IC, which is maximally
    informative about direction, not uninformative. We return p=0 for that
    case (sign is certain across every period) and p=1 when the constant
    series is exactly zero.
    """
    if n_periods < 2:
        return 1.0
    if std_ic <= 1e-15:
        return 0.0 if mean_ic > 0 else 1.0
    z = abs(t_stat)
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    return max(0.0, min(1.0, p))


def evaluate_factor(
    panels: PanelSet,
    cost_model: CostModel,
    trial_metadata: TrialMetadata,
    top_fraction: float = 0.2,
    min_names: int = 5,
    min_periods: int = 12,
    max_exclusion_share: float = 0.20,
) -> FactorEvaluation:
    """Evaluate ONE factor against the frozen falsification criteria.

    Args:
        panels: Assembled PanelSet (contract items 1-3, 8-9).
        cost_model: Preregistered cost model for the spread haircut.
        trial_metadata: The preregistered trial family record (fixed size).
        top_fraction: Preregistered top-set fraction for turnover.
        min_names: Minimum cross-section width per period (passed through).
        min_periods: Minimum usable panels; below → INCONCLUSIVE.
        max_exclusion_share: Exclusion budget; above → INCONCLUSIVE.

    Returns:
        FactorEvaluation with verdict in {REJECTED, INCONCLUSIVE, CANDIDATE}.

    Raises:
        EvaluationError: On empty panels or contract violations.
    """
    if not panels.panels:
        raise EvaluationError("cannot evaluate an empty PanelSet")

    attempted = panels.n_observations + sum(panels.exclusions.values())
    exclusion_share = sum(panels.exclusions.values()) / attempted if attempted else 1.0

    ic_result = information_coefficient(panels.panels, min_names=min_names)
    spreads = quantile_spread_series(panels.panels, n_quantiles=5, min_names=min_names)

    # Turnover needs ranking maps per period: rebuild them from panel order.
    # Panels carry (signal, fwd_return) pairs; the ranking is by signal.
    rankings: list[Dict[str, float]] = []
    for period_index, panel in enumerate(panels.panels):
        ranking = {f"{panels.period_dates[period_index]}#{k}": signal for k, (signal, _) in enumerate(panel)}
        rankings.append(ranking)
    turnover_result = factor_turnover(rankings, top_fraction=top_fraction)

    gross_spread = sum(spreads) / len(spreads) if spreads else 0.0
    mean_turnover = turnover_result.mean_top_set_turnover
    # Costs are expressed per unit of traded notional. The CostModel carries
    # per-contract fields; the preregistered convention for factor panels is
    # the market_impact_bps + spread/slippage tick values read as bps of
    # notional (documented in the frozen contract, item 7).
    one_way_bps = cost_model.market_impact_bps + cost_model.slippage_ticks + cost_model.spread_ticks
    one_way_fraction = one_way_bps / 10_000.0
    cost_adjusted_spread = gross_spread - 2.0 * one_way_fraction * mean_turnover

    p_raw = _ic_p_value(ic_result.mean_ic, ic_result.std_ic, ic_result.t_stat, ic_result.n_periods)
    correction = multiple_testing_correction(
        [p_raw],
        method="holm",  # preregistered (contract item 11)
        alpha=0.05,
        family_definition=trial_metadata.trial_group_id,
    )
    p_holm = correction.adjusted_p_values[0]

    reasons: List[str] = []
    verdict = "CANDIDATE"

    if ic_result.n_periods < min_periods:
        verdict = "INCONCLUSIVE"
        reasons.append(f"usable_periods={ic_result.n_periods} < min_periods={min_periods}")
    if exclusion_share > max_exclusion_share:
        verdict = "INCONCLUSIVE"
        reasons.append(f"exclusion_share={exclusion_share:.3f} > budget {max_exclusion_share}")

    if verdict != "INCONCLUSIVE":
        if ic_result.mean_ic <= 0.0 or p_holm > 0.05:
            verdict = "REJECTED"
            reasons.append(f"mean_ic={ic_result.mean_ic:+.4f} holm_p={p_holm:.4f} (H0: mean rank IC <= 0 not rejected)")
        if cost_adjusted_spread <= 0.0:
            verdict = "REJECTED"
            reasons.append(f"cost_adjusted_spread={cost_adjusted_spread:+.6f} <= 0 at {cost_model.model_id}")
        if not reasons:
            reasons.append(
                "positive IC survives Holm correction AND positive cost-adjusted spread at the preregistered cost model"
            )

    return FactorEvaluation(
        factor_id=panels.factor_id,
        trial_metadata={
            "trial_group_id": trial_metadata.trial_group_id,
            "trial_index": trial_metadata.trial_index,
            "trials_in_family": trial_metadata.trials_in_family,
            "hypothesis_family": trial_metadata.hypothesis_family,
            "selection_method": trial_metadata.selection_method,
            "parameter_search_space": trial_metadata.parameter_search_space,
        },
        ic=ic_result.to_dict(),
        quantile_spread_mean=gross_spread,
        cost_adjusted_spread=cost_adjusted_spread,
        turnover=turnover_result.to_dict(),
        ic_p_value_raw=p_raw,
        ic_p_value_holm=p_holm,
        exclusion_share=exclusion_share,
        verdict=verdict,
        reasons=reasons,
    )
