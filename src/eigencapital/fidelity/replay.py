"""Deterministic Replay Campaign.

Runs the frozen R4 configuration against historical MT5 data in deterministic
replay mode. Compares research engine outputs against paper engine outputs
at every decision boundary.

This isolates software/implementation divergence from market-data divergence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
    ParitySummary,
    ParityBoundary,
)


class ReplayStatus(str, Enum):
    """Replay campaign status."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ReplayDecision:
    """A single decision point in the deterministic replay."""

    decision_id: str
    timestamp: str
    instrument_id: str
    research_signal: float
    paper_signal: float
    research_weight: float
    paper_weight: float
    research_position: float
    paper_position: float
    research_pnl: float
    paper_pnl: float
    is_intentional_divergence: bool = False
    divergence_explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "research_signal": self.research_signal,
            "paper_signal": self.paper_signal,
            "research_weight": self.research_weight,
            "paper_weight": self.paper_weight,
            "research_position": self.research_position,
            "paper_position": self.paper_position,
            "research_pnl": self.research_pnl,
            "paper_pnl": self.paper_pnl,
            "is_intentional_divergence": self.is_intentional_divergence,
            "divergence_explanation": self.divergence_explanation,
        }


@dataclass(frozen=True)
class ReplayResult:
    """Complete result of a deterministic replay campaign."""

    campaign_id: str
    manifest_identity: str
    total_decisions: int
    exact_matches: int
    expected_differences: int
    unexplained_divergences: int
    critical_divergences: int
    match_rate: float
    status: str  # "PASS", "WARNING", "CRITICAL"
    decisions: List[ReplayDecision] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "manifest_identity": self.manifest_identity,
            "total_decisions": self.total_decisions,
            "exact_matches": self.exact_matches,
            "expected_differences": self.expected_differences,
            "unexplained_divergences": self.unexplained_divergences,
            "critical_divergences": self.critical_divergences,
            "match_rate": self.match_rate,
            "status": self.status,
        }


class DeterministicReplayCampaign:
    """Deterministic replay of R4 against historical data.

    This campaign runs the frozen R4 configuration against the same
    historical data used in research, comparing every decision boundary.
    """

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest
        self._campaign_id = f"REPLAY-{manifest.compute_identity()[:12]}"
        self._parity = ResearchPaperParityEngine(self._campaign_id)
        self._decisions: List[ReplayDecision] = []
        self._status = ReplayStatus.CREATED
        self._decision_counter = 0

    def run(
        self,
        research_decisions: List[Dict[str, Any]],
        paper_decisions: List[Dict[str, Any]],
    ) -> ReplayResult:
        """Run the deterministic replay.

        Args:
            research_decisions: list of research engine outputs
            paper_decisions: list of paper engine outputs (same data, same config)

        Returns:
            ReplayResult with parity analysis
        """
        self._status = ReplayStatus.RUNNING

        if len(research_decisions) != len(paper_decisions):
            return ReplayResult(
                campaign_id=self._campaign_id,
                manifest_identity=self._manifest.compute_identity(),
                total_decisions=0,
                exact_matches=0,
                expected_differences=0,
                unexplained_divergences=0,
                critical_divergences=1,
                match_rate=0.0,
                status="CRITICAL",
            )

        for r_dec, p_dec in zip(research_decisions, paper_decisions):
            self._decision_counter += 1

            # Check each boundary
            self._parity.check_signal(
                timestamp=r_dec.get("timestamp", ""),
                instrument_id=r_dec.get("instrument_id", ""),
                research_signal=r_dec.get("signal", 0.0),
                paper_signal=p_dec.get("signal", 0.0),
            )

            self._parity.check_weight(
                timestamp=r_dec.get("timestamp", ""),
                instrument_id=r_dec.get("instrument_id", ""),
                research_weight=r_dec.get("weight", 0.0),
                paper_weight=p_dec.get("weight", 0.0),
            )

            self._parity.check_position(
                timestamp=r_dec.get("timestamp", ""),
                instrument_id=r_dec.get("instrument_id", ""),
                research_position=r_dec.get("position", 0.0),
                paper_position=p_dec.get("position", 0.0),
            )

            self._parity.check_pnl(
                timestamp=r_dec.get("timestamp", ""),
                instrument_id=r_dec.get("instrument_id", ""),
                research_pnl=r_dec.get("pnl", 0.0),
                paper_pnl=p_dec.get("pnl", 0.0),
            )

            # Record decision
            self._decisions.append(
                ReplayDecision(
                    decision_id=f"DEC-{self._decision_counter:06d}",
                    timestamp=r_dec.get("timestamp", ""),
                    instrument_id=r_dec.get("instrument_id", ""),
                    research_signal=r_dec.get("signal", 0.0),
                    paper_signal=p_dec.get("signal", 0.0),
                    research_weight=r_dec.get("weight", 0.0),
                    paper_weight=p_dec.get("weight", 0.0),
                    research_position=r_dec.get("position", 0.0),
                    paper_position=p_dec.get("position", 0.0),
                    research_pnl=r_dec.get("pnl", 0.0),
                    paper_pnl=p_dec.get("pnl", 0.0),
                )
            )

        self._status = ReplayStatus.COMPLETED
        summary = self._parity.get_summary()

        return ReplayResult(
            campaign_id=self._campaign_id,
            manifest_identity=self._manifest.compute_identity(),
            total_decisions=summary.total_checks,
            exact_matches=summary.exact_matches,
            expected_differences=summary.expected_differences,
            unexplained_divergences=summary.unexplained_divergences,
            critical_divergences=summary.critical_divergences,
            match_rate=summary.match_rate,
            status=summary.overall_status,
            decisions=list(self._decisions),
        )

    @property
    def status(self) -> ReplayStatus:
        return self._status

    @property
    def parity_engine(self) -> ResearchPaperParityEngine:
        return self._parity
