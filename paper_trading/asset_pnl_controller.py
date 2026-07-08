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
from paper_trading.position.adaptive_exit import AdaptiveExitEngine
from paper_trading.shadow.memory import store_event as _shadow_store

logger = logging.getLogger("eigencapital.pnl_controller")

ET = pytz.timezone("US/Eastern")

# Cap per-asset trade history to prevent unbounded memory growth.
_MAX_TRADES = 10_000


def _sync_broker_sltp(asset, trade_id: str | None = None) -> bool:
    """Push current SL/TP to the real broker (MT5) after in-memory adjustment.

    If trade_id is provided, sync that specific position. Otherwise syncs all positions.
    Returns True if all syncs succeeded.
    """
    bridge = getattr(asset, "execution_bridge", None)
    if bridge is None or not getattr(bridge, "_is_real_broker", False):
        return True

    positions_to_sync: list[tuple[dict | None, str | None]] = [
        (asset.position, getattr(asset, "_current_trade_id", None)),
    ]
    if trade_id is None:
        for i, tid in enumerate(asset.reentry_trade_ids):
            positions_to_sync.append((asset.reentry_positions[i], tid))
    else:
        if trade_id in asset.reentry_trade_ids:
            idx = asset.reentry_trade_ids.index(trade_id)
            positions_to_sync = [(asset.reentry_positions[idx], trade_id)]
        elif trade_id == getattr(asset, "_current_trade_id", None):
            positions_to_sync = [(asset.position, trade_id)]
        else:
            positions_to_sync = []

    all_ok = True
    for pos_dict, _ in positions_to_sync:
        if pos_dict is None:
            continue
        mt5_ticket = pos_dict.get("mt5_ticket")
        if mt5_ticket is None:
            continue
        # All stacked positions (primary + reentries) share the trailed SL/TP
        if asset.pos_mgr.has_position():
            sl = asset.pos_mgr.position.stop_loss
            tp = asset.pos_mgr.position.take_profit
            pos_dict["sl"] = sl   # keep dict in sync for dashboard consistency
            pos_dict["tp"] = tp
        else:
            sl = pos_dict.get("sl")
            tp = pos_dict.get("tp")
        if pd.isna(sl) or pd.isna(tp) or sl is None or tp is None:
            logger.error("%s: cannot sync NaN SL=%.4f or TP=%.4f to broker", asset.name, sl, tp)
            all_ok = False
            continue
        try:
            ok = bridge.broker.modify_position(
                asset.ticker,
                str(mt5_ticket),
                sl=float(sl),
                tp=float(tp),
            )
            if not ok:
                logger.error(
                    "%s: MT5 modify_position returned failure for ticket=%s sl=%.5f tp=%.5f",
                    asset.name,
                    mt5_ticket,
                    sl,
                    tp,
                )
                all_ok = False
            else:
                logger.info(
                    "%s: MT5 SL/TP synced for ticket=%s sl=%.5f tp=%.5f",
                    asset.name,
                    mt5_ticket,
                    sl,
                    tp,
                )
        except Exception as e:
            logger.error(
                "%s: MT5 modify_position raised exception for ticket=%s: %s",
                asset.name,
                mt5_ticket,
                e,
            )
            all_ok = False
    return all_ok


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
        has_any_position = asset.pos_mgr.has_position() or len(asset.reentry_positions) > 0
        if has_any_position and asset.current_price is not None and self._check_intraday_sltp(asset, max_hold):
            return

        self._settle_daily_pnl(asset)

    def _check_intraday_sltp(self, asset, max_hold) -> bool:
        self._reconcile_position_tp(asset)
        self._tick_shadow_sltp(asset)
        self._check_scale_out_tiers(asset)
        if self._check_sltp_hit(asset):
            return True

        # Apply EXACTLY ONE trailing exit system per cycle to prevent SL ping-pong.
        # Only applies to primary position. Re-entry positions use fixed SL/TP.
        #
        # When adaptive_exit is enabled, it handles the full lifecycle:
        #   breakeven lock (0.5R) → scale-out → retracement trail → time decay.
        # The old dynamic_sltp trailing (vol-spike tightening) is skipped to avoid
        # conflicting SL updates that ping-pong between two independent systems.
        #
        # When adaptive_exit is disabled, the legacy dynamic_sltp trailing + post-entry
        # adjustment runs (vol spike tightening, TP nudging).
        ae_cfg = asset.config.get("adaptive_exit", {})
        if ae_cfg.get("enabled", False):
            self._apply_adaptive_exit(asset)
        else:
            self._apply_trailing_stop(asset)

        # Check re-entry positions for SL/TP hits (fixed barriers only)
        for i in range(len(asset.reentry_positions) - 1, -1, -1):
            pos_dict = asset.reentry_positions[i]
            tid = asset.reentry_trade_ids[i]
            if self._check_position_sltp_hit(asset, pos_dict, tid):
                return True

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
            entry_state if entry_state else (asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW")
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

        from eigencapital.domain.entities.position import PositionSide

        correct_tp = entry_price + (
            tp_geo.tp_distance if asset.pos_mgr.position.side == PositionSide.LONG else -tp_geo.tp_distance
        )

        current_tp = asset.pos_mgr.position.take_profit
        if not pd.isna(correct_tp) and abs(correct_tp - current_tp) > 1e-6:
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
        if entry is None or cp is None or not entry or not cp:
            return
        if pd.isna(entry) or pd.isna(cp):
            return
        raw_return = (cp - entry) / entry
        side = asset.pos_mgr.position.side
        from eigencapital.domain.entities.position import PositionSide

        excursion = raw_return if side == PositionSide.LONG else -raw_return
        if excursion is None or pd.isna(excursion):
            return
        mae = getattr(asset, "_running_mae", 0.0)
        mfe = getattr(asset, "_running_mfe", 0.0)
        if mae is None or mfe is None:
            return
        asset._running_mae = max(mae, -excursion)
        asset._running_mfe = max(mfe, excursion)

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

    def _check_position_sltp_hit(self, asset, pos_dict: dict, trade_id: str) -> bool:
        """Check SL/TP for a single position dict (primary or re-entry)."""
        current_price = asset.current_price
        if current_price is None or pd.isna(current_price) or current_price <= 0:
            return False
        side = pos_dict.get("side")
        sl = pos_dict.get("sl")
        tp = pos_dict.get("tp")
        if sl is None or tp is None or pd.isna(sl) or pd.isna(tp):
            return False

        if side == "long":
            if current_price <= sl:
                hit_reason, hit_price = "sl", sl
            elif current_price >= tp:
                hit_reason, hit_price = "tp", tp
            else:
                return False
        elif side == "short":
            if current_price >= sl:
                hit_reason, hit_price = "sl", sl
            elif current_price <= tp:
                hit_reason, hit_price = "tp", tp
            else:
                return False
        else:
            return False

        last_bar = str(datetime.now(tz=ET).date())
        entry = pos_dict.get("entry", 0)
        ret = (hit_price / entry - 1) if side == "long" else (entry / hit_price - 1)
        logger.info(
            "%s: SL/TP HIT: %s at %.4f (Current: %.4f, Entry: %.4f, Ret: %.4f%%, Side: %s, Trade: %s)",
            asset.name,
            hit_reason.upper(),
            hit_price,
            current_price,
            entry,
            ret * 100,
            side,
            trade_id,
        )
        _exit_reason = "TP" if hit_reason == "tp" else "SL"
        asset._close_position(hit_price, last_bar, _exit_reason, trade_id=trade_id)
        if asset.current_value > asset.peak_value:
            asset.peak_value = asset.current_value
        return True

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
        _exit_reason = "BREAKEVEN" if hit[0] == "breakeven" else "TP" if hit[0] == "tp" else "SL"
        asset._close_position(hit[1], last_bar, _exit_reason)
        if asset.current_value > asset.peak_value:
            asset.peak_value = asset.current_value
        return True

    @staticmethod
    def _load_sltp_data(asset):
        """Load price data for SL/TP operations.

        Shared helper used by _apply_trailing_stop and _apply_post_entry_adjust
        to avoid duplicating the guard checks and data-fetching logic.
        Returns (df, False) on failure, (df, True) on success.
        """
        if not asset.config.get("dynamic_sltp", {}).get("enabled", False) or asset._entry_vol is None:
            return None, False
        data = getattr(asset, "price_data", None)
        if data is None:
            data = getattr(asset, "_price_df", None)
        if data is None or asset.pos_mgr.position is None:
            return None, False
        return data, True

    def _apply_trailing_stop(self, asset) -> None:
        data, ok = self._load_sltp_data(asset)
        if not ok:
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
        if trailing.trailing_sl is not None and not pd.isna(trailing.trailing_sl):
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

    def _apply_adaptive_exit(self, asset) -> None:
        cfg = asset.config.get("adaptive_exit", {})
        if not cfg.get("enabled", False):
            return
        if asset._entry_vol is None or not asset.pos_mgr.has_position():
            return

        if not hasattr(asset, "_adaptive_exit_engine"):
            asset._adaptive_exit_engine = AdaptiveExitEngine()
        ae = asset._adaptive_exit_engine

        if getattr(asset, "_adaptive_exit_reset", True):
            ae.reset()
            asset._adaptive_exit_reset = False

        result = ae.compute(
            side=asset.pos_mgr.position.side.value,
            entry_price=asset.pos_mgr.position.entry_price,
            current_price=asset.current_price,
            current_sl=asset.pos_mgr.position.stop_loss,
            vol_at_entry=asset._entry_vol,
            bars_since_entry=getattr(asset, "_bars_at_entry", 0),
            config=cfg,
        )

        # Scale-out: close a fraction of the position at target R-multiple
        if result.scale_out_fraction is not None and result.scale_out_price is not None:
            last_bar = str(datetime.now(tz=ET).date())
            asset.pos_mgr.partial_close(
                result.scale_out_fraction,
                result.scale_out_price,
                last_bar,
                f"r_scale_out_{cfg.get('scale_out_r', '?')}R",
            )
            logger.info(
                "%s: adaptive exit scale-out — closed %.0f%% at %.4f (%.1fR)",
                asset.name,
                result.scale_out_fraction * 100,
                result.scale_out_price,
                cfg.get("scale_out_r", 0),
            )

        if result.new_sl is not None and not pd.isna(result.new_sl):
            asset.pos_mgr.update_stop_loss(float(result.new_sl))
            _sync_broker_sltp(asset)
            logger.info(
                "%s: adaptive exit %s — SL moved to %.4f",
                asset.name,
                result.action,
                result.new_sl,
            )

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
        if adjust.new_sl is not None and not pd.isna(adjust.new_sl):
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
        if adjust.new_tp is not None and not pd.isna(adjust.new_tp):
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
                asset._close_position(asset.current_price, last_bar, "EXPIRY")
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
            if len(asset.trades) >= _MAX_TRADES:
                asset.trades.pop(0)
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
        cp = asset.current_price
        if cp is None or pd.isna(cp):
            return cv

        # Sum PnL from primary position
        total_pnl_pct = 0.0
        if asset.pos_mgr.has_position():
            pnl_pct = asset.pos_mgr.position_pnl(cp) / 100
            total_pnl_pct = pnl_pct * asset.pos_mgr.position_size * asset.pos_mgr.exposure_multiplier

        # Sum PnL from re-entry positions (approximate using fixed size = position_size)
        for pos_dict in asset.reentry_positions:
            entry = pos_dict.get("entry", 0)
            if entry <= 0:
                continue
            side = pos_dict.get("side", "long")
            raw_ret = (cp / entry - 1) if side == "long" else (entry / cp - 1)
            total_pnl_pct += raw_ret * asset.pos_mgr.position_size * asset.pos_mgr.exposure_multiplier

        return cv * (1 + total_pnl_pct)

    def set_capital_base(self, new_base: float) -> None:
        asset = self.asset
        old_base = asset.capital_base
        asset.capital_base = new_base
        delta = new_base - old_base
        asset.initial_capital = asset.initial_capital + delta
        asset.current_value = asset.current_value + delta
        asset.peak_value = asset.peak_value + delta
        asset.pos_mgr.initial_capital = asset.pos_mgr.initial_capital + delta
        asset.pos_mgr.current_value = asset.pos_mgr.current_value + delta
        asset.pos_mgr.peak_value = asset.pos_mgr.peak_value + delta


def _compute_r(asset, exit_price: float) -> float:
    """Compute the realized R-multiple from a trade.

    Uses ``effective_sl`` (which reflects trailing/adaptive stop adjustments)
    rather than ``stop_loss`` (the original entry SL) to correctly measure
    risk for R-multiple calculation.  When trailing stops tighten the SL,
    the original ``stop_loss`` would understate risk and inflate apparent
    risk-adjusted returns.
    """
    if asset.pos_mgr is None or asset.pos_mgr.position is None:
        return 0.0
    entry = asset.pos_mgr.position.entry_price
    sl = asset.pos_mgr.position.effective_sl
    if entry <= 0 or sl == entry or sl is None or sl <= 0:
        return 0.0
    side = asset.pos_mgr.position.side
    ret = (exit_price / entry - 1) if side == "long" else (entry / exit_price - 1)
    risk_pct = abs(entry - sl) / entry
    return round(ret / risk_pct, 4) if risk_pct > 0 else 0.0
