"""Phase 1R — R4 Paper Fidelity & Execution Qualification.

Frozen R4 configuration + research→paper parity + fidelity verdict.
"""

from eigencapital.fidelity.forward import ForwardPaperCampaign
from eigencapital.fidelity.parity import (
    ParityBoundary,
    ParityCheckResult,
    ResearchPaperParityEngine,
)
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.replay import DeterministicReplayCampaign
from eigencapital.fidelity.verdict import FidelityGate, FidelityVerdict

__all__ = [
    "DeterministicReplayCampaign",
    "FidelityGate",
    "FidelityVerdict",
    "ForwardPaperCampaign",
    "ParityBoundary",
    "ParityCheckResult",
    "R4ConfigManifest",
    "ResearchPaperParityEngine",
]
