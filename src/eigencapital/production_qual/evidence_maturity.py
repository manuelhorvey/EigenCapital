"""Evidence Maturity Framework — prevents premature conclusions.

Because R4 is a slow-tail strategy, positive expectancy in a dashboard
could be based on a tiny sample. This framework tracks evidence maturity
to prevent someone from seeing "positive expectancy" and forgetting
it was based on 17 days of data.

Evidence maturity states:
  E0 — No meaningful evidence
  E1 — Operational evidence (system runs, no critical incidents)
  E2 — Execution evidence (fills match expectations)
  E3 — Early economic evidence (first trade lifecycles complete)
  E4 — Full holding-period evidence (20-40+ day cycles observed)
  E5 — Replicated economic evidence (multiple independent episodes)
  E6 — Capital-promotion evidence (statistically defensible for scaling)

R4 should not be considered promotion-ready until E5 or E6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class EvidenceLevel(str, Enum):
    """Evidence maturity levels."""

    E0_NO_EVIDENCE = "E0_NO_EVIDENCE"
    E1_OPERATIONAL = "E1_OPERATIONAL"
    E2_EXECUTION = "E2_EXECUTION"
    E3_EARLY_ECONOMIC = "E3_EARLY_ECONOMIC"
    E4_FULL_HOLDING = "E4_FULL_HOLDING"
    E5_REPLICATED = "E5_REPLICATED"
    E6_PROMOTION_READY = "E6_PROMOTION_READY"


@dataclass(frozen=True)
class EvidenceState:
    """Current evidence maturity state."""

    level: str
    level_number: int
    timestamp: str

    # What we know
    operational_days: float
    completed_trades: int
    independent_episodes: int
    max_holding_period_days: float

    # What we need for next level
    next_level_requirements: List[str]

    # Assessment
    assessment: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "level_number": self.level_number,
            "timestamp": self.timestamp,
            "operational_days": self.operational_days,
            "completed_trades": self.completed_trades,
            "independent_episodes": self.independent_episodes,
            "max_holding_period_days": self.max_holding_period_days,
            "next_level_requirements": self.next_level_requirements,
            "assessment": self.assessment,
        }


class EvidenceMaturityTracker:
    """Tracks evidence maturity for Phase 2 qualification.

    Prevents premature capital promotion by requiring sufficient
    evidence at each level before advancing.
    """

    # Level advancement thresholds
    THRESHOLDS = {
        EvidenceLevel.E0_NO_EVIDENCE: {
            "min_days": 0,
            "min_trades": 0,
            "min_episodes": 0,
            "max_holding": 0,
        },
        EvidenceLevel.E1_OPERATIONAL: {
            "min_days": 7,
            "min_trades": 0,
            "min_episodes": 0,
            "max_holding": 0,
        },
        EvidenceLevel.E2_EXECUTION: {
            "min_days": 14,
            "min_trades": 10,
            "min_episodes": 0,
            "max_holding": 0,
        },
        EvidenceLevel.E3_EARLY_ECONOMIC: {
            "min_days": 21,
            "min_trades": 20,
            "min_episodes": 1,
            "max_holding": 10,
        },
        EvidenceLevel.E4_FULL_HOLDING: {
            "min_days": 45,
            "min_trades": 30,
            "min_episodes": 2,
            "max_holding": 30,
        },
        EvidenceLevel.E5_REPLICATED: {
            "min_days": 90,
            "min_trades": 50,
            "min_episodes": 3,
            "max_holding": 40,
        },
        EvidenceLevel.E6_PROMOTION_READY: {
            "min_days": 120,
            "min_trades": 80,
            "min_episodes": 5,
            "max_holding": 40,
        },
    }

    def __init__(self) -> None:
        self._current_level = EvidenceLevel.E0_NO_EVIDENCE
        self._level_history: List[Dict[str, Any]] = []

    def assess(
        self,
        operational_days: float,
        completed_trades: int,
        independent_episodes: int,
        max_holding_period_days: float,
    ) -> EvidenceState:
        """Assess current evidence maturity level.

        Args:
            operational_days: Days of continuous operation
            completed_trades: Number of completed trade lifecycles
            independent_episodes: Number of independent portfolio episodes
            max_holding_period_days: Longest observed holding period

        Returns:
            Current evidence state
        """
        now = datetime.now(timezone.utc).isoformat()

        # Determine highest achievable level
        achieved_level = EvidenceLevel.E0_NO_EVIDENCE
        achieved_number = 0

        for level in [
            EvidenceLevel.E6_PROMOTION_READY,
            EvidenceLevel.E5_REPLICATED,
            EvidenceLevel.E4_FULL_HOLDING,
            EvidenceLevel.E3_EARLY_ECONOMIC,
            EvidenceLevel.E2_EXECUTION,
            EvidenceLevel.E1_OPERATIONAL,
        ]:
            thresholds = self.THRESHOLDS[level]
            if (
                operational_days >= thresholds["min_days"]
                and completed_trades >= thresholds["min_trades"]
                and independent_episodes >= thresholds["min_episodes"]
                and max_holding_period_days >= thresholds["max_holding"]
            ):
                achieved_level = level
                achieved_number = int(level.value[1])
                break

        # Compute next level requirements
        next_requirements = []
        next_level_num = achieved_number + 1
        if next_level_num <= 6:
            next_level = EvidenceLevel(
                f"E{next_level_num}_{'OPERATIONAL' if next_level_num == 1 else 'EXECUTION' if next_level_num == 2 else 'EARLY_ECONOMIC' if next_level_num == 3 else 'FULL_HOLDING' if next_level_num == 4 else 'REPLICATED' if next_level_num == 5 else 'PROMOTION_READY'}"
            )
            next_thresholds = self.THRESHOLDS[next_level]

            if operational_days < next_thresholds["min_days"]:
                next_requirements.append(
                    f"Need {next_thresholds['min_days'] - operational_days:.0f} more operational days"
                )
            if completed_trades < next_thresholds["min_trades"]:
                next_requirements.append(
                    f"Need {next_thresholds['min_trades'] - completed_trades} more completed trades"
                )
            if independent_episodes < next_thresholds["min_episodes"]:
                next_requirements.append(
                    f"Need {next_thresholds['min_episodes'] - independent_episodes} more independent episodes"
                )
            if max_holding_period_days < next_thresholds["max_holding"]:
                next_requirements.append(
                    f"Need {next_thresholds['max_holding'] - max_holding_period_days:.0f} more days of holding observation"
                )

        # Generate assessment
        assessment = self._generate_assessment(
            achieved_level,
            operational_days,
            completed_trades,
            independent_episodes,
            max_holding_period_days,
        )

        state = EvidenceState(
            level=achieved_level.value,
            level_number=achieved_number,
            timestamp=now,
            operational_days=operational_days,
            completed_trades=completed_trades,
            independent_episodes=independent_episodes,
            max_holding_period_days=max_holding_period_days,
            next_level_requirements=next_requirements,
            assessment=assessment,
        )

        # Track level changes
        if achieved_level != self._current_level:
            self._level_history.append(
                {
                    "from": self._current_level.value,
                    "to": achieved_level.value,
                    "timestamp": now,
                    "operational_days": operational_days,
                    "completed_trades": completed_trades,
                }
            )
            self._current_level = achieved_level

        return state

    def _generate_assessment(
        self,
        level: EvidenceLevel,
        days: float,
        trades: int,
        episodes: int,
        max_holding: float,
    ) -> str:
        """Generate human-readable assessment."""
        assessments = {
            EvidenceLevel.E0_NO_EVIDENCE: "No meaningful evidence yet. System just started.",
            EvidenceLevel.E1_OPERATIONAL: f"Operational evidence: {days:.0f} days running. System survives. No economic conclusions possible.",
            EvidenceLevel.E2_EXECUTION: f"Execution evidence: {trades} trades observed. Can assess fill quality and costs. Economic conclusions still premature.",
            EvidenceLevel.E3_EARLY_ECONOMIC: f"Early economic evidence: {trades} trades, {episodes} episodes. First lifecycle data available. Holding period observation ongoing.",
            EvidenceLevel.E4_FULL_HOLDING: f"Full holding-period evidence: {max_holding:.0f}-day observations. Can assess edge expression timeline. Still need replication.",
            EvidenceLevel.E5_REPLICATED: f"Replicated evidence: {episodes} independent episodes, {trades} trades. Statistically meaningful. Ready for promotion consideration.",
            EvidenceLevel.E6_PROMOTION_READY: f"Promotion-ready evidence: {episodes} episodes, {trades} trades, {days:.0f} days. Statistically defensible for scaling.",
        }
        return assessments.get(level, "Unknown level")

    def get_current_level(self) -> EvidenceLevel:
        """Get current evidence level."""
        return self._current_level

    def get_history(self) -> List[Dict[str, Any]]:
        """Get level change history."""
        return list(self._level_history)

    def is_promotion_ready(self) -> bool:
        """Check if evidence level supports capital promotion."""
        return self._current_level in (
            EvidenceLevel.E5_REPLICATED,
            EvidenceLevel.E6_PROMOTION_READY,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Export current state."""
        return {
            "current_level": self._current_level.value,
            "history": self._level_history,
            "promotion_ready": self.is_promotion_ready(),
        }
