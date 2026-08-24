"""Phase 1R — R4 Paper Fidelity & Execution Qualification.

Frozen R4 configuration + research→paper parity + fidelity verdict.
"""

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
    ParityCheckResult,
    ParityBoundary,
)
from eigencapital.fidelity.replay import DeterministicReplayCampaign
from eigencapital.fidelity.forward import ForwardPaperCampaign
from eigencapital.fidelity.verdict import FidelityVerdict, FidelityGate

__all__ = [
    "R4ConfigManifest",
    "ResearchPaperParityEngine",
    "ParityCheckResult",
    "ParityBoundary",
    "DeterministicReplayCampaign",
    "ForwardPaperCampaign",
    "FidelityVerdict",
    "FidelityGate",
]
