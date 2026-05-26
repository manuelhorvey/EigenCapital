import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from paper_trading import diagnostics as diag
from paper_trading import wrappers as _w
from paper_trading.shadow_memory import store_event as _shadow_store
from paper_trading.tracer import (
    shadow_compare_pnl,
    shadow_compare_sltp,
    trace_diagnostic_report,
)

logger = logging.getLogger("quantforge.pnl_controller")

ET = pytz.timezone("US/Eastern")


class AssetPnlController:
    def __init__(self, asset):
        self.asset = asset

    def update_pnl(self):
        asset = self.asset
        asset._ensure_position_synced()

        # 1. Intraday SL/TP Check - ALWAYS run this on every refresh using real-time price
        max_hold = asset.config.get("max_holding_days")
        if asset.pos_mgr.has_position() and asset.current_price is not None:
            # ── Scale-out tier check ─────────────────────────────
            if asset._scale_out_plan is not None:
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

            hit = asset.pos_mgr.check_sl_tp(asset.current_price)
            if hit:
                last_bar = str(datetime.now(tz=ET).date())

                logger.info(
                    "%s: SL/TP HIT: %s at %s (Current: %s)", asset.name, hit[0].upper(), hit[1], asset.current_price
                )
                if asset.pos_mgr.position is not None:
                    asset._record_stop_out(asset.pos_mgr.position.side, hit[1])
                asset._close_position(hit[1], last_bar, hit[0])
                if asset.current_value > asset.peak_value:
                    asset.peak_value = asset.current_value
                return

            # ── Trailing stop check ──────────────────────────────
            if asset.config.get("dynamic_sltp", {}).get("enabled", False) and asset._entry_vol is not None:
                data = getattr(asset, "price_data", None)
                if data is None:
                    data = getattr(asset, "_price_df", None)
                if data is not None and asset.pos_mgr.position is not None:
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

                    # ── Post-entry adjustment ────────────────────────
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

            # Time stop check — force close if held beyond max_holding_days
            if max_hold is not None and asset.pos_mgr.position is not None:
                entry_str = str(asset.pos_mgr.position.entry_date)
                try:
                    entry_dt = pd.Timestamp(entry_str)
                    if entry_dt.tz is None:
                        entry_dt = entry_dt.tz_localize("US/Eastern")
                    elapsed = (datetime.now(tz=ET) - entry_dt).days
                    if elapsed >= max_hold:
                        last_bar = str(datetime.now(tz=ET).date())
                        logger.info("%s: TIME STOP after %d days (max=%d)", asset.name, elapsed, max_hold)
                        asset._close_position(asset.current_price, last_bar, "time_stop")
                        return
                except Exception:
                    pass

        # 2. Daily P&L Settlement - Only run if signal_data is available (historical context)
        if asset.signal_data is None or len(asset.signal_data) < 2:
            return

        close = asset.signal_data["close"]
        today_close = float(close.iloc[-1])
        last_bar = str(datetime.now(tz=ET).date())

        if asset.trades and asset.trades[-1]["date"] == last_bar:
            return
        # Skip settlement on first cycle — no prior live signal to settle.
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
        except Exception:
            pass
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
