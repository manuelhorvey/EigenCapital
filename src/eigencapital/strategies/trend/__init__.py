"""Cross-asset trend/momentum strategy — deliberately simple, no ML.

Hypothesis:
    Persistent price trends contain exploitable information at medium-term
    horizons, and a diversified, volatility-scaled implementation may retain
    positive risk-adjusted expectancy after realistic costs.

This is the FIRST strategy for EigenCapital — designed to test the
complete research pipeline, not to be profitable.

Constraints:
- ≤ 5-10 meaningful parameters
- No ML
- No parameter optimization marathon
- No strategy-specific risk exceptions
- No asset-specific magic numbers
- Costs included from first experiment
"""

from eigencapital.strategies.trend.strategy import CrossAssetTrendStrategy

__all__ = ["CrossAssetTrendStrategy"]
