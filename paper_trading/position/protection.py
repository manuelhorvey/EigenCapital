"""Position-level stop loss protection (breakeven + profit floor + trailing stops).

PositionProtection.update() is called each cycle to evaluate whether a
position's stop loss should be adjusted:
1. Breakeven lock: Moves SL to entry price when unrealized R >= threshold
2. Profit floor protection: Lifecycle state machine that sets a hard
   minimum exit floor after a validated favorable excursion. Once the
   peak R exceeds ``trigger_r`` (default 2.5), a floor at ``floor_r``
   (default 2.0) is enforced via risk_floor. The floor persists even if
   price recovers — this is the key differentiator from a trailing stop.
3. Trail: Tightens SL behind price as favorable excursion increases
   (can further tighten beyond the profit floor).

All operations update position.risk_floor which feeds into the
effective_sl computation (max of current SL and risk_floor for longs).

Key exports:
- PositionProtection: Stateless protection logic
- check_profit_floor_exit: Dedicated profit floor exit check returning
  (should_exit, exit_price, exit_reason) tuple
- _update_position_protection: Legacy wrapper for backward compatibility

Config keys:
- breakeven_threshold_r (default 0.5): R-multiple to trigger breakeven
- profit_lock_trigger_r (default 2.5): R-multiple to activate profit floor
- profit_lock_floor_r (default 2.0): R-multiple floor to protect when active
- trail_activate_r (default 1.0): R-multiple to activate trailing
- trail_distance_r (default 0.5): Trailing stop distance in R-units
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from eigencapital.domain.entities.position import ProfitLockState

logger = logging.getLogger("eigencapital.position_protection")


@dataclass
class ProtectionAction:
    action: str = "none"
    new_sl: float | None = None


class PositionProtection:
    @staticmethod
    def update(position, current_price: float | None, config: dict) -> ProtectionAction:
        if position is None or current_price is None or current_price <= 0:
            return ProtectionAction()

        if position.is_long:
            position.peak_price = max(position.peak_price, current_price)
        else:
            position.peak_price = min(position.peak_price, current_price) if position.peak_price > 0 else current_price

        unrealized_r = PositionProtection._unrealized_r(position, current_price)
        vol_est = position.vol
        action = ProtectionAction()

        # Breakeven SL (does NOT return early — trailing stop check follows)
        be_threshold = config.get("breakeven_threshold_r", 0.5)
        if not position.breakeven_set and unrealized_r >= be_threshold:
            if position.is_long:
                position.risk_floor = max(position.risk_floor, position.avg_price)
            else:
                if position.risk_floor == 0:
                    position.risk_floor = position.avg_price
                else:
                    position.risk_floor = min(position.risk_floor, position.avg_price)
            position.breakeven_set = True
            action = ProtectionAction(action="breakeven", new_sl=position.risk_floor)

        # ── Profit floor protection: lifecycle state machine ──────────────
        pl_enabled = config.get("profit_lock_enabled", False)
        pl_trigger_r = config.get("profit_lock_trigger_r", 2.5)
        pl_floor_r = config.get("profit_lock_floor_r", 2.0)

        if pl_enabled:
            # Initialize state on first call
            if position.profit_lock_state is None:
                position.profit_lock_state = ProfitLockState(
                    enabled=True,
                    trigger_r=pl_trigger_r,
                    floor_r=pl_floor_r,
                )

            pls = position.profit_lock_state

            # Track highest R seen (persistent — survives price dips)
            if unrealized_r > pls.highest_r_seen:
                pls.highest_r_seen = unrealized_r

            # Check trigger: has the trade ever reached trigger_r?
            if not pls.triggered and pls.highest_r_seen >= pl_trigger_r:
                pls.triggered = True
                pls.trigger_timestamp = datetime.now(timezone.utc).isoformat()
                pls.trigger_price = current_price
                pls.trigger_mfe = pls.highest_r_seen

                # Set risk_floor to protect floor_r
                if position.is_long:
                    locked_floor = position.avg_price + pl_floor_r * position.avg_price * vol_est
                    position.risk_floor = max(position.risk_floor, locked_floor)
                else:
                    locked_floor = position.avg_price - pl_floor_r * position.avg_price * vol_est
                    if position.risk_floor == 0:
                        position.risk_floor = locked_floor
                    else:
                        position.risk_floor = min(position.risk_floor, locked_floor)

                action = ProtectionAction(action="profit_floor", new_sl=position.risk_floor)
                logger.info(
                    "Profit floor LOCKED at %.5f (trigger=%.1fR, floor=%.1fR, mfe=%.2fR)",
                    position.risk_floor, pl_trigger_r, pl_floor_r, pls.highest_r_seen,
                )

        # Event-driven trailing stop (can further tighten beyond profit floor)
        trail_activate = config.get("trail_activate_r", 1.0)
        trail_distance = config.get("trail_distance_r", 0.5)

        if unrealized_r >= trail_activate and vol_est > 0:
            if position.is_long:
                distance_from_peak = position.peak_price - current_price
            else:
                distance_from_peak = current_price - position.peak_price
            peak_to_current_r = distance_from_peak / max(position.avg_price * vol_est, 1e-9)

            if peak_to_current_r <= 0:
                trail_price = trail_distance * position.avg_price * vol_est
                if position.is_long:
                    new_floor = current_price - trail_price
                    if new_floor > position.risk_floor:
                        position.risk_floor = new_floor
                        action = ProtectionAction(action="trail", new_sl=new_floor)
                else:
                    new_floor = current_price + trail_price
                    if position.risk_floor == 0 or new_floor < position.risk_floor:
                        position.risk_floor = new_floor
                        action = ProtectionAction(action="trail", new_sl=new_floor)

        return action

    @staticmethod
    def _unrealized_r(position, current_price: float) -> float:
        if position is None or position.avg_price <= 0 or position.vol <= 0:
            return 0.0
        if position.is_long:
            return (current_price - position.avg_price) / (position.avg_price * position.vol)
        else:
            return (position.avg_price - current_price) / (position.avg_price * position.vol)


def check_profit_floor_exit(position, current_price: float) -> tuple[bool, float | None, str | None]:
    """Check whether the profit floor exit condition is met.

    Returns (should_exit, exit_price, exit_reason).
    Should be called AFTER PositionProtection.update() each cycle.
    """
    if position is None or position.profit_lock_state is None:
        return False, None, None
    pls = position.profit_lock_state
    if not pls.enabled or not pls.triggered:
        return False, None, None

    effective = position.effective_sl
    if effective is None or effective <= 0:
        return False, None, None

    if position.is_long and current_price <= effective:
        return True, effective, "PROFIT_LOCK"
    elif not position.is_long and current_price >= effective:
        return True, effective, "PROFIT_LOCK"

    return False, None, None


# ── Backward-compatible wrapper ──────────────────────────────────────────────


def _update_position_protection(ctx, df=None) -> None:
    """Legacy wrapper — delegates to PositionProtection.update()."""
    engine = ctx.engine
    pos = engine.pos_mgr.position
    current_price = getattr(engine, "current_price", None)
    config = getattr(engine, "config", {})
    action = PositionProtection.update(pos, current_price, config)
    if action.action == "breakeven":
        logger.info("%s: breakeven SL activated at %.5f", engine.name, action.new_sl)
    elif action.action == "profit_floor":
        logger.info("%s: profit floor locked at %.5f", engine.name, action.new_sl)
    elif action.action == "trail":
        logger.info("%s: trailing stop moved to %.5f", engine.name, action.new_sl)
