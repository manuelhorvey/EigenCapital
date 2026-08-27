"""Account-level risk checks — drawdown, loss limits, leverage, equity.

All checks return RiskCheckResult with PASS, WARN, or FAIL status.
FAIL status causes position REJECTION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from eigencapital.core.models.risk_check_result import RiskCheckResult
from eigencapital.risk.policy import RiskPolicy


@dataclass
class AccountState:
    """Current account state for risk checks."""

    equity: float = 100_000.0
    peak_equity: float = 100_000.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    position_count: int = 0
    instrument_exposures: Dict[str, float] = field(default_factory=dict)
    asset_class_exposures: Dict[str, float] = field(default_factory=dict)


def check_max_drawdown(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if drawdown exceeds maximum allowed."""
    if state.peak_equity <= 0:
        return RiskCheckResult(
            check_id="max_drawdown",
            status="FAIL",
            observed=0,
            limit=policy.max_drawdown_pct,
            unit="%",
            message="Peak equity is zero or negative",
        )

    drawdown_pct = ((state.peak_equity - state.equity) / state.peak_equity) * 100

    if drawdown_pct > policy.max_drawdown_pct:
        status = "FAIL"
        msg = f"Drawdown {drawdown_pct:.1f}% exceeds maximum {policy.max_drawdown_pct}%"
    elif drawdown_pct > policy.warn_drawdown_pct:
        status = "WARN"
        msg = f"Drawdown {drawdown_pct:.1f}% approaching limit"
    else:
        status = "PASS"
        msg = f"Drawdown {drawdown_pct:.1f}% within limits"

    return RiskCheckResult(
        check_id="max_drawdown",
        status=status,
        observed=round(drawdown_pct, 2),
        limit=policy.max_drawdown_pct,
        unit="%",
        message=msg,
    )


