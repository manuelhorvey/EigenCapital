"""Hypothesis model — pre-registered research claim.

Every hypothesis must explicitly state its falsification criteria.
This prevents EigenCapital from becoming an engine for rationalizing
trades we already want to believe in.

Usage:
    hyp = Hypothesis(
        hypothesis_id="HYP-000001",
        claim="Assets exhibiting X tend to exhibit Y over horizon Z.",
        economic_rationale="Mean reversion in volatility...",
        falsification_criteria="If Sharpe < 0.5 after costs, reject.",
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class Hypothesis:
    """Pre-registered research hypothesis.

    The critical field is falsification_criteria: what evidence would
    convince us that this idea is wrong?

    Attributes:
        hypothesis_id: Unique identifier (e.g., "HYP-000001")
        claim: The testable assertion
        economic_rationale: Why this should work economically
        expected_mechanism: How the edge manifests
        universe: Instruments/asset classes involved
        horizon: Expected holding period
        primary_metric: Main evaluation metric (Sharpe, etc.)
        falsification_criteria: What would reject this hypothesis
        known_risks: Limitations and known failure modes
        pre_existing_evidence: Prior research or intuition
        status: DRAFT, REGISTERED, TESTED, REJECTED, SUPPORTED
        version: Version for change tracking
    """

    hypothesis_id: str
    claim: str
    economic_rationale: str = ""
    expected_mechanism: str = ""
    universe: str = ""
    horizon: str = ""
    primary_metric: str = "Sharpe"
    falsification_criteria: str = ""
    known_risks: str = ""
    pre_existing_evidence: str = ""
    status: str = "DRAFT"
    version: str = "v1"

    def __post_init__(self) -> None:
        if not self.hypothesis_id:
            raise ValueError("hypothesis_id must be non-empty")
        if not self.claim:
            raise ValueError("claim must be non-empty")
        valid_statuses = {"DRAFT", "REGISTERED", "TESTED", "REJECTED", "SUPPORTED"}
        if self.status not in valid_statuses:
            raise ValueError(
                f"Invalid status: {self.status}. Must be one of {valid_statuses}"
            )

    def register(self) -> Hypothesis:
        """Transition to REGISTERED status (returns new frozen instance)."""
        if self.status != "DRAFT":
            raise ValueError(f"Cannot register: current status is {self.status}")
        return Hypothesis(**{**self.__dict__, "status": "REGISTERED"})

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "claim": self.claim,
            "economic_rationale": self.economic_rationale,
            "expected_mechanism": self.expected_mechanism,
            "universe": self.universe,
            "horizon": self.horizon,
            "primary_metric": self.primary_metric,
            "falsification_criteria": self.falsification_criteria,
            "known_risks": self.known_risks,
            "pre_existing_evidence": self.pre_existing_evidence,
            "status": self.status,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Hypothesis:
        """Deserialize from dict."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
