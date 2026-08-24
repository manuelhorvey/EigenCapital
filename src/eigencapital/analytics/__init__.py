"""Analytics — research validation and statistical testing.

The analytics layer is EigenCapital's hostile validation campaign.
Its purpose is to prove that research results are NOT genuine edges.

Modules:
    metrics — canonical performance metrics
    validation/ — walk-forward, bootstrap, permutation, sensitivity, etc.
"""

from eigencapital.analytics.metrics import PerformanceMetrics, compute_metrics, compute_returns

__all__ = ["PerformanceMetrics", "compute_metrics", "compute_returns"]
