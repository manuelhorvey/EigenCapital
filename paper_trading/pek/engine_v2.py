"""RiskEngineV2 — adaptive risk budgeting from portfolio + performance state.

Consumes PortfolioStateSnapshot and PerformanceState, produces RiskBudget.
The budget is then consumed by the PEK (Portfolio Execution Kernel).

Key invariant:
    RiskEngineV2 can only REDUCE risk below config base. It NEVER expands
    risk beyond what the mode config defines. The PEK applies the final
    clamp: final_risk = min(config.max_risk, budget.max_risk_per_trade_pct).
"""

from __future__ import annotations

import logging
from typing import Any

from paper_trading.pek.contracts.performance_state import PerformanceState
from paper_trading.pek.contracts.portfolio_state import PortfolioStateSnapshot
from paper_trading.pek.contracts.risk_budget import RiskBudget

logger = logging.getLogger("eigencapital.pek.engine_v2")


class RiskEngineV2:
    """Adaptive risk budget computation.

    Call compute_budget() once per cycle in the pre-phase, after the
    PortfolioStateSnapshot and PerformanceState have been built.
    The output RiskBudget is consumed by the PEK for admission decisions.
    """

    def __init__(self, mode_config: dict[str, Any]):
        self._mode = mode_config

    def compute_budget(
        self,
        portfolio: PortfolioStateSnapshot,
        perf: PerformanceState,
    ) -> RiskBudget:
        """Compute the adaptive risk budget for the current cycle.

        Args:
            portfolio: Frozen portfolio state snapshot (built pre-phase).
            perf: Frozen performance state (built after previous cycle's Phase 4).

        Returns:
            RiskBudget: effective risk limits for this cycle.
        """
        # ── Base risk from config ──
        base_risk = self._mode.get("max_risk_per_trade_pct", 1.0)
        min_risk = self._mode.get("min_risk_per_trade_pct", 0.10)

        # ── Drawdown scalar — tighter as drawdown deepens ──
        dd = portfolio.drawdown_pct
        dd_limit = self._mode.get("max_drawdown_pct", -0.15)
        if dd <= dd_limit:
            dd_scalar = 0.0  # circuit breaker territory
        elif dd <= dd_limit * 0.75:  # within 75% of limit
            dd_scalar = 0.5
        elif dd <= dd_limit * 0.5:  # within 50% of limit
            dd_scalar = 0.75
        else:
            dd_scalar = 1.0

        # ── Performance composite scalar ──
        perf_scalar = perf.composite_scalar

        # ── Volatility scalar (light adjustment only — heavy adjustment is in perf state) ──
        vol_scalar = min(1.0, perf.market_scalar * 1.2)

        # ── Effective risk ──
        effective = base_risk * dd_scalar * perf_scalar * vol_scalar
        # Allow full halt (effective=0) at drawdown limit; otherwise apply min_risk floor
        if dd_scalar == 0.0:
            effective = 0.0
        else:
            effective = max(min_risk, min(base_risk, effective))

        # ── Portfolio heat ──
        max_heat = self._mode.get("max_leverage", 2.0)
        current_heat = portfolio.gross_exposure / max(portfolio.total_equity, 1.0)
        heat_cap = max_heat * 0.9 if current_heat > max_heat * 0.9 else max_heat

        # ── Max concurrent positions ──
        max_concurrent = self._mode.get("max_concurrent_positions", 21)

        return RiskBudget(
            max_risk_per_trade_pct=round(effective, 4),
            max_portfolio_heat=heat_cap,
            max_concurrent_positions=max_concurrent,
            volatility_scalar=round(vol_scalar, 4),
            drawdown_scalar=round(dd_scalar, 4),
            performance_scalar=round(perf_scalar, 4),
            velocity_scalar=round(perf.velocity_scalar, 4),
        )
