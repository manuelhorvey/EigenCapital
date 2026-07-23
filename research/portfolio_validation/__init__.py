"""Portfolio A/B simulation framework.

Three-scenario comparison to validate label strategy changes before
production deployment:

    Scenario A — Current production (TB_v1, production calibration)
    Scenario B — Optimized (LabelStrategyRegistry, same calibration)
    Scenario C — Hybrid diagnostic (new labels, old calibration)

Usage:
    from research.portfolio_validation.scenarios import build_scenarios
    from research.portfolio_validation.runner import run_portfolio_simulation
    from research.portfolio_validation.reporting import print_comparison

    scenarios = build_scenarios()
    results = run_portfolio_simulation(scenarios)
    print_comparison(results)
"""

from research.portfolio_validation import scenarios
from research.portfolio_validation import runner
from research.portfolio_validation import metrics
from research.portfolio_validation import comparison
from research.portfolio_validation import reporting
