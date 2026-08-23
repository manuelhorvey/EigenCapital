"""Portfolio layer — exposure aggregation and risk-gated order planning.

Flow:
    StrategyIntent(s) → Portfolio → PortfolioTarget → EigenRisk → ApprovedTarget → OrderPlan

This layer answers: "What exposure does the collection of strategies want?"
EigenRisk answers: "What exposure is actually permitted?"
Execution answers: "What orders are necessary to move toward the approved target?"
"""

from eigencapital.portfolio.portfolio import Portfolio, PortfolioState

__all__ = ["Portfolio", "PortfolioState"]
