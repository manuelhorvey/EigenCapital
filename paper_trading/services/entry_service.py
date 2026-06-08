import logging

import numpy as np
import pandas as pd
import pytz

from paper_trading.entry.decision import EntryAction, PositionIntent, PositionSide
from paper_trading.entry.deferred_entry import DeferredEntryStatus
from paper_trading.governance.multipliers import compute_effective_multipliers

logger = logging.getLogger("quantforge.entry_service")

ET = pytz.timezone("US/Eastern")


class EntryService:
    """Entry service methods. Stateless — methods take everything they need as parameters."""

    def effective_capital(self, *, initial_capital, capital_base, current_value) -> float:
        if initial_capital <= 0:
            return capital_base
        growth = current_value / initial_capital
        return capital_base * growth

    def tb_vol(self, close_series):
        returns = np.log(close_series / close_series.shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def composite_size_scalar(self, extra_scalar: float = 1.0, *, validity_state, sl_mult, tp_mult,
                                regime_geometry, governance, pos_mgr, meta_size_multiplier) -> float:
        _, _, effective_size = compute_effective_multipliers(
            base_sl=sl_mult,
            base_tp=tp_mult,
            validity_state=validity_state,
            regime_geometry=regime_geometry,
            narrative_sl_mult=governance._narrative_sl_mult,
            liquidity_sl_mult=governance._liquidity_sl_mult,
            narrative_size_scalar=governance._narrative_size_scalar,
            liquidity_size_scalar=governance._liquidity_size_scalar,
        )
        return (
            pos_mgr.position_size
            * pos_mgr.exposure_multiplier
            * extra_scalar
            * meta_size_multiplier
            * effective_size
        )

    def compute_notional(self, effective_capital_val: float, size_scalar_val: float) -> float:
        return effective_capital_val * size_scalar_val

    def sizing_config(self, close: pd.Series, position_size_scalar: float = 1.0, *,
                      execution_bridge, ticker, config, effective_capital_val, size_scalar_val) -> dict:
        cfg = dict(config)
        if execution_bridge is None:
            return cfg
        price = float(close.iloc[-1]) if len(close) else 0.0
        if price <= 0:
            return cfg
        notional = self.compute_notional(effective_capital_val, size_scalar_val)
        cfg["impact_bps"] = execution_bridge.estimate_impact_bps(ticker, notional)
        return cfg

    def can_enter(self, side, price, *, last_stop_out_date, last_stop_out_side, config,
                  cooldown_penalty_func, pending_entries, cycle_counter, last_signal_flip_cycle,
                  min_flip_interval_bars, context=None) -> tuple[bool, str]:
        if last_stop_out_date is not None:
            cross_cooldown_hours = config.get("stopout_cross_side_cooldown_hours", 1.0)
            now = pd.Timestamp.now(tz="UTC")
            elapsed_hours = (now - last_stop_out_date).total_seconds() / 3600
            if elapsed_hours < cross_cooldown_hours:
                remaining = round(cross_cooldown_hours - elapsed_hours, 2)
                return False, f"cross_side_stopout_cooldown_{remaining}h"

        if last_stop_out_date is not None and last_stop_out_side == side:
            now = pd.Timestamp.now(tz="UTC")
            if last_stop_out_date == now.normalize():
                return False, "same_day_stopout_lock"

        penalty = cooldown_penalty_func(side)
        if penalty > 0:
            return False, f"cooldown_active_{penalty:.2f}"

        if side in pending_entries:
            return False, "pending_entry_exists"

        cycles_since_flip = cycle_counter - last_signal_flip_cycle
        if cycles_since_flip < min_flip_interval_bars:
            return False, f"signal_flip_cooldown_{cycles_since_flip}"

        return True, "ok"

    def open_position(self, side, entry_price, entry_date, asset, df=None, tp_geo=None):
        data = df if df is not None else asset.price_data
        vol = self.tb_vol(data["close"])
        logger.debug(
            "%s tb_vol: vol=%.6f entry=%.4f close_last=%.4f close_min=%.4f close_max=%.4f close_len=%d",
            asset.name,
            vol,
            entry_price,
            data["close"].iloc[-1] if len(data["close"]) else 0,
            data["close"].min() if len(data["close"]) else 0,
            data["close"].max() if len(data["close"]) else 0,
            len(data["close"]),
        )
        if pd.isna(vol) or pd.isna(entry_price) or entry_price == 0:
            logger.warning("%s: skipped entry — invalid price=%s or vol=%s", asset.name, entry_price, vol)
            return

        state = asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW"
        sl_mult, tp_mult, _ = compute_effective_multipliers(
            base_sl=asset.sl_mult,
            base_tp=asset.tp_mult,
            validity_state=state,
            regime_geometry=asset.regime_geometry,
            narrative_sl_mult=asset.governance._narrative_sl_mult,
            liquidity_sl_mult=asset.governance._liquidity_sl_mult,
            narrative_size_scalar=asset.governance._narrative_size_scalar,
            liquidity_size_scalar=asset.governance._liquidity_size_scalar,
        )

        fill_price = entry_price
        entry_slippage_bps = 0.0
        mt5_ticket = None
        if asset.execution_bridge is not None:
            effective_cap = self.effective_capital(
                initial_capital=asset.initial_capital,
                capital_base=asset.capital_base,
                current_value=asset.current_value,
            )
            size_scalar = self.composite_size_scalar(
                1.0,
                validity_state=state,
                sl_mult=asset.sl_mult,
                tp_mult=asset.tp_mult,
                regime_geometry=asset.regime_geometry,
                governance=asset.governance,
                pos_mgr=asset.pos_mgr,
                meta_size_multiplier=asset._meta_size_multiplier(),
            )
            notional = self.compute_notional(effective_cap, size_scalar)
            side_str = side.value if hasattr(side, "value") else side
            broker_side = "buy" if side_str == "long" else "sell"
            qty = max(notional / entry_price, 1e-6)
            if hasattr(asset.execution_bridge, "_is_real_broker") and asset.execution_bridge._is_real_broker:
                broker = asset.execution_bridge.broker
                existing_positions = broker.get_positions()
                mt5_symbol = getattr(broker, "_symbol_map", {}).get(asset.ticker, asset.ticker)
                has_position = any(p.asset == mt5_symbol for p in existing_positions)
                if has_position:
                    logger.warning(
                        "%s: skipping MT5 order — %s position already open in broker",
                        asset.name,
                        side.value,
                    )
                else:
                    if side == PositionSide.LONG:
                        mt5_sl = entry_price * (1 - vol * sl_mult)
                        mt5_tp = entry_price * (1 + vol * tp_mult)
                    else:
                        mt5_sl = entry_price * (1 + vol * sl_mult)
                        mt5_tp = entry_price * (1 - vol * tp_mult)
                    fill_price, order_id = asset.execution_bridge.submit_market_order(
                        asset.ticker,
                        broker_side,
                        qty,
                        entry_price,
                        sl=mt5_sl,
                        tp=mt5_tp,
                    )
                    if order_id:
                        mt5_ticket = int(order_id)
                        logger.info(
                            "%s: MT5 order submitted — ticket=%s sl=%.5f tp=%.5f",
                            asset.name,
                            order_id,
                            mt5_sl,
                            mt5_tp,
                        )
            else:
                fill_price, entry_slippage_bps, _ = asset.execution_bridge.fill_price(
                    asset.ticker, broker_side, qty, entry_price
                )
        asset._last_entry_slippage = entry_slippage_bps

        if asset.config.get("dynamic_sltp", {}).get("enabled", False):
            regime = getattr(asset, "_current_regime", "neutral")
            sltp_result = asset._sltp_engine.compute_barriers(
                entry_price=fill_price,
                side=side,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=regime,
                vol=vol,
                meta_confidence=asset._last_meta_proba,
            )
            intent = PositionIntent(
                side=side,
                entry_price=fill_price,
                entry_date=entry_date,
                stop_loss=sltp_result.stop_loss,
                take_profit=sltp_result.take_profit,
                vol=vol,
            )
        else:
            intent = PositionIntent.from_price_and_vol(side, fill_price, entry_date, vol, sl_mult, tp_mult)

        if tp_geo is None:
            from paper_trading.entry.tp_compiler import compute_take_profit

            sl_dist = abs(intent.stop_loss - fill_price)
            tp_geo = compute_take_profit(
                fill_price,
                sl_dist,
                state,
                getattr(asset, "_entry_archetype", "UNKNOWN"),
                asset._structure_detector.detect(data),
            )

        if side == PositionSide.LONG:
            intent.take_profit = fill_price + tp_geo.tp_distance
        else:
            intent.take_profit = fill_price - tp_geo.tp_distance

        asset.pos_mgr.open(intent)

        if asset._shadow_sltp is not None:
            asset._shadow_sltp.record_entry(
                side=side,
                entry_price=float(fill_price),
                entry_date=entry_date,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=getattr(asset, "_current_regime", "neutral"),
                meta_confidence=getattr(asset, "_last_meta_proba", None),
            )

        asset.position = {
            "side": intent.side,
            "entry": intent.entry_price,
            "sl": intent.stop_loss,
            "tp": intent.take_profit,
            "entry_date": intent.entry_date,
            "vol": intent.vol,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "tp_geo": tp_geo,
            "mt5_ticket": mt5_ticket,
        }
        asset._entry_vol = vol
        asset._bars_at_entry = 0
        asset._initial_sl = float(intent.stop_loss)
        asset._initial_tp = float(intent.take_profit)

        if asset.config.get("dynamic_sltp", {}).get("enabled", False) and asset._initial_sl is not None:
            asset._sltp_engine.reset_best_price(fill_price)

        asset._entry_price = intent.entry_price
        asset._regime_adjusted_entry = asset.regime_geometry.get(state, {}).get("sl_mult", 1.0) < 1.0

        trade_id = f"{entry_date}_{side}_{asset.name}"
        asset._current_trade_id = trade_id
        entry_action_type = "immediate" if asset._pending_entries.get(side) is None else "deferred"
        deferred_bars = 0
        if entry_action_type == "deferred" and side in asset._pending_entries:
            deferred_bars = (
                asset._pending_entries[side]._bars_pending
                if hasattr(asset._pending_entries.get(side), "_bars_pending")
                else 0
            )

        asset._attribution.record_prediction(
            trade_id=trade_id,
            signal=side,
            label=getattr(asset, "_last_label", 0),
            confidence=getattr(asset, "_last_confidence", 0.0),
            prob_long=getattr(asset, "_last_prob_long", 0.0),
            prob_short=getattr(asset, "_last_prob_short", 0.0),
            prob_neutral=getattr(asset, "_last_prob_neutral", 0.0),
            meta_proba=getattr(asset, "_last_meta_proba", None),
            regime_at_entry=getattr(asset, "_current_regime", "neutral"),
            archetype_at_entry=getattr(asset, "_entry_archetype", "UNKNOWN"),
        )
        asset._attribution.record_execution(
            trade_id=trade_id,
            entry_type=entry_action_type,
            deferred_bars=deferred_bars,
            entry_price=float(fill_price),
            mid_price_at_signal=float(entry_price),
            entry_slippage_bps=entry_slippage_bps,
        )
        asset._attribution.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=0.0,
        )
        asset._attribution.record_decision_quality(
            trade_id=trade_id,
            entry_pressure_pct=getattr(asset, "_entry_pressure", None),
        )

        asset._scale_out_plan = None
        if asset._scale_out_engine is not None:
            asset._scale_out_plan = asset._scale_out_engine.build_plan(
                side, float(intent.entry_price), float(intent.take_profit), tier_specs=tp_geo.scale_out_tiers
            )

    def poll_pending_entries(self, df: pd.DataFrame, asset) -> None:
        if not asset._pending_entries:
            return

        to_remove = []
        structure = asset._structure_detector.detect(df)
        today = str(pd.Timestamp.now(tz=ET).date())

        for direction, entry in asset._pending_entries.items():
            if not entry.is_active:
                to_remove.append(direction)
                continue

            entry.update()
            if entry.status == DeferredEntryStatus.EXPIRED:
                to_remove.append(direction)
                continue

            entry_action = asset._entry_optimizer.evaluate(
                entry.decision.signal, entry.decision.archetype, structure, asset.config.get("entry_optimization", {})
            )

            tp_geo = None
            if entry_action == EntryAction.ENTER:
                vol = self.tb_vol(df["close"] if isinstance(df, pd.DataFrame) and "close" in df.columns else df)
                state = asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW"
                curr_sl_mult, _, _ = compute_effective_multipliers(
                    base_sl=asset.sl_mult,
                    base_tp=asset.tp_mult,
                    validity_state=state,
                    regime_geometry=asset.regime_geometry,
                    narrative_sl_mult=asset.governance._narrative_sl_mult,
                    liquidity_sl_mult=asset.governance._liquidity_sl_mult,
                    narrative_size_scalar=asset.governance._narrative_size_scalar,
                    liquidity_size_scalar=asset.governance._liquidity_size_scalar,
                )
                sl_dist = float(df["close"].iloc[-1]) * vol * curr_sl_mult

                from paper_trading.entry.tp_compiler import compute_take_profit

                tp_geo = compute_take_profit(
                    float(df["close"].iloc[-1]), sl_dist, state, entry.decision.archetype, structure
                )

            policy_dec = asset._execution_policy.handle(
                entry_action, entry.decision, entry.decision.archetype, structure, tp_geo=tp_geo, deferred=entry
            )
            asset._last_policy_hash = str(
                hash(
                    (
                        policy_dec.action,
                        policy_dec.archetype,
                        policy_dec.reason,
                        str(policy_dec.entry_plan),
                        str(policy_dec.exit_plan),
                    )
                )
            )[:12]
            asset._entry_archetype = entry.decision.archetype

            if policy_dec.action == EntryAction.ENTER:
                side = PositionSide(direction)
                ok, reason = self.can_enter(
                    side,
                    float(df["close"].iloc[-1]),
                    last_stop_out_date=asset._last_stop_out_date,
                    last_stop_out_side=asset._last_stop_out_side,
                    config=asset.config,
                    cooldown_penalty_func=asset._cooldown_penalty,
                    pending_entries=asset._pending_entries,
                    cycle_counter=asset._cycle_counter,
                    last_signal_flip_cycle=asset._last_signal_flip_cycle,
                    min_flip_interval_bars=asset._min_flip_interval_bars,
                    context={"regime": getattr(asset, "_current_regime", "neutral")},
                )
                if not ok:
                    logger.info(
                        "%s: entry gate blocking deferred %s entry — %s",
                        asset.name,
                        direction,
                        reason,
                    )
                    entry.cancel(reason=reason)
                    to_remove.append(direction)
                    continue
                logger.info(f"{asset.name}: TRIGGERING deferred {direction} entry (Policy: {policy_dec.reason})")
                entry.trigger(float(df["close"].iloc[-1]))
                self.open_position(side, entry.decision.close_price, today, df, tp_geo=policy_dec.exit_plan)
                if asset.position is not None:
                    asset.position["confidence"] = entry.decision.confidence
                    asset.position["policy_reason"] = policy_dec.reason
                entry.close()
                to_remove.append(direction)

            elif policy_dec.action == EntryAction.SKIP:
                logger.info(f"{asset.name}: CANCELLING deferred {direction} entry (Policy: {policy_dec.reason})")
                entry.cancel(reason=policy_dec.reason)
                to_remove.append(direction)

        for direction in to_remove:
            del asset._pending_entries[direction]
