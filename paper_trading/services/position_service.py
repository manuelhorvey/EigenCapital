import logging

import pandas as pd
import pytz

from paper_trading.entry.decision import PositionIntent, PositionSide

logger = logging.getLogger("quantforge.position_service")

ET = pytz.timezone("US/Eastern")


class PositionService:
    def __init__(self, asset):
        self.asset = asset

    def macro_blend_trade_returns(self, trade_ret: float) -> tuple[float, float]:
        asset = self.asset
        entry = asset._entry_signal_dir
        if entry == 0:
            return trade_ret, trade_ret
        macro_dir = asset._last_macro_dir
        blend_dir = asset._last_blend_dir
        macro_ret = trade_ret if macro_dir is None or macro_dir == entry else -trade_ret
        blend_ret = trade_ret if blend_dir is None or blend_dir == entry else -trade_ret
        return macro_ret, blend_ret

    def position_pnl(self, current_price):
        return self.asset.pos_mgr.position_pnl(current_price)

    def ensure_position_synced(self):
        asset = self.asset
        if asset.position is not None and not asset.pos_mgr.has_position():
            intent = PositionIntent(
                side=PositionSide(asset.position["side"]),
                entry_price=asset.position["entry"],
                entry_date=asset.position.get("entry_date", ""),
                stop_loss=asset.position["sl"],
                take_profit=asset.position["tp"],
                vol=asset.position.get("vol", 0.01),
            )
            asset.pos_mgr.open(intent)

    def save_trade_journal(self, trade):
        if self.asset.state_store is not None:
            self.asset.state_store.append_trade(trade)

    def close_position(self, exit_price, exit_date, reason):
        asset = self.asset
        fill_price = exit_price
        exit_slippage_bps = 0.0
        if asset.execution_bridge is not None and asset.pos_mgr.has_position():
            side = asset.pos_mgr.position.side
            broker_side = "sell" if side == "long" else "buy"
            notional = asset.current_value * asset.pos_mgr.position_size * asset.pos_mgr.exposure_multiplier
            qty = max(notional / exit_price, 1e-6)
            fill_price, exit_slippage_bps, _ = asset.execution_bridge.fill_price(
                asset.ticker, broker_side, qty, exit_price
            )

        trade = asset.pos_mgr.close(fill_price, exit_date, reason)
        if trade is None:
            return
        trade["asset"] = asset.name
        trade["conf_at_entry"] = asset.position.get("confidence") if asset.position else None
        trade["archetype_at_entry"] = asset._entry_archetype if hasattr(asset, "_entry_archetype") else "UNKNOWN"

        trade_id = asset._current_trade_id
        if trade_id:
            realized_r = trade.get("realized_r", 0.0)
            realized_return = trade.get("return", 0.0)
            realized_pnl = trade.get("pnl", 0.0)
            theoretical_r = realized_r
            asset._attribution.record_friction(
                trade_id=trade_id,
                entry_slippage_bps=getattr(asset, "_last_entry_slippage", 0.0),
                exit_slippage_bps=exit_slippage_bps,
            )
            record = asset._attribution.finalize(
                trade_id=trade_id,
                asset=asset.name,
                entry_date=str(trade.get("entry_date", "")),
                exit_date=str(trade.get("exit_date", "")),
                side=str(trade.get("side", "long")),
                exit_price=fill_price,
                exit_reason=reason,
                realized_r=realized_r,
                realized_return=realized_return,
                realized_pnl=realized_pnl,
                theoretical_r=theoretical_r,
                policy_hash=getattr(asset, "_last_policy_hash", ""),
                archetype_version="1.0",
                exit_archetype=getattr(asset, "_exit_archetype", ""),
            )
            if record is not None:
                asset._attribution_buffer.append(record)
                asset._attribution_svc.flush_attribution()
                if asset.state_store is not None:
                    try:
                        asset.state_store.append_attribution(record.to_dict())
                    except Exception:
                        logger.exception("attribution: failed to persist to centralized store")
                exit_info = record.exit_info
                if exit_info is not None:
                    trade["mae"] = exit_info.mae
                    trade["mfe"] = exit_info.mfe
                    trade["mae_per_bar"] = exit_info.mae_per_bar
                    trade["mfe_per_bar"] = exit_info.mfe_per_bar
                    trade["realized_r"] = exit_info.realized_r
                    trade["bars"] = exit_info.bars_held
                    trade["exit_archetype"] = exit_info.exit_archetype
                exec_attr = record.execution
                trade["entry_slippage_bps"] = exec_attr.entry_slippage_bps if exec_attr else 0.0
                friction = record.friction
                trade["exit_slippage_bps"] = friction.exit_slippage_bps
                trade["fill_qty_ratio"] = friction.fill_qty_ratio
                trade["gap_fill"] = friction.gap_fill
                trade["partial_fill"] = friction.partial_fill
                trade["latency_bars"] = friction.latency_bars
                trade["pred_confidence"] = record.prediction.confidence
                trade["pred_archetype"] = record.prediction.archetype_at_entry
                trade["pred_regime"] = record.prediction.regime_at_entry
            trade["attribution_trade_id"] = trade_id

            if asset.state_store is not None:
                try:
                    shadow = getattr(asset, "_shadow_sltp", None)
                    if shadow is not None:
                        completed = shadow.flush_completed(asset_name=asset.name)
                        for st in completed:
                            asset.state_store.append_shadow_trade(st.__dict__)
                except Exception:
                    logger.exception("shadow: failed to persist completed shadow trades")

        try:
            macro_head = getattr(asset.model, "macro_head", None) if asset.model else None
            if macro_head is not None and macro_head.online_weight:
                trade_ret = float(trade.get("return", 0.0))
                macro_ret, blend_ret = self.macro_blend_trade_returns(trade_ret)
                macro_head.update_weight(macro_ret, blend_ret)
        except (AttributeError, ValueError, TypeError):
            pass

        # ── Real broker close (MT5) ──
        mt5_ticket = asset.position.get("mt5_ticket") if asset.position else None
        if mt5_ticket is not None and asset.execution_bridge is not None and getattr(asset.execution_bridge, "_is_real_broker", False):
            try:
                asset.execution_bridge.broker.close_position(asset.ticker, str(mt5_ticket))
            except Exception as e:
                logger.warning("%s: MT5 close failed for ticket=%s: %s", asset.name, mt5_ticket, e)

        asset.position = None
        if reason == "signal_flip":
            asset._last_signal_flip_cycle = asset._cycle_counter
        asset.current_value = asset.pos_mgr.current_value
        asset.trade_log = list(asset.pos_mgr.trade_log)
        self.save_trade_journal(trade)
        if asset.state_store is not None:
            asset.state_store.write_analytics_snapshot()
        from paper_trading.governance.risk import record_trade_outcome as _record_exit_outcome

        _record_exit_outcome(asset.name, reason)

    def record_stop_out(self, side: str, exit_price: float) -> None:
        asset = self.asset

        # Compute SL price for churn filter check WITHOUT mutating state yet
        sl_price = None
        if asset.pos_mgr.position is not None:
            sl_price = asset.pos_mgr.position.stop_loss

        # Churn filter: if price barely moved beyond SL, skip recording entirely.
        # Prevents noise-driven stop-outs from triggering cooldown/locks.
        if asset._regime_adjusted_entry and sl_price is not None and asset._entry_price is not None:
            sl_distance = abs(sl_price - asset._entry_price)
            price_beyond_sl = abs(exit_price - sl_price)
            if sl_distance > 0 and (price_beyond_sl / sl_distance) < asset._churn_ratio_threshold:
                return

        # Atomically persist all stop-out metadata (only after churn filter passes)
        asset._last_stop_out_price = sl_price
        asset._last_stop_out_side = side
        asset._last_stop_out_date = pd.Timestamp.now(tz="UTC").normalize()
        asset._cooldown_score = 1.0
        asset._last_cooldown_update = pd.Timestamp.now(tz="UTC")

    def cooldown_penalty(self, side: str) -> float:
        asset = self.asset
        if asset._last_stop_out_side != side:
            return 0.0
        if not hasattr(asset, "_cooldown_score") or asset._cooldown_score <= 0:
            return 0.0

        now = pd.Timestamp.now(tz="UTC")
        elapsed_hours = (now - asset._last_cooldown_update).total_seconds() / 3600

        half_life = asset.config.get("cooldown_half_life_hours", 4.0)
        decay = 0.5 ** (elapsed_hours / half_life)
        asset._cooldown_score *= decay
        asset._last_cooldown_update = now

        if asset._cooldown_score < 0.05:
            asset._cooldown_score = 0.0
            asset._last_stop_out_side = None

        return asset._cooldown_score
