import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from paper_trading.ops import diagnostics as diag
from paper_trading.ops import wrappers as _w
from paper_trading.ops.tracer import (
    shadow_compare_pnl,
    shadow_compare_sltp,
    trace_diagnostic_report,
)
from paper_trading.shadow.memory import store_event as _shadow_store

logger = logging.getLogger("quantforge.pnl_controller")

ET = pytz.timezone("US/Eastern")


def _sync_broker_sltp(asset) -> None:
    """Push current SL/TP to the real broker (MT5) after in-memory adjustment."""
    mt5_ticket = asset.position.get("mt5_ticket") if asset.position else None
    if mt5_ticket is None:
        return
    bridge = getattr(asset, "execution_bridge", None)
    if bridge is None or not getattr(bridge, "_is_real_broker", False):
        return
    pos = asset.pos_mgr.position
    if pos is None:
        return
    try:
        bridge.broker.modify_position(asset.ticker, str(mt5_ticket), sl=float(pos.stop_loss), tp=float(pos.take_profit))
    except Exception as e:
        logger.debug("%s: MT5 modify_position failed: %s", asset.name, e)


class AssetPnlController:
    def __init__(self, asset):
        self.asset = asset

    def update_pnl(self):
        asset = self.asset
        asset._ensure_position_synced()
        mtm = self.mtm_value
        if mtm > asset.peak_value:
            asset.peak_value = mtm
        self._track_running_excursion(asset)

        max_hold = asset.config.get("max_holding_days")
        if (
            asset.pos_mgr.has_position()
            and asset.current_price is not None
            and self._check_intraday_sltp(asset, max_hold)
        ):
            return

        self._settle_daily_pnl(asset)

    def _check_intraday_sltp(self, asset, max_hold) -> bool:
        self._reconcile_position_tp(asset)
        self._tick_shadow_sltp(asset)
        self._check_scale_out_tiers(asset)
        if self._check_sltp_hit(asset):
            return True
        self._apply_trailing_stop(asset)
        return self._check_time_stop(asset, max_hold)

    def _tick_shadow_sltp(self, asset) -> None:
        if hasattr(asset, "_shadow_sltp") and asset._shadow_sltp is not None and asset._shadow_sltp.is_active:
            data = getattr(asset, "price_data", None)
            if data is None:
                data = getattr(asset, "_price_df", None)
            if data is not None:
                asset._shadow_sltp.tick(
                    asset.current_price,
                    data,
                    str(datetime.now(tz=ET).date()),
                )

    def _reconcile_position_tp(self, asset) -> None:
        if not asset.pos_mgr.has_position():
            return
        if not asset.config.get("dynamic_sltp", {}).get("enabled", False):
            return
        if getattr(asset, "_tp_reconciled", False):
            return

        entry_price = asset.pos_mgr.position.entry_price
        initial_sl = getattr(asset, "_initial_sl", None)
        if initial_sl is None:
            return

        sl_dist = abs(initial_sl - entry_price)
        if sl_dist <= 0:
            return

        entry_state = getattr(asset, "_entry_validity_state", None)
        state = (
            entry_state
            if entry_state
            else (asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW")
        )
        archetype = getattr(asset, "_entry_archetype", "UNKNOWN")

        data = getattr(asset, "price_data", None)
        if data is None:
            data = getattr(asset, "_price_df", None)
        if data is None:
            return

        from paper_trading.entry.tp_compiler import compute_take_profit

        tp_geo = compute_take_profit(
            entry_price,
            sl_dist,
            state,
            archetype,
            asset._structure_detector.detect(data),
        )

        from quantforge.domain.entities.position import PositionSide

        correct_tp = entry_price + (
            tp_geo.tp_distance if asset.pos_mgr.position.side == PositionSide.LONG else -tp_geo.tp_distance
        )

        current_tp = asset.pos_mgr.position.take_profit
        if abs(correct_tp - current_tp) > 1e-6:
            asset.pos_mgr.update_take_profit(float(correct_tp))
            _sync_broker_sltp(asset)
            logger.info(
                "%s: TP reconciled from %.4f to %.4f (sl_dist=%.4f, arch=%s)",
                asset.name,
                current_tp,
                correct_tp,
                sl_dist,
                archetype,
            )
        asset._tp_reconciled = True

    def _track_running_excursion(self, asset) -> None:
        if not asset.pos_mgr.has_position():
            return
        entry = asset.pos_mgr.position.entry_price
        cp = asset.current_price
        if entry is None or cp is None:
            return
        raw_return = (cp - entry) / entry
        side = asset.pos_mgr.position.side
        from quantforge.domain.entities.position import PositionSide

        excursion = raw_return if side == PositionSide.LONG else -raw_return
        asset._running_mae = max(getattr(asset, "_running_mae", 0.0), -excursion)
        asset._running_mfe = max(getattr(asset, "_running_mfe", 0.0), excursion)

    def _check_scale_out_tiers(self, asset) -> None:
        if asset._scale_out_plan is None:
            return
        so_fills = asset._scale_out_engine.check_tiers(
            asset._scale_out_plan,
            asset.pos_mgr.position.side,
            asset.current_price,
            asset.current_value,
            asset.pos_mgr.position_size,
            asset.pos_mgr.exposure_multiplier,
        )
        for so in so_fills:
            if so.get("fraction", 0) > 0:
                asset.pos_mgr.partial_close(
                    so["fraction"],
                    so["fill_price"],
                    str(datetime.now(tz=ET).date()),
                    so["reason"],
                )
            breakeven = so.get("breakeven_price")
            if breakeven is not None:
                asset.pos_mgr.activate_breakeven_stop()
            if so.get("reason") == "trailing_activated":
                logger.info("%s: trailing activated by scale-out tier fill", asset.name)

    def _check_sltp_hit(self, asset) -> bool:
        hit = asset.pos_mgr.check_sl_tp(asset.current_price)
        if not hit:
            return False

        last_bar = str(datetime.now(tz=ET).date())

        if asset.pos_mgr.position is not None:
            entry = asset.pos_mgr.position.entry_price
            side = asset.pos_mgr.position.side
            ret = (hit[1] / entry - 1) if side == "long" else (entry / hit[1] - 1)
            logger.info(
                "%s: SL/TP HIT: %s at %.4f (Current: %.4f, Entry: %.4f, Ret: %.4f%%, Side: %s)",
                asset.name,
                hit[0].upper(),
                hit[1],
                asset.current_price,
                entry,
                ret * 100,
                side,
            )
        if asset.pos_mgr.position is not None:
            asset._record_stop_out(asset.pos_mgr.position.side, hit[1])
        if hasattr(asset, "_shadow_sltp") and asset._shadow_sltp is not None:
            asset._shadow_sltp.close_shadow(float(hit[1]), last_bar, hit[0])
            asset._shadow_sltp.set_live_outcome(hit[0], _compute_r(asset, float(hit[1])))
        asset._close_position(hit[1], last_bar, hit[0])
        if asset.current_value > asset.peak_value:
            asset.peak_value = asset.current_value
        return True

    def _apply_trailing_stop(self, asset) -> None:
        if not asset.config.get("dynamic_sltp", {}).get("enabled", False) or asset._entry_vol is None:
            return
        data = getattr(asset, "price_data", None)
        if data is None:
            data = getattr(asset, "_price_df", None)
        if data is None or asset.pos_mgr.position is None:
            return

        trailing = asset._sltp_engine.compute_trailing_stop(
            side=asset.pos_mgr.position.side,
            entry_price=asset.pos_mgr.position.entry_price,
            current_price=asset.current_price,
            initial_sl=asset._initial_sl or asset.pos_mgr.position.stop_loss,
            current_sl=asset.pos_mgr.position.stop_loss,
            take_profit=asset.pos_mgr.position.take_profit,
            df=data,
        )
        if trailing.trailing_sl is not None:
            asset.pos_mgr.update_stop_loss(float(trailing.trailing_sl))
            _sync_broker_sltp(asset)
            logger.info(
                "%s: trailing stop activated to %.4f (locked profit=%.2f%%)",
                asset.name,
                trailing.trailing_sl,
                (trailing.locked_profit or 0) * 100,
            )
            shadow_compare_sltp(
                asset.name,
                label_sl=asset._initial_sl or asset.pos_mgr.position.stop_loss,
                label_tp=asset.pos_mgr.position.take_profit,
                runtime_sl=trailing.trailing_sl,
                runtime_tp=asset.pos_mgr.position.take_profit,
                entry_price=asset.pos_mgr.position.entry_price,
                reason="trailing",
            )

        self._apply_post_entry_adjust(asset, data)

    def _apply_post_entry_adjust(self, asset, data) -> None:
        asset._bars_at_entry += 1
        adjust = asset._sltp_engine.post_entry_adjust(
            side=asset.pos_mgr.position.side,
            entry_price=asset.pos_mgr.position.entry_price,
            current_sl=asset.pos_mgr.position.stop_loss,
            current_tp=asset.pos_mgr.position.take_profit,
            df=data,
            vol=asset._entry_vol,
            bars_since_entry=asset._bars_at_entry,
        )
        if adjust.new_sl is not None:
            asset.pos_mgr.update_stop_loss(float(adjust.new_sl))
            _sync_broker_sltp(asset)
            logger.info(
                "%s: post-entry SL adjusted: %s (new=%.4f)",
                asset.name,
                adjust.reason,
                adjust.new_sl,
            )
            shadow_compare_sltp(
                asset.name,
                label_sl=asset._initial_sl or asset.pos_mgr.position.stop_loss,
                label_tp=asset.pos_mgr.position.take_profit,
                runtime_sl=adjust.new_sl,
                runtime_tp=asset.pos_mgr.position.take_profit,
                entry_price=asset.pos_mgr.position.entry_price,
                reason=adjust.reason or "post_entry_sl",
            )
        if adjust.new_tp is not None:
            asset.pos_mgr.update_take_profit(float(adjust.new_tp))
            _sync_broker_sltp(asset)
            logger.info(
                "%s: post-entry TP adjusted: %s (new=%.4f)",
                asset.name,
                adjust.reason,
                adjust.new_tp,
            )
            shadow_compare_sltp(
                asset.name,
                label_sl=asset.pos_mgr.position.stop_loss,
                label_tp=asset._initial_tp or asset.pos_mgr.position.take_profit,
                runtime_sl=asset.pos_mgr.position.stop_loss,
                runtime_tp=adjust.new_tp,
                entry_price=asset.pos_mgr.position.entry_price,
                reason=adjust.reason or "post_entry_tp",
            )

    def _check_time_stop(self, asset, max_hold) -> bool:
        if max_hold is None or asset.pos_mgr.position is None:
            return False
        entry_str = str(asset.pos_mgr.position.entry_date)
        try:
            entry_dt = pd.Timestamp(entry_str)
            if entry_dt.tz is None:
                entry_dt = entry_dt.tz_localize("US/Eastern")
            elapsed = (datetime.now(tz=ET) - entry_dt).days
            if elapsed >= max_hold:
                last_bar = str(datetime.now(tz=ET).date())
                logger.info("%s: TIME STOP after %d days (max=%d)", asset.name, elapsed, max_hold)
                if hasattr(asset, "_shadow_sltp") and asset._shadow_sltp is not None:
                    asset._shadow_sltp.close_shadow(asset.current_price, last_bar, "time_stop")
                asset._close_position(asset.current_price, last_bar, "time_stop")
                return True
        except (AttributeError, TypeError, ValueError):
            logger.debug("%s: could not parse entry date for time stop", asset.name)
        return False

    def _settle_daily_pnl(self, asset) -> None:
        if asset.signal_data is None or len(asset.signal_data) < 2:
            return

        close = asset.signal_data["close"]
        today_close = float(close.iloc[-1])
        last_bar = str(datetime.now(tz=ET).date())

        if asset.trades and asset.trades[-1]["date"] == last_bar:
            return
        if not asset._initial_settlement_done:
            asset._initial_settlement_done = True
            return

        sig = asset.signal_data["signal"].iloc[-2]
        direction = 1 if sig == 2 else (-1 if sig == 0 else 0)
        pos_size = (
            float(asset.signal_data["position_size"].iloc[-2]) if "position_size" in asset.signal_data.columns else 1.0
        )
        prev_close = float(close.iloc[-2])
        ret = (
            (today_close / prev_close - 1)
            if len(close) >= 2 and prev_close != 0 and not pd.isna(today_close) and not pd.isna(prev_close)
            else 0
        )
        if pd.isna(ret) or np.isinf(ret):
            ret = 0
        pnl = asset.pos_mgr.compute_daily_pnl(direction, ret, pos_size)
        _shadow_pnl = _w.compute_daily_pnl(
            asset.pos_mgr.current_value,
            direction,
            ret,
            asset.pos_mgr.position_size,
            pos_size,
        )
        shadow_compare_pnl(asset=asset.name, wrapper_pnl=_shadow_pnl, original_pnl=pnl)
        try:
            _pnl_decomp = diag.analyze_pnl_decomposition(
                asset.pos_mgr.current_value,
                direction,
                ret,
                asset.pos_mgr.position_size,
                pos_size,
                pnl,
            )
            _regime = diag.analyze_regime_context(close)
            _report = diag.build_shadow_report(
                asset=asset.name,
                timestamp=last_bar,
                signal_match=True,
                pnl_match=_pnl_decomp["match"],
                regime_context=_regime,
                pnl_decomposition=_pnl_decomp,
            )
            trace_diagnostic_report(_report)
            _shadow_store(asset.name, _report)
        except (TypeError, ValueError, KeyError):
            logger.debug("%s: shadow report failed", asset.name)
        asset.pos_mgr.apply_pnl(pnl)
        asset.current_value = asset.pos_mgr.current_value
        asset.peak_value = asset.pos_mgr.peak_value
        if direction != 0:
            asset.trades.append(
                {
                    "date": last_bar,
                    "direction": direction,
                    "return": float(ret),
                    "pnl": float(pnl),
                }
            )

    @property
    def mtm_value(self) -> float:
        asset = self.asset
        cv = asset.current_value if not pd.isna(asset.current_value) else asset.initial_capital
        if not asset.pos_mgr.has_position() or asset.current_price is None or pd.isna(asset.current_price):
            return cv

        pnl_pct = asset.pos_mgr.position_pnl(asset.current_price) / 100
        return cv * (1 + pnl_pct * asset.pos_mgr.position_size * asset.pos_mgr.exposure_multiplier)

    def set_capital_base(self, new_base: float) -> None:
        asset = self.asset
        old_base = asset.capital_base
        asset.capital_base = new_base
        delta = new_base - old_base
        asset.current_value = asset.current_value + delta
        asset.pos_mgr.current_value = asset.pos_mgr.current_value + delta


def _compute_r(asset, exit_price: float) -> float:
    """Compute the realized R-multiple from a trade."""
    if asset.pos_mgr is None or asset.pos_mgr.position is None:
        return 0.0
    entry = asset.pos_mgr.position.entry_price
    sl = asset.pos_mgr.position.stop_loss
    if entry <= 0 or sl == entry:
        return 0.0
    side = asset.pos_mgr.position.side
    ret = (exit_price / entry - 1) if side == "long" else (entry / exit_price - 1)
    risk_pct = abs(entry - sl) / entry
    return round(ret / risk_pct, 4) if risk_pct > 0 else 0.0
