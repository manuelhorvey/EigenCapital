"""PortfolioAdmissionController — the PEK (Portfolio Execution Kernel).

Centralized admission gate that replaces the distributed per-cycle budget_ref.
All admission decisions go through this single controller.

Two-stage design:
    Stage A — Fast admission filter (hard constraint checks)
    Stage B — Portfolio optimizer ranking (if enabled)

Key invariant: PEK is the ONLY execution gate. No trade enters without PEK approval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from paper_trading.orchestrator.admission.signal import AdmissionSignal
from paper_trading.pek.contracts.portfolio_state import PortfolioStateSnapshot
from paper_trading.pek.contracts.risk_budget import RiskBudget

logger = logging.getLogger("quantforge.orchestrator.admission")


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""  # populated on reject
    can_defer: bool = False
    defer_max_cycles: int = 0


@dataclass
class BudgetDelta:
    """What was consumed by the admitted signals this cycle.
    Applied to the next cycle's snapshot."""

    leverage_consumed: float = 0.0
    daily_loss_consumed: float = 0.0
    positions_added: int = 0
    positions_closed: dict[str, float] = field(default_factory=dict)  # asset -> notional freed


@dataclass
class AdmissionResult:
    admitted: list[AdmissionSignal] = field(default_factory=list)
    rejected: list[tuple[AdmissionSignal, str]] = field(default_factory=list)  # (signal, reason)
    deferred: list[tuple[AdmissionSignal, int]] = field(default_factory=list)  # (signal, max_cycles)
    budget_delta: BudgetDelta = field(default_factory=BudgetDelta)
    ranking_scores: dict[str, float] = field(default_factory=dict)


