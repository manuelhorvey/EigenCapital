"""Statistical validation — hostile testing of research hypotheses.

The validation layer tries to DISPROVE trading edges, not confirm them.

Modules:
    walk_forward — purged and embargoed walk-forward analysis
    bootstrap — bootstrap and permutation tests
    sensitivity — parameter sensitivity analysis
    cost_stress — cost stress testing
    regime — regime analysis
    deflated_sharpe — selection-bias-aware Sharpe significance (DSR)
    factor_evaluation — IC, quantile analysis, factor turnover
    evidence_gate — evidence gate for hypothesis disposition
"""

from eigencapital.analytics.validation.bootstrap import (
    BootstrapResult,
    bootstrap_test,
    permutation_test,
)
from eigencapital.analytics.validation.cost_stress import (
    CostStressResult,
    cost_stress_test,
)
from eigencapital.analytics.validation.deflated_sharpe import (
    DeflatedSharpeResult,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
)
from eigencapital.analytics.validation.evidence_gate import (
    EvidenceGate,
    EvidenceVerdict,
)
from eigencapital.analytics.validation.factor_evaluation import (
    ICResult,
    QuantileResult,
    TurnoverResult,
    factor_turnover,
    information_coefficient,
    quantile_analysis,
    quantile_spread_series,
    spearman_correlation,
)
from eigencapital.analytics.validation.regime import RegimeResult, regime_analysis
from eigencapital.analytics.validation.sensitivity import (
    SensitivityResult,
    parameter_sensitivity,
)
from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult,
    purged_walk_forward,
)

__all__ = [
    "BootstrapResult",
    "CostStressResult",
    "DeflatedSharpeResult",
    "EvidenceGate",
    "EvidenceVerdict",
    "ICResult",
    "QuantileResult",
    "RegimeResult",
    "SensitivityResult",
    "TurnoverResult",
    "WalkForwardResult",
    "bootstrap_test",
    "cost_stress_test",
    "deflated_sharpe_ratio",
    "expected_maximum_sharpe",
    "factor_turnover",
    "information_coefficient",
    "parameter_sensitivity",
    "permutation_test",
    "purged_walk_forward",
    "quantile_analysis",
    "quantile_spread_series",
    "regime_analysis",
    "spearman_correlation",
]