def check_daily_loss(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if daily loss exceeds limit."""
    loss = abs(min(state.daily_pnl, 0))

    if loss > policy.daily_loss_limit:
        status = "FAIL"
        msg = f"Daily loss {loss:.0f} exceeds limit {policy.daily_loss_limit:.0f}"
    elif loss > policy.warn_daily_loss:
        status = "WARN"
        msg = f"Daily loss {loss:.0f} approaching limit"
    else:
        status = "PASS"
        msg = f"Daily loss {loss:.0f} within limits"

    return RiskCheckResult(
        check_id="daily_loss",
        status=status,
        observed=loss,
        limit=policy.daily_loss_limit,
        unit="USD",
        message=msg,
    )


def check_weekly_loss(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if weekly loss exceeds limit."""
    loss = abs(min(state.weekly_pnl, 0))

    if loss > policy.weekly_loss_limit:
        status = "FAIL"
        msg = f"Weekly loss {loss:.0f} exceeds limit {policy.weekly_loss_limit:.0f}"
    else:
        status = "PASS"
        msg = f"Weekly loss {loss:.0f} within limits"

    return RiskCheckResult(
        check_id="weekly_loss",
        status=status,
        observed=loss,
        limit=policy.weekly_loss_limit,
        unit="USD",
        message=msg,
    )


def check_gross_leverage(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if gross leverage exceeds maximum."""
    if state.equity <= 0:
        return RiskCheckResult(
            check_id="gross_leverage",
            status="FAIL",
            observed=0,
            limit=policy.max_gross_leverage,
            unit="x",
            message="Equity is zero or negative — cannot compute leverage",
        )

    leverage = abs(state.gross_exposure) / state.equity

    if leverage > policy.max_gross_leverage:
        status = "FAIL"
        msg = f"Gross leverage {leverage:.2f}x exceeds maximum {policy.max_gross_leverage:.1f}x"
    elif leverage > policy.warn_gross_leverage:
        status = "WARN"
        msg = f"Gross leverage {leverage:.2f}x approaching limit"
    else:
        status = "PASS"
        msg = f"Gross leverage {leverage:.2f}x within limits"

    return RiskCheckResult(
        check_id="gross_leverage",
        status=status,
        observed=round(leverage, 4),
        limit=policy.max_gross_leverage,
        unit="x",
        message=msg,
    )


def check_min_equity(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if equity is above minimum."""
    if state.equity < policy.min_equity:
        status = "FAIL"
        msg = f"Equity {state.equity:.0f} below minimum {policy.min_equity:.0f}"
    else:
        status = "PASS"
        msg = f"Equity {state.equity:.0f} above minimum"

    return RiskCheckResult(
        check_id="min_equity",
        status=status,
        observed=state.equity,
        limit=policy.min_equity,
        unit="USD",
        message=msg,
    )


def check_position_count(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if position count is within limit."""
    if state.position_count > policy.max_position_count:
        status = "FAIL"
        msg = f"Position count {state.position_count} exceeds maximum {policy.max_position_count}"
    else:
        status = "PASS"
        msg = f"Position count {state.position_count} within limits"

    return RiskCheckResult(
        check_id="max_position_count",
        status=status,
        observed=float(state.position_count),
        limit=float(policy.max_position_count),
        unit="count",
        message=msg,
    )


def check_kill_switch(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """Check if kill switch is activated."""
    if policy.kill_switch:
        return RiskCheckResult(
            check_id="kill_switch",
            status="FAIL",
            observed=1.0,
            limit=0.0,
            unit="bool",
            message="Kill switch ACTIVATED — all new positions rejected",
        )
    return RiskCheckResult(
        check_id="kill_switch",
        status="PASS",
        observed=0.0,
        limit=0.0,
        unit="bool",
        message="Kill switch inactive",
    )


def _pct(notional: float, equity: float) -> float:
    return (notional / equity * 100) if equity > 0 else float("inf")


def check_max_concentration(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """FAIL if any single instrument exceeds max_concentration_pct of equity."""
    if not getattr(state, "instrument_exposures", None):
        return RiskCheckResult(
            check_id="max_concentration",
            status="PASS",
            observed=0,
            limit=policy.max_concentration_pct,
            unit="%",
            message="No instrument exposures",
        )
    worst_sym, worst_notional = max(
        getattr(state, "instrument_exposures", {}).items(),
        key=lambda kv: abs(kv[1]),
    )
    pct = _pct(abs(worst_notional), state.equity)
    if pct > policy.max_concentration_pct:
        status, msg = (
            "FAIL",
            (f"{worst_sym} concentration {pct:.1f}% exceeds {policy.max_concentration_pct}% cap"),
        )
    elif pct > policy.warn_concentration_pct:
        status, msg = "WARN", f"{worst_sym} concentration {pct:.1f}% elevated"
    else:
        status, msg = "PASS", f"Max concentration {pct:.1f}% within limits"
    return RiskCheckResult(
        check_id="max_concentration",
        status=status,
        observed=round(pct, 2),
        limit=policy.max_concentration_pct,
        unit="%",
        message=msg,
    )


def check_asset_class_exposure(state: AccountState, policy: RiskPolicy) -> RiskCheckResult:
    """FAIL if any asset class exceeds max_asset_class_exposure_pct."""
    if not getattr(state, "asset_class_exposures", None):
        return RiskCheckResult(
            check_id="asset_class_exposure",
            status="PASS",
            observed=0,
            limit=policy.max_asset_class_exposure_pct,
            unit="%",
            message="No asset-class exposures",
        )
    worst_cls, worst_notional = max(
        getattr(state, "asset_class_exposures", {}).items(),
        key=lambda kv: abs(kv[1]),
    )
    pct = _pct(abs(worst_notional), state.equity)
    if pct > policy.max_asset_class_exposure_pct:
        status, msg = (
            "FAIL",
            (f"{worst_cls} exposure {pct:.1f}% exceeds {policy.max_asset_class_exposure_pct}% cap"),
        )
    elif pct > policy.warn_asset_class_exposure_pct:
        status, msg = "WARN", f"{worst_cls} exposure {pct:.1f}% elevated"
    else:
        status, msg = "PASS", f"Max class exposure {pct:.1f}% within limits"
    return RiskCheckResult(
        check_id="asset_class_exposure",
        status=status,
        observed=round(pct, 2),
        limit=policy.max_asset_class_exposure_pct,
        unit="%",
        message=msg,
    )


def run_all_account_checks(state: AccountState, policy: RiskPolicy) -> List[RiskCheckResult]:
    """Run all account-level risk checks."""
    return [
        check_kill_switch(state, policy),
        check_min_equity(state, policy),
        check_max_drawdown(state, policy),
        check_daily_loss(state, policy),
        check_weekly_loss(state, policy),
        check_gross_leverage(state, policy),
        check_position_count(state, policy),
        check_max_concentration(state, policy),
        check_asset_class_exposure(state, policy),
    ]
