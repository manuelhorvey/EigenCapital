"""EquityTracker — portfolio equity, returns, and VaR/CVaR tracking.

Extracted from ``EngineOrchestrator`` as part of MAINT-01 (split oversized
modules).  Owns the rolling portfolio returns list, previous-value tracking
for daily return computation, and VaR/CVaR calculation.

Does NOT own actor iteration — callers pass the portfolio value directly.

Usage:
    tracker = EquityTracker()
    var_95, cvar_95 = tracker.record_return(portfolio_value)
    vol = tracker.portfolio_vol_estimate()
    tracker.reset()  # test fixture cleanup
"""

from __future__ import annotations

from typing import Any

from paper_trading.orchestrator.health import compute_var_cvar, portfolio_vol_estimate

# Maximum rolling return window (252 trading days ≈ 1 year)
_MAX_RETURN_WINDOW = 252


class EquityTracker:
    """Tracks portfolio equity, rolling returns, and VaR/CVaR.

    Owns:
        - ``portfolio_returns`` — rolling list of daily portfolio returns
        - ``var_baseline_vol`` — baseline volatility estimate for monitoring
        - ``var_prev_value`` — previous portfolio value for computing daily return

    Callers pass the current portfolio value each cycle; the tracker
    computes the daily return and updates VaR/CVaR.
    """

    def __init__(self) -> None:
        self.portfolio_returns: list[float] = []
        self.var_baseline_vol: float | None = None
        self.var_prev_value: float | None = None

    def record_return(self, portfolio_value: float) -> tuple[float | None, float | None]:
        """Record a portfolio return and compute VaR/CVaR.

        Computes the daily return as ``(pv - prev) / prev`` where ``pv``
        is the current portfolio value.  Appends the return to the rolling
        window (trimmed to ``_MAX_RETURN_WINDOW``) and returns
        ``(var_95, cvar_95)`` if enough data exists, else ``(None, None)``.

        Updates ``var_prev_value`` to ``portfolio_value`` for the next cycle.
        """
        var_95: float | None = None
        cvar_95: float | None = None

        if (
            portfolio_value > 0
            and self.var_prev_value is not None
            and self.var_prev_value > 0
        ):
            r = (portfolio_value - self.var_prev_value) / self.var_prev_value
            self.portfolio_returns.append(r)
            if len(self.portfolio_returns) > _MAX_RETURN_WINDOW:
                self.portfolio_returns = self.portfolio_returns[-_MAX_RETURN_WINDOW:]
            var_95, cvar_95 = compute_var_cvar(
                self.portfolio_returns, window=60, percentile=0.05,
            )
            if var_95 is not None:
                var_95 = round(var_95, 6)
            if cvar_95 is not None:
                cvar_95 = round(cvar_95, 6)

        self.var_prev_value = portfolio_value
        return var_95, cvar_95

    def portfolio_vol_estimate(self) -> float | None:
        """Estimate daily portfolio return vol from rolling returns (60-day)."""
        return portfolio_vol_estimate(self.portfolio_returns)

    def reset(self) -> None:
        """Clear all tracked state.  Call in test fixtures."""
        self.portfolio_returns.clear()
        self.var_baseline_vol = None
        self.var_prev_value = None

    def snapshot_dict(self) -> dict[str, Any]:
        """Return current tracker state as a dict for export/debugging."""
        return {
            "n_returns": len(self.portfolio_returns),
            "var_baseline_vol": self.var_baseline_vol,
            "var_prev_value": self.var_prev_value,
            "portfolio_vol": self.portfolio_vol_estimate(),
        }