class PortfolioAdmissionController:
    """Portfolio Execution Kernel — single-threaded admission controller.

    Sits between Phase 1a (parallel signal generation) and Phase 1c (entry execution).
    """

    def __init__(self, mode_config: dict[str, Any]):
        self._mode = mode_config
        ranking_cfg = mode_config.get("position_ranking", {})
        self._ranking_enabled = ranking_cfg.get("enabled", False)
        self._weights = ranking_cfg.get("ranking_weights", {})
        self._deferred_decay = ranking_cfg.get("deferred_entry_decay", 0.90)
        self._stale_after = ranking_cfg.get("stale_after_cycles", 5)

    # ── Stage A: Fast admission filter ──

    def fast_filter(
        self,
        signal: AdmissionSignal,
        snapshot: PortfolioStateSnapshot,
    ) -> FilterResult:
        """Hard constraint checks. Runs FIRST, before any ranking.
        Returns PASS | HARD_REJECT. Never returns DEFER — defer decisions
        are made by the decision pipeline's entry optimization, not here."""

        # 1. Concurrent positions
        if snapshot.concurrent_remaining <= 0:
            return FilterResult(False, "max_concurrent_positions_reached")

        # 2. Daily loss budget
        if signal.risk_usd > snapshot.daily_loss_remaining:
            return FilterResult(False, "daily_loss_budget_exhausted")

        # 3. Leverage budget
        if signal.notional_requested > snapshot.leverage_remaining:
            return FilterResult(False, "leverage_budget_exhausted")

        # 4. Drawdown headroom
        projected_dd_pct = signal.risk_usd / max(snapshot.total_equity, 1.0)
        max_loss_frac = abs(snapshot.max_daily_loss) / max(snapshot.total_equity, 1.0)
        if abs(snapshot.drawdown_pct) + projected_dd_pct > max_loss_frac:
            return FilterResult(False, "drawdown_limit_would_be_exceeded")

        # 5. Factor exposure headroom
        from shared.factor_model import FACTOR_GROUPS

        for factor_name, headroom in snapshot.factor_headroom:
            assets_in_factor = FACTOR_GROUPS.get(factor_name, frozenset())
            notional_frac = signal.notional_requested / max(snapshot.total_equity, 1.0)
            if signal.asset in assets_in_factor and headroom < notional_frac:
                return FilterResult(False, f"factor_exposure_limit_{factor_name}")

        # 6. Per-asset gates
        for gate in snapshot.asset_gates:
            if gate.asset == signal.asset and not gate.all_ok:
                return FilterResult(False, "asset_gate_blocked")

        # 7. Stale signal check
        if signal.deferred_cycles > self._stale_after:
            return FilterResult(False, "signal_stale")

        return FilterResult(True)

    # ── Stage B: Portfolio optimizer ranking ──

    def rank_and_allocate(
        self,
        candidates: list[AdmissionSignal],
        snapshot: PortfolioStateSnapshot,
        risk_budget: RiskBudget,
    ) -> AdmissionResult:
        """Rank eligible signals and allocate budget.

        Only called after fast_filter has been applied to all candidates.
        """
        if not candidates:
            return AdmissionResult()

        # Build scoring
        scored: list[tuple[float, AdmissionSignal]] = []
        for sig in candidates:
            score = self._compute_score(sig, snapshot) if self._ranking_enabled else sig.calibrated_prob
            scored.append((score, sig))

        # Sort descending by score
        scored.sort(key=lambda x: -x[0])
        ranking_scores = {s.asset: round(s, 4) for s, _ in scored}

        # Allocate
        admitted: list[AdmissionSignal] = []
        rejected: list[tuple[AdmissionSignal, str]] = []
        deferred: list[tuple[AdmissionSignal, int]] = []

        remaining_leverage = snapshot.leverage_remaining
        remaining_daily_loss = snapshot.daily_loss_remaining
        remaining_concurrent = snapshot.concurrent_remaining

        for score, sig in scored:
            # Check budget (re-check after previous allocations consumed some)
            if sig.notional_requested > remaining_leverage:
                rejected.append((sig, "leverage_budget_exhausted"))
                continue
            if sig.risk_usd > remaining_daily_loss:
                rejected.append((sig, "daily_loss_budget_exhausted"))
                continue
            if remaining_concurrent <= 0:
                rejected.append((sig, "max_concurrent_positions_reached"))
                continue

            # Admit
            admitted.append(sig)
            remaining_leverage -= sig.notional_requested
            remaining_daily_loss -= sig.risk_usd
            remaining_concurrent -= 1

        result = AdmissionResult(
            admitted=admitted,
            rejected=rejected,
            deferred=deferred,
            ranking_scores=ranking_scores,
        )

        # Build budget delta from admitted signals
        result.budget_delta = BudgetDelta(
            leverage_consumed=sum(sig.notional_requested for sig in admitted),
            daily_loss_consumed=sum(sig.risk_usd for sig in admitted),
            positions_added=len(admitted),
        )

        return result

    def _compute_score(self, signal: AdmissionSignal, snapshot: PortfolioStateSnapshot) -> float:
        """Composite score for ranking. Formula config-driven."""
        w_prob = self._weights.get("calibrated_probability", 0.30)
        w_ev = self._weights.get("expected_value_r", 0.25)
        w_rr = self._weights.get("risk_adjusted_reward", 0.20)
        w_regime = self._weights.get("regime_confidence", 0.15)
        w_corr = self._weights.get("correlation_penalty", -0.10)

        # Correlation penalty: penalize piling into a correlated cluster on the same side
        corr_penalty = 0.0
        for cluster in snapshot.clusters:
            if signal.asset in cluster.assets:
                if cluster.dominant_side is not None and signal.side.value == cluster.dominant_side:
                    corr_penalty = 0.1 * min(cluster.position_count - 1, 5) / 5.0
                break

        # Age decay for deferred entries
        age_decay = self._deferred_decay**signal.deferred_cycles

        raw = (
            w_prob * signal.calibrated_prob
            + w_ev * max(0.0, signal.expected_value_r)
            + w_rr * min(signal.tp_sl_ratio / 5.0, 1.0)
            + w_regime * signal.regime_confidence
            + w_corr * corr_penalty
        ) * age_decay

        return max(0.0, raw)

    # ── Main entry point ──

    def run_admission(
        self,
        candidates: list[AdmissionSignal],
        snapshot: PortfolioStateSnapshot,
        risk_budget: RiskBudget,
    ) -> AdmissionResult:
        """Complete admission pipeline.

        1. Stage A: fast_filter each candidate
        2. Stage B: rank_and_allocate passed signals
        3. Return AdmissionResult with admitted, rejected, deferred, budget_delta
        """
        # Stage A: fast filter
        passed: list[AdmissionSignal] = []
        rejected: list[tuple[AdmissionSignal, str]] = []

        for sig in candidates:
            result = self.fast_filter(sig, snapshot)
            if result.passed:
                passed.append(sig)
            else:
                rejected.append((sig, result.reason))

        if not passed:
            return AdmissionResult(rejected=rejected)

        # Stage B: rank and allocate
        result = self.rank_and_allocate(passed, snapshot, risk_budget)
        result.rejected.extend(rejected)

        logger.info(
            "ADMISSION: %d admitted, %d rejected, %d deferred (%.2f%% budget used)",
            len(result.admitted),
            len(result.rejected),
            len(result.deferred),
            result.budget_delta.leverage_consumed
            / max(snapshot.leverage_remaining + result.budget_delta.leverage_consumed, 1.0)
            * 100,
        )

        return result
