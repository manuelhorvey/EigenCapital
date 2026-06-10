import logging

from paper_trading.entry.decision import PositionIntent, PositionSide

logger = logging.getLogger("quantforge.position_service")


class PositionService:
    def __init__(
        self,
        *,
        name,
        ticker,
        config,
        pos_mgr,
        state_store,
        attribution,
        attribution_svc,
        execution_bridge,
        model,
        shadow_sltp,
    ):
        self.name = name
        self.ticker = ticker
        self.config = config
        self.pos_mgr = pos_mgr
        self.state_store = state_store
        self.attribution = attribution
        self.attribution_svc = attribution_svc
        self.execution_bridge = execution_bridge
        self.model = model
        self._shadow_sltp = shadow_sltp

    def macro_blend_trade_returns(
        self,
        trade_ret: float,
        *,
        entry_signal_dir: int,
        last_macro_dir,
        last_blend_dir,
    ) -> tuple[float, float]:
        entry = entry_signal_dir
        if entry == 0:
            return trade_ret, trade_ret
        macro_dir = last_macro_dir
        blend_dir = last_blend_dir
        macro_ret = trade_ret if macro_dir is None or macro_dir == entry else -trade_ret
        blend_ret = trade_ret if blend_dir is None or blend_dir == entry else -trade_ret
        return macro_ret, blend_ret

    def ensure_position_synced(self, *, position, pos_mgr):
        if position is not None and not pos_mgr.has_position():
            intent = PositionIntent(
                side=PositionSide(position["side"]),
                entry_price=position["entry"],
                entry_date=position.get("entry_date", ""),
                stop_loss=position["sl"],
                take_profit=position["tp"],
                vol=position.get("vol", 0.01),
            )
            pos_mgr.open(intent)

    def close_position(
        self,
        exit_price,
        exit_date,
        reason,
        *,
        position,
        current_value,
        entry_archetype,
        current_trade_id,
        attribution_buffer,
        cycle_counter,
        last_entry_slippage,
        last_policy_hash,
        exit_archetype,
        attribution_export_dir,
        experiment_id,
        entry_signal_dir,
        last_macro_dir,
        last_blend_dir,
    ):
        fill_price = exit_price
        exit_slippage_bps = 0.0
        if self.execution_bridge is not None and self.pos_mgr.has_position():
            side = self.pos_mgr.position.side
            broker_side = "sell" if side == "long" else "buy"
            notional = current_value * self.pos_mgr.position_size * self.pos_mgr.exposure_multiplier
            qty = max(notional / exit_price, 1e-6)
            fill_price, exit_slippage_bps, _ = self.execution_bridge.fill_price(
                self.ticker, broker_side, qty, exit_price
            )

        trade = self.pos_mgr.close(fill_price, exit_date, reason)
        if trade is None:
            return {}
        trade["asset"] = self.name
        trade["conf_at_entry"] = position.get("confidence") if position else None
        trade["archetype_at_entry"] = entry_archetype if entry_archetype else "UNKNOWN"

        trade_id = current_trade_id
        if trade_id:
            realized_r = trade.get("realized_r", 0.0)
            realized_return = trade.get("return", 0.0)
            realized_pnl = trade.get("pnl", 0.0)
            theoretical_r = realized_r
            self.attribution.record_friction(
                trade_id=trade_id,
                entry_slippage_bps=last_entry_slippage if last_entry_slippage else 0.0,
                exit_slippage_bps=exit_slippage_bps,
            )
            record = self.attribution.finalize(
                trade_id=trade_id,
                asset=self.name,
                entry_date=str(trade.get("entry_date", "")),
                exit_date=str(trade.get("exit_date", "")),
                side=str(trade.get("side", "long")),
                exit_price=fill_price,
                exit_reason=reason,
                realized_r=realized_r,
                realized_return=realized_return,
                realized_pnl=realized_pnl,
                theoretical_r=theoretical_r,
                policy_hash=last_policy_hash if last_policy_hash else "",
                archetype_version="1.0",
                exit_archetype=exit_archetype if exit_archetype else "",
            )
            if record is not None:
                attribution_buffer.append(record)
                self.attribution_svc.flush_attribution(
                    name=self.name,
                    attribution_buffer=attribution_buffer,
                    attribution_export_dir=attribution_export_dir,
                    experiment_id=experiment_id,
                )
                if self.state_store is not None:
                    try:
                        self.state_store.append_attribution(record.to_dict())
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

            if self.state_store is not None:
                try:
                    if self._shadow_sltp is not None:
                        completed = self._shadow_sltp.flush_completed(asset_name=self.name)
                        for st in completed:
                            self.state_store.append_shadow_trade(st.__dict__)
                except Exception:
                    logger.exception("shadow: failed to persist completed shadow trades")

        try:
            macro_head = getattr(self.model, "macro_head", None) if self.model else None
            if macro_head is not None and macro_head.online_weight:
                trade_ret = float(trade.get("return", 0.0))
                macro_ret, blend_ret = self.macro_blend_trade_returns(
                    trade_ret,
                    entry_signal_dir=entry_signal_dir,
                    last_macro_dir=last_macro_dir,
                    last_blend_dir=last_blend_dir,
                )
                macro_head.update_weight(macro_ret, blend_ret)
        except (AttributeError, ValueError, TypeError):
            pass

        # ── Real broker close (MT5) ──
        mt5_ticket = position.get("mt5_ticket") if position else None
        is_real = getattr(self.execution_bridge, "_is_real_broker", False)
        if mt5_ticket is not None and self.execution_bridge is not None and is_real:
            try:
                self.execution_bridge.broker.close_position(self.ticker, str(mt5_ticket))
            except Exception as e:
                logger.warning("%s: MT5 close failed for ticket=%s: %s", self.name, mt5_ticket, e)

        new_trade_log = list(self.pos_mgr.trade_log)
        mutations = {
            "position": None,
            "trade": trade,
            "current_value": self.pos_mgr.current_value,
            "trade_log": new_trade_log,
        }
        if reason == "signal_flip":
            mutations["last_signal_flip_cycle"] = cycle_counter

        if self.state_store is not None:
            self.state_store.append_trade(trade)
            self.state_store.write_analytics_snapshot()
        from paper_trading.governance.risk import record_trade_outcome as _record_exit_outcome

        _record_exit_outcome(self.name, reason)
        return mutations

    def record_stop_out(
        self, side: str, exit_price: float, *, pos_mgr, regime_adjusted_entry, entry_price,
        churn_ratio_threshold, cycle_counter,
    ):
        sl_price = None
        if pos_mgr.position is not None:
            sl_price = pos_mgr.position.stop_loss

        # Churn filter
        if regime_adjusted_entry and sl_price is not None and entry_price is not None:
            sl_distance = abs(sl_price - entry_price)
            price_beyond_sl = abs(exit_price - sl_price)
            if sl_distance > 0 and (price_beyond_sl / sl_distance) < churn_ratio_threshold:
                return {}

        return {
            "_last_stop_out_price": sl_price,
            "_last_stop_out_side": side,
            "_last_stop_out_cycle": cycle_counter,
            "_cooldown_score": 1.0,
            "_last_cooldown_update_cycle": cycle_counter,
        }

    def cooldown_penalty(self, side: str, *, last_stop_out_side, cooldown_score,
                          last_cooldown_update_cycle, config, cycle_counter) -> float:
        if last_stop_out_side != side:
            return 0.0
        if not cooldown_score or cooldown_score <= 0:
            return 0.0

        elapsed_cycles = cycle_counter - last_cooldown_update_cycle
        half_life = config.get("cooldown_half_life_cycles", 48)
        decay = 0.5 ** (elapsed_cycles / max(half_life, 1))
        new_score = cooldown_score * decay
        return new_score
