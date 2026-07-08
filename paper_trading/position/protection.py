from __future__ import annotations

import logging
from dataclasses import dataclass

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
        action = ProtectionAction()

        # Breakeven SL (does NOT return early — trailing stop check follows)
        be_threshold = config.get("breakeven_threshold_r", 0.5)
        if not position.breakeven_set and unrealized_r >= be_threshold:
            if position.is_long:
                position.risk_floor = max(position.risk_floor, position.avg_price)
            else:
                position.risk_floor = min(position.risk_floor, position.avg_price)
            position.breakeven_set = True
            action = ProtectionAction(action="breakeven", new_sl=position.risk_floor)

        # Event-driven trailing stop
        trail_activate = config.get("trail_activate_r", 1.0)
        trail_distance = config.get("trail_distance_r", 0.5)
        vol_est = position.vol

        if unrealized_r >= trail_activate and vol_est > 0:
            if position.is_long:
                distance_from_peak = position.peak_price - current_price
            else:
                distance_from_peak = current_price - position.peak_price
            peak_to_current_r = distance_from_peak / max(position.avg_price * vol_est, 1e-9)

            if peak_to_current_r <= 0:
                # Trail distance in price units = trail_distance_r * avg_price * vol_entry
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
    elif action.action == "trail":
        logger.info("%s: trailing stop moved to %.5f", engine.name, action.new_sl)
