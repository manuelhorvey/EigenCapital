"""Statistical validation — hostile testing of research hypotheses.

The validation layer tries to DISPROVE trading edges, not confirm them.

Modules:
    walk_forward — purged walk-forward analysis
    bootstrap — bootstrap and permutation tests
    sensitivity — parameter sensitivity analysis
    cost_stress — cost stress testing
    regime — regime analysis
    evidence_gate — evidence gate for hypothesis disposition
"""

from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult,
    purged_walk_forward,
)
from eigencapital.analytics.validation.bootstrap import (
    BootstrapResult,
    bootstrap_test,
    permutation_test,
)
from eigencapital.analytics.validation.sensitivity import (
    SensitivityResult,
    parameter_sensitivity,
)
from eigencapital.analytics.validation.cost_stress import (
    CostStressResult,
    cost_stress_test,
)
from eigencapital.analytics.validation.regime import RegimeResult, regime_analysis
from eigencapital.analytics.validation.evidence_gate import (
    EvidenceGate,
    EvidenceVerdict,
)

__all__ = [
    "WalkForwardResult",
    "purged_walk_forward",
    "BootstrapResult",
    "bootstrap_test",
    "permutation_test",
    "SensitivityResult",
    "parameter_sensitivity",
    "CostStressResult",
    "cost_stress_test",
    "RegimeResult",
    "regime_analysis",
    "EvidenceGate",
    "EvidenceVerdict",
]
