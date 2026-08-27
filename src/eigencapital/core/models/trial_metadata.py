"""Domain model: TrialMetadata.

Multiple-testing accounting for research experiments.

Every experiment that is part of a parameter/feature/model search belongs to a
TRIAL FAMILY. A final Sharpe ratio means something entirely different if it was
the first hypothesis tested versus the best of 500 combinations. This metadata
must survive permanently in the research ledger so selection bias can be
quantified (e.g., deflated Sharpe ratio).

Invariants:
- trial_group_id is non-empty (identifies the family/search)
- hypothesis_family is non-empty (e.g. "momentum", "trend")
- trial_index >= 1 (1-based ordinal position within the family)
- trials_in_family >= trial_index when set (a family cannot be smaller
  than the position of any member)
- selection_method is non-empty (how this configuration was chosen)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class TrialMetadata:
    """Multiple-testing provenance for one experiment inside a trial family.

    Attributes:
        trial_group_id: Identifier of the family/search this trial belongs to
            (e.g., "HYP-TREND-001/lookback-stop-grid").
        trial_index: 1-based ordinal position of this experiment within the
            family (1 = first distinct opportunity tried).
        trials_in_family: Total number of materially distinct trials known in
            the family at reporting time. None while the family is still open.
        hypothesis_family: Research family label (trend, momentum,
            mean_reversion, breakout, volatility, cross_sectional,
            statistical_arbitrage, factor, ml, alternative_data).
        parameter_search_space: Declared space searched by the family
            (parameter names -> ranges/options). Empty dict for single-shot
            experiments.
        selection_method: How this configuration was selected from the family
            (e.g., "first_registered", "best_validation_sharpe",
            "single_candidate"). Must never claim out-of-sample merit for an
            in-sample selection.
    """

    trial_group_id: str
    trial_index: int
    hypothesis_family: str
    selection_method: str
    trials_in_family: int | None = None
    parameter_search_space: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trial_group_id:
            raise ValueError("trial_group_id must be non-empty")

        if not isinstance(self.trial_index, int) or self.trial_index < 1:
            raise ValueError(f"trial_index must be an int >= 1, got {self.trial_index!r}")

        if not self.hypothesis_family:
            raise ValueError("hypothesis_family must be non-empty")

        if not self.selection_method:
            raise ValueError("selection_method must be non-empty")

        if self.trials_in_family is not None:
            if not isinstance(self.trials_in_family, int) or self.trials_in_family < self.trial_index:
                raise ValueError(
                    f"trials_in_family ({self.trials_in_family!r}) must be an int >= trial_index ({self.trial_index})"
                )

        if not isinstance(self.parameter_search_space, dict):
            raise ValueError("parameter_search_space must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "trial_group_id": self.trial_group_id,
            "trial_index": self.trial_index,
            "hypothesis_family": self.hypothesis_family,
            "selection_method": self.selection_method,
            "trials_in_family": self.trials_in_family,
            "parameter_search_space": dict(self.parameter_search_space),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TrialMetadata:
        """Deserialize from dict."""
        return cls(
            trial_group_id=str(d["trial_group_id"]),
            trial_index=int(d["trial_index"]),
            hypothesis_family=str(d["hypothesis_family"]),
            selection_method=str(d["selection_method"]),
            trials_in_family=(int(d["trials_in_family"]) if d.get("trials_in_family") is not None else None),
            parameter_search_space=d.get("parameter_search_space", {}),
        )

    @property
    def is_first_trial(self) -> bool:
        """True if this was the first materially distinct opportunity tried."""
        return self.trial_index == 1

    @property
    def family_is_open(self) -> bool:
        """True while total family size is still unknown (search ongoing)."""
        return self.trials_in_family is None

    def summary(self) -> str:
        """Human-readable one-liner."""
        size = str(self.trials_in_family) if self.trials_in_family is not None else "open"
        return (
            f"{self.trial_group_id} [{self.hypothesis_family}] "
            f"trial {self.trial_index}/{size} "
            f"(selected via {self.selection_method})"
        )
