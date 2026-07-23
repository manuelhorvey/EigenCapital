"""TradeAttributionCalculator — deterministic post-trade attribution compiler.

Orchestrates all six attribution layers at trade finalization.
Reads from DecisionProvenance + lifecycle events + execution record,
writes a single immutable TradeAttribution once per trade.

Usage::

    calculator = TradeAttributionCalculator()
    attribution = calculator.calculate(
        trade_id="...",
        decision_id="...",
        lifecycle_version="v2_profit_floor",
        realized_r=2.0,
        provenance=decision_provenance,
        lifecycle_events=[...],
        collector_record=trade_attribution_record,
        exit_reason="PROFIT_LOCK",
        asset="GBPUSD",
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from eigencapital.domain.provenance.trade_attribution import (
    ATTRIBUTION_VERSION,
    TradeAttribution,
)

from research.attribution.exit_attribution import compute as compute_exit, COUNTERFACTUAL_VERSION_EXIT
from research.attribution.profit_floor_attribution import compute as compute_profit_floor, COUNTERFACTUAL_VERSION_PROFIT_FLOOR
from research.attribution.entry_attribution import compute as compute_entry
from research.attribution.calibration_attribution import compute as compute_calibration, COUNTERFACTUAL_VERSION_CALIBRATION
from research.attribution.portfolio_attribution import compute as compute_portfolio
from research.attribution.risk_attribution import compute as compute_risk

logger = logging.getLogger("eigencapital.attribution.calculator")


class TradeAttributionCalculator:
    """Compiles a complete TradeAttribution from all available data sources."""

    def calculate(
        self,
        *,
        trade_id: str,
        decision_id: str,
        lifecycle_version: str,
        realized_r: float,
        holding_period_candles: int = 0,
        exit_reason: str = "",
        asset: str = "",
        entry_archetype: str = "",
        # Layer-specific inputs
        static_exit_r: float | None = None,
        was_protected: bool = False,
        unprotected_exit_r: float | None = None,
        calibrated: bool = False,
        uncalibrated_signal_r: float | None = None,
        actual_allocation_pct: float | None = None,
        risk_intervention_active: bool = False,
        unrestricted_estimate_r: float | None = None,
        # Entry attribution inputs
        entry_price: float = 0.0,
        first_intervention_price: float | None = None,
        side: str = "",
        risk_pct: float = 1.0,
        collector_record: dict | None = None,
    ) -> TradeAttribution:
        """Compile attribution for a single trade at finalization."""

        # Layer 2: Exit attribution
        exit_alpha, exit_status, sr = compute_exit(
            realized_r=realized_r,
            static_exit_r=static_exit_r,
            collector_record=collector_record,
        )

        # Layer 3: Profit floor attribution
        pf_alpha, pf_status, no_pf_r = compute_profit_floor(
            realized_r=realized_r,
            was_protected=was_protected,
            unprotected_exit_r=unprotected_exit_r,
        )

        # Layer 4: Calibration attribution
        cal_alpha, cal_status, unc_sig_r = compute_calibration(
            realized_r=realized_r,
            calibrated=calibrated,
            uncalibrated_signal_r=uncalibrated_signal_r,
        )

        # Layer 1: Entry attribution
        entry_alpha, entry_status = compute_entry(
            realized_r=realized_r,
            entry_price=entry_price,
            first_intervention_price=first_intervention_price,
            side=side,
            risk=risk_pct,
        )

        # Layer 5: Portfolio attribution
        port_alpha, port_status = compute_portfolio(
            realized_r=realized_r,
            actual_allocation_pct=actual_allocation_pct,
        )

        # Layer 6: Risk attribution
        risk_alpha, risk_status = compute_risk(
            realized_r=realized_r,
            risk_intervention_active=risk_intervention_active,
            unrestricted_estimate_r=unrestricted_estimate_r,
        )

        return TradeAttribution(
            trade_id=trade_id,
            decision_id=decision_id,
            lifecycle_version=lifecycle_version,
            attribution_version=ATTRIBUTION_VERSION,
            realized_r=realized_r,
            holding_period_candles=holding_period_candles,
            entry_archetype=entry_archetype,
            exit_reason=exit_reason,
            asset=asset,
            created_at=datetime.now(timezone.utc).isoformat(),
            # Layer contributions
            entry_alpha_r=entry_alpha,
            entry_alpha_status=entry_status,
            calibration_alpha_r=cal_alpha,
            calibration_alpha_status=cal_status,
            exit_alpha_r=exit_alpha,
            exit_alpha_status=exit_status,
            profit_floor_alpha_r=pf_alpha,
            profit_floor_alpha_status=pf_status,
            portfolio_alpha_r=port_alpha,
            portfolio_alpha_status=port_status,
            risk_alpha_r=risk_alpha,
            risk_alpha_status=risk_status,
            # Counterfactual references
            static_exit_r=sr,
            counterfactual_version_exit=COUNTERFACTUAL_VERSION_EXIT if exit_status == "APPLIED" else None,
            uncalibrated_signal_r=unc_sig_r,
            counterfactual_version_calibration=COUNTERFACTUAL_VERSION_CALIBRATION if cal_status == "APPLIED" else None,
            no_profit_floor_r=no_pf_r,
            counterfactual_version_profit_floor=COUNTERFACTUAL_VERSION_PROFIT_FLOOR if pf_status == "APPLIED" else None,
        )
