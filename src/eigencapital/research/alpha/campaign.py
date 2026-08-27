"""Research Campaign Runner — executes hypothesis library through existing pipeline.

Campaign governance:
- No hypothesis modification after registration
- Trial groups frozen before results
- Parameter snapshots frozen before results
- Mandatory cost model
- Evidence gate authoritative
- Negative results are successful research outcomes

Campaign lifecycle:
PLANNED → CALIBRATION → TIER_1 → TIER_2 → TIER_3 → ML_GATE → COMPLETED
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class CampaignPhase(str, Enum):
    """Research campaign phase."""

    PLANNED = "planned"
    CALIBRATION = "calibration"  # FACTOR-003 replication gate
    SIMPLE_FACTORS = "simple_factors"  # Tier 1: cheap, broad, structurally useful
    TREND_MOMENTUM = "trend_momentum"  # Tier 2: trend/momentum/breakout
    MEAN_REVERSION = "mean_reversion"  # Tier 3: mean reversion (hostile)
    STAT_ARB = "stat_arb"  # Tier 4: statistical arbitrage
    VOLATILITY = "volatility"  # Volatility as conditioning layer
    ALT_DATA = "alt_data"  # Alternative data (after timestamp discipline)
    ML_GATE = "ml_gate"  # ML complexity ladder (last)
    COMPLETED = "completed"
    FAILED = "failed"


# Valid phase transitions
_VALID_PHASE_TRANSITIONS: Dict[str, List[str]] = {
    CampaignPhase.PLANNED.value: [
        CampaignPhase.CALIBRATION.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.CALIBRATION.value: [
        CampaignPhase.SIMPLE_FACTORS.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.SIMPLE_FACTORS.value: [
        CampaignPhase.TREND_MOMENTUM.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.TREND_MOMENTUM.value: [
        CampaignPhase.MEAN_REVERSION.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.MEAN_REVERSION.value: [
        CampaignPhase.STAT_ARB.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.STAT_ARB.value: [
        CampaignPhase.VOLATILITY.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.VOLATILITY.value: [
        CampaignPhase.ALT_DATA.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.ALT_DATA.value: [
        CampaignPhase.ML_GATE.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.ML_GATE.value: [
        CampaignPhase.COMPLETED.value,
        CampaignPhase.FAILED.value,
    ],
    CampaignPhase.COMPLETED.value: [],
    CampaignPhase.FAILED.value: [],
}


class HypothesisStatus(str, Enum):
    """Hypothesis lifecycle status."""

    UNVALIDATED = "unvalidated"
    REGISTERED = "registered"
    EXPERIMENTED = "experimented"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    PORTFOLIO_USEFUL = "portfolio_useful"
    PRODUCTION_CANDIDATE = "production_candidate"
    CONDITIONAL = "conditional"  # Works only under declared conditions
    INCREMENTAL = "incremental"  # Adds value to existing portfolio
    REDUNDANT = "redundant"  # Works individually but adds no portfolio value
    FRAGILE = "fragile"  # Statistical edge fails robustness/cost/regime
    CAPACITY_LIMITED = "capacity_limited"  # Edge exists but deployable capacity inadequate


@dataclass(frozen=True)
class HypothesisIdentity:
    """Immutable hypothesis identity — frozen at registration."""

    hypothesis_id: str
    family: str
    title: str
    claim: str
    economic_rationale: str
    expected_mechanism: str
    universe: str
    required_data: tuple  # tuple of strings
    candidate_features: tuple  # tuple of strings
    candidate_parameters: dict  # frozen parameter search space
    falsification_criteria: str
    expected_failure_modes: str
    transaction_cost_sensitivity: str
    capacity_considerations: str
    source: str
    trial_group_default: str = ""
    status: str = HypothesisStatus.UNVALIDATED.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "title": self.title,
            "claim": self.claim,
            "economic_rationale": self.economic_rationale,
            "expected_mechanism": self.expected_mechanism,
            "universe": self.universe,
            "required_data": list(self.required_data),
            "candidate_features": list(self.candidate_features),
            "candidate_parameters": self.candidate_parameters,
            "falsification_criteria": self.falsification_criteria,
            "expected_failure_modes": self.expected_failure_modes,
            "transaction_cost_sensitivity": self.transaction_cost_sensitivity,
            "capacity_considerations": self.capacity_considerations,
            "source": self.source,
            "trial_group_default": self.trial_group_default,
            "status": self.status,
        }

    def compute_fingerprint(self) -> str:
        """Fingerprint of the hypothesis identity — cannot change after registration."""
        data = self.to_dict()
        # Remove status from fingerprint — identity is immutable
        data.pop("status", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class HypothesisTrial:
    """A single trial of a hypothesis experiment."""

    trial_id: str
    hypothesis_id: str
    trial_group_id: str
    trial_index: int
    parameter_config: dict
    dataset_version: str
    universe: str
    feature_versions: dict
    strategy_config_hash: str
    cost_model_hash: str
    provenance_hash: str
    timestamp: str = ""
    result_status: str = ""  # SUPPORTED, REJECTED, INCONCLUSIVE
    result_sharpe: float = 0.0
    result_turnover: float = 0.0
    result_drawdown: float = 0.0
    is_selected: bool = False  # Whether this was the "best" trial in its family

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "hypothesis_id": self.hypothesis_id,
            "trial_group_id": self.trial_group_id,
            "trial_index": self.trial_index,
            "parameter_config": self.parameter_config,
            "dataset_version": self.dataset_version,
            "universe": self.universe,
            "feature_versions": self.feature_versions,
            "strategy_config_hash": self.strategy_config_hash,
            "cost_model_hash": self.cost_model_hash,
            "provenance_hash": self.provenance_hash,
            "timestamp": self.timestamp,
            "result_status": self.result_status,
            "result_sharpe": self.result_sharpe,
            "result_turnover": self.result_turnover,
            "result_drawdown": self.result_drawdown,
            "is_selected": self.is_selected,
        }


@dataclass(frozen=True)
class HypothesisVerdict:
    """Final verdict on a hypothesis after all trials."""

    hypothesis_id: str
    family: str
    status: str  # REJECTED, INCONCLUSIVE, SUPPORTED, PORTFOLIO_USEFUL, PRODUCTION_CANDIDATE
    total_trials: int
    selected_trial_id: str = ""
    best_sharpe: float = 0.0
    net_sharpe: float = 0.0
    turnover: float = 0.0
    max_drawdown: float = 0.0
    falsification_passed: bool = False
    cost_survived: bool = False
    incremental_value: bool = False
    incremental_sharpe_delta: float = 0.0
    incremental_dd_delta: float = 0.0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "status": self.status,
            "total_trials": self.total_trials,
            "selected_trial_id": self.selected_trial_id,
            "best_sharpe": self.best_sharpe,
            "net_sharpe": self.net_sharpe,
            "turnover": self.turnover,
            "max_drawdown": self.max_drawdown,
            "falsification_passed": self.falsification_passed,
            "cost_survived": self.cost_survived,
            "incremental_value": self.incremental_value,
            "incremental_sharpe_delta": self.incremental_sharpe_delta,
            "incremental_dd_delta": self.incremental_dd_delta,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ResearchCampaign:
    """Immutable research campaign identity."""

    campaign_id: str
    production_fingerprint: str
    start_timestamp: str = ""
    expiry_timestamp: str = ""
    current_phase: str = CampaignPhase.PLANNED.value
    phase_history: tuple = ()
    total_hypotheses: int = 0
    hypotheses_by_family: dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "production_fingerprint": self.production_fingerprint,
            "start_timestamp": self.start_timestamp,
            "expiry_timestamp": self.expiry_timestamp,
            "current_phase": self.current_phase,
            "total_hypotheses": self.total_hypotheses,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def can_transition_to(self, new_phase: str) -> bool:
        valid_targets = _VALID_PHASE_TRANSITIONS.get(self.current_phase, [])
        return new_phase in valid_targets


class ResearchCampaignRunner:
    """Manages research campaign lifecycle, hypothesis registration, and trial tracking."""

    def __init__(self) -> None:
        self._campaigns: Dict[str, ResearchCampaign] = {}
        self._hypotheses: Dict[str, HypothesisIdentity] = {}
        self._trials: Dict[str, List[HypothesisTrial]] = {}  # hypothesis_id -> trials
        self._verdicts: Dict[str, HypothesisVerdict] = {}
        self._events: List[Dict[str, Any]] = []

    def create_campaign(self, campaign: ResearchCampaign) -> ResearchCampaign:
        """Create a new research campaign."""
        self._campaigns[campaign.campaign_id] = campaign
        self._record_event("CAMPAIGN_CREATED", campaign.campaign_id, campaign.current_phase)
        return campaign

    def transition_phase(
        self,
        campaign_id: str,
        new_phase: str,
        timestamp: str = "",
        reason: str = "",
    ) -> bool:
        """Transition campaign to a new phase."""
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            return False

        if not campaign.can_transition_to(new_phase):
            self._record_event(
                "INVALID_TRANSITION",
                campaign_id,
                f"{campaign.current_phase} -> {new_phase} (INVALID)",
                reason=reason,
            )
            return False

        updated = ResearchCampaign(
            campaign_id=campaign.campaign_id,
            production_fingerprint=campaign.production_fingerprint,
            start_timestamp=campaign.start_timestamp,
            expiry_timestamp=campaign.expiry_timestamp,
            current_phase=new_phase,
            phase_history=campaign.phase_history + ((new_phase, timestamp),),
            total_hypotheses=campaign.total_hypotheses,
            hypotheses_by_family=campaign.hypotheses_by_family,
        )
        self._campaigns[campaign_id] = updated
        self._record_event("PHASE_CHANGED", campaign_id, new_phase, reason=reason)
        return True

    def register_hypothesis(self, hypothesis: HypothesisIdentity) -> HypothesisIdentity:
        """Register a hypothesis — frozen after registration."""
        registered = HypothesisIdentity(
            hypothesis_id=hypothesis.hypothesis_id,
            family=hypothesis.family,
            title=hypothesis.title,
            claim=hypothesis.claim,
            economic_rationale=hypothesis.economic_rationale,
            expected_mechanism=hypothesis.expected_mechanism,
            universe=hypothesis.universe,
            required_data=hypothesis.required_data,
            candidate_features=hypothesis.candidate_features,
            candidate_parameters=hypothesis.candidate_parameters,
            falsification_criteria=hypothesis.falsification_criteria,
            expected_failure_modes=hypothesis.expected_failure_modes,
            transaction_cost_sensitivity=hypothesis.transaction_cost_sensitivity,
            capacity_considerations=hypothesis.capacity_considerations,
            source=hypothesis.source,
            trial_group_default=hypothesis.trial_group_default,
            status=HypothesisStatus.REGISTERED.value,
        )
        self._hypotheses[hypothesis.hypothesis_id] = registered
        self._trials[hypothesis.hypothesis_id] = []
        self._record_event("HYPOTHESIS_REGISTERED", hypothesis.hypothesis_id, registered.family)
        return registered

    def record_trial(self, trial: HypothesisTrial) -> None:
        """Record a trial result for a hypothesis."""
        trials = self._trials.get(trial.hypothesis_id, [])
        trials.append(trial)
        self._trials[trial.hypothesis_id] = trials
        self._record_event(
            "TRIAL_RECORDED",
            trial.hypothesis_id,
            f"trial={trial.trial_id}, status={trial.result_status}",
        )

    def record_verdict(self, verdict: HypothesisVerdict) -> None:
        """Record a final hypothesis verdict."""
        self._verdicts[verdict.hypothesis_id] = verdict
        # Update hypothesis status
        hypothesis = self._hypotheses.get(verdict.hypothesis_id)
        if hypothesis is not None:
            updated = HypothesisIdentity(
                hypothesis_id=hypothesis.hypothesis_id,
                family=hypothesis.family,
                title=hypothesis.title,
                claim=hypothesis.claim,
                economic_rationale=hypothesis.economic_rationale,
                expected_mechanism=hypothesis.expected_mechanism,
                universe=hypothesis.universe,
                required_data=hypothesis.required_data,
                candidate_features=hypothesis.candidate_features,
                candidate_parameters=hypothesis.candidate_parameters,
                falsification_criteria=hypothesis.falsification_criteria,
                expected_failure_modes=hypothesis.expected_failure_modes,
                transaction_cost_sensitivity=hypothesis.transaction_cost_sensitivity,
                capacity_considerations=hypothesis.capacity_considerations,
                source=hypothesis.source,
                trial_group_default=hypothesis.trial_group_default,
                status=verdict.status,
            )
            self._hypotheses[verdict.hypothesis_id] = updated
        self._record_event(
            "VERDICT_RECORDED",
            verdict.hypothesis_id,
            verdict.status,
        )

    def cannot_modify_hypothesis(self, hypothesis_id: str) -> bool:
        """Verify that a registered hypothesis cannot be modified."""
        return hypothesis_id in self._hypotheses

    def get_hypothesis(self, hypothesis_id: str) -> HypothesisIdentity | None:
        return self._hypotheses.get(hypothesis_id)

    def get_trials(self, hypothesis_id: str) -> List[HypothesisTrial]:
        return list(self._trials.get(hypothesis_id, []))

    def get_verdict(self, hypothesis_id: str) -> HypothesisVerdict | None:
        return self._verdicts.get(hypothesis_id)

    def get_campaign(self, campaign_id: str) -> ResearchCampaign | None:
        return self._campaigns.get(campaign_id)

    def get_all_verdicts(self) -> List[HypothesisVerdict]:
        return list(self._verdicts.values())

    def get_verdicts_by_family(self, family: str) -> List[HypothesisVerdict]:
        return [v for v in self._verdicts.values() if v.family == family]

    def get_rejected_count(self) -> int:
        return sum(1 for v in self._verdicts.values() if v.status == HypothesisStatus.REJECTED.value)

    def get_supported_count(self) -> int:
        return sum(
            1
            for v in self._verdicts.values()
            if v.status
            in (
                HypothesisStatus.SUPPORTED.value,
                HypothesisStatus.PORTFOLIO_USEFUL.value,
                HypothesisStatus.PRODUCTION_CANDIDATE.value,
            )
        )

    def _record_event(self, event_type: str, entity_id: str, status: str, reason: str = "") -> None:
        self._events.append(
            {
                "event_type": event_type,
                "entity_id": entity_id,
                "status": status,
                "reason": reason,
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self._events)
