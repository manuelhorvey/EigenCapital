import logging
import time

import numpy as np
import pandas as pd
import pytz

from paper_trading.entry.decision import EntryAction, PositionIntent, PositionSide
from paper_trading.entry.deferred_entry import DeferredEntryStatus
from paper_trading.governance.multipliers import compute_effective_multipliers
from quorrin.domain.entities.position import OrderType, StackLayer
from shared.sizing_chain import SizingChain, SizingInput, SizingResult
from shared.volatility import estimate_ewm_vol

logger = logging.getLogger("quorrin.entry_service")

ET = pytz.timezone("US/Eastern")


class EntryService:
    """Entry service methods. Stateless — methods take everything they need as parameters."""

    def effective_capital(self, *, initial_capital, capital_base, current_value) -> float:
        if initial_capital <= 0:
            return capital_base
        growth = min(current_value / initial_capital, 3.0)
        return capital_base * growth

    def tb_vol(self, close_series, vol_lookback=21):
        returns = np.log(close_series / close_series.shift(1))
        vol = returns.rolling(vol_lookback).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def drawdown_taper(
        self,
        current_drawdown_pct: float,
        start_dd: float = -0.05,
        end_dd: float = -0.15,
        min_size: float = 0.50,
    ) -> float:
        if current_drawdown_pct >= start_dd:
            return 1.0
        if current_drawdown_pct <= end_dd:
            return min_size
        t = (current_drawdown_pct - start_dd) / (end_dd - start_dd)
        return max(1.0 - t * (1.0 - min_size), min_size)

    def composite_size_scalar(
        self,
        extra_scalar: float = 1.0,
        *,
        validity_state,
        sl_mult,
        tp_mult,
        regime_geometry,
        governance,
        pos_mgr,
        meta_size_multiplier,
        drawdown_taper: float = 1.0,
    ) -> float:
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
            * drawdown_taper
        )

    def compute_notional(self, effective_capital_val: float, size_scalar_val: float) -> float:
        return effective_capital_val * size_scalar_val

    def sizing_config(
        self,
        close: pd.Series,
        position_size_scalar: float = 1.0,
        *,
        execution_bridge,
        ticker,
        config,
        effective_capital_val,
        size_scalar_val,
    ) -> dict:
        cfg = dict(config)
        if execution_bridge is None:
            return cfg
        price = float(close.iloc[-1]) if len(close) else 0.0
        if price <= 0:
            return cfg
        notional = self.compute_notional(effective_capital_val, size_scalar_val)
        cfg["impact_bps"] = execution_bridge.estimate_impact_bps(ticker, notional)
        return cfg

    def can_enter(
        self,
        side,
        price,
        *,
        last_stop_out_cycle,
        last_stop_out_side,
        config,
        cooldown_penalty_func,
        pending_entries,
        cycle_counter,
        last_signal_flip_cycle,
        min_flip_interval_bars,
        context=None,
    ) -> tuple[bool, str]:
        if last_stop_out_cycle is not None:
            cross_cooldown_cycles = config.get("stopout_cross_side_cooldown_cycles", 1)
            elapsed_cycles = cycle_counter - last_stop_out_cycle
            if elapsed_cycles < cross_cooldown_cycles:
                remaining = cross_cooldown_cycles - elapsed_cycles
                return False, f"cross_side_stopout_cooldown_{remaining}"

        if last_stop_out_cycle is not None and last_stop_out_side == side and cycle_counter - last_stop_out_cycle < 1:
            return False, "same_cycle_stopout_lock"

        penalty = cooldown_penalty_func(side)
        if penalty > 0:
            return False, f"cooldown_active_{penalty:.2f}"

        if side in pending_entries:
            return False, "pending_entry_exists"

        cycles_since_flip = cycle_counter - last_signal_flip_cycle
        if cycles_since_flip < min_flip_interval_bars:
            return False, f"signal_flip_cooldown_{cycles_since_flip}"

        return True, "ok"

    def open_position(
        self, side, entry_price, entry_date, asset, df=None, tp_geo=None, order_type=OrderType.ENTRY, stack_cmd=None
    ):
        data = df if df is not None else asset.price_data
        vol, entry_price = self._validate_price_vol(asset, data, entry_price)
        if vol is None:
            return

        # Use current market price for fill/SL/TP instead of the decision's
        # close_price which may be stale (yesterday's close vs today's live).
        # The decision determines direction; the market determines fill price.
        live_entry = getattr(asset, "current_price", None)
        if live_entry is not None and not pd.isna(live_entry) and live_entry > 0:
            entry_price = float(live_entry)

        state = self._resolve_validity_state(asset)

        # ── Stacking branch ─────────────────────────────────────────
        if order_type == OrderType.STACK:
            if stack_cmd is None:
                logger.error("%s: STACK order missing StackCommand", asset.name)
                return

            # Compute stack's tighter SL via risk envelope model
            stack_config = asset.config.get("stacking", {})
            stack_sl_tighten = stack_config.get("stack_sl_tighten", 0.5)
            existing_sl = asset.position.get("sl") if asset.position else None
            if existing_sl is not None and vol > 0 and entry_price > 0:
                base_sl_distance_pct = abs(entry_price - existing_sl) / entry_price
                stack_sl_distance_pct = base_sl_distance_pct * stack_sl_tighten
                if side == "long":
                    intent_sl = entry_price * (1 - stack_sl_distance_pct)
                else:
                    intent_sl = entry_price * (1 + stack_sl_distance_pct)
            else:
                intent_sl = self._compute_stop_loss(asset, data, side, entry_price, 1.0, 1.0, 0.01)
            if intent_sl is None:
                return

            final_tp = asset.position.get("tp") if asset.position else None
            fill_price, entry_slippage_bps, mt5_ticket = self._submit_to_broker(
                asset,
                side,
                entry_price,
                intent_sl,
                final_tp,
                state,
                order_type=order_type,
            )
            if fill_price is None:
                return
            layer = StackLayer(
                entry_price=float(fill_price),
                size=stack_cmd.size,
                timestamp=entry_date,
                signal_id=stack_cmd.reason,
                pnl_at_time=0.0,
                stop_loss=float(intent_sl),
            )
            self._record_stack_layer(asset, layer, mt5_ticket)
            self._record_attribution(asset, side, entry_date, entry_price, fill_price, entry_slippage_bps, None, None)
            logger.info(
                "%s: STACK layer=%d size=%.4f price=%.5f sl=%.5f total_size=%.4f avg_price=%.5f",
                asset.name,
                stack_cmd.expected_layer_idx,
                stack_cmd.size,
                fill_price,
                intent_sl,
                asset.position.get("total_size", 0) if asset.position else 0,
                asset.position.get("avg_price", 0) if asset.position else 0,
            )
            return

        # ── Normal entry ─────────────────────────────────────────────
        sl_mult, tp_mult = self._compute_multipliers(asset, state)
        intent_sl = self._compute_stop_loss(asset, data, side, entry_price, sl_mult, tp_mult, vol)
        if intent_sl is None:
            return
        tp_geo, final_tp = self._compute_take_profit(asset, data, side, entry_price, intent_sl, tp_geo, state)
        sl_dist = abs(intent_sl - entry_price)

        if not self._validate_sltp_invariants(
            asset, side, entry_price, intent_sl, final_tp, sl_dist, sl_mult, tp_mult, tp_geo
        ):
            return

        fill_price, entry_slippage_bps, mt5_ticket = self._submit_to_broker(
            asset,
            side,
            entry_price,
            intent_sl,
            final_tp,
            state,
        )
        if fill_price is None:
            return
        asset._last_entry_slippage = entry_slippage_bps

        intent = PositionIntent(
            side=side,
            entry_price=fill_price,
            entry_date=entry_date,
            stop_loss=float(intent_sl),
            take_profit=float(final_tp),
            vol=vol,
        )
        self._record_position_state(
            asset, side, intent, sl_mult, tp_mult, tp_geo, vol, fill_price, state, mt5_ticket, data
        )
        self._record_attribution(asset, side, entry_date, entry_price, fill_price, entry_slippage_bps, intent, tp_geo)

    # ── Private helpers for open_position ─────────────────────────────────────

    def _validate_price_vol(self, asset, data, entry_price):
        vol = estimate_ewm_vol(data["close"], span=100)
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
            return None, None

        current_price = getattr(asset, "current_price", None)
        max_deviation = asset.config.get("max_entry_slippage_pct", 2.0) / 100.0
        if current_price is not None and current_price > 0:
            deviation = abs(current_price / entry_price - 1)
            if deviation > max_deviation:
                logger.warning(
                    "%s: entry skipped — price deviated %.2f%% from signal price (max %.2f%%)",
                    asset.name,
                    deviation * 100,
                    max_deviation * 100,
                )
                return None, None
        return vol, entry_price

    def _resolve_validity_state(self, asset):
        state = asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW"
        asset._entry_validity_state = state
        return state

    def _compute_multipliers(self, asset, state):
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
        return sl_mult, tp_mult

    def _compute_stop_loss(self, asset, data, side, entry_price, sl_mult, tp_mult, vol):
        if asset.config.get("dynamic_sltp", {}).get("enabled", False):
            regime = getattr(asset, "_current_regime", "neutral")
            sltp_result = asset._sltp_engine.compute_barriers(
                entry_price=entry_price,
                side=side,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=regime,
                vol=vol,
                meta_confidence=asset._last_meta_proba,
            )
            return sltp_result.stop_loss
        if side == PositionSide.LONG:
            return entry_price * (1 - vol * sl_mult)
        return entry_price * (1 + vol * sl_mult)

    def _compute_take_profit(self, asset, data, side, entry_price, intent_sl, tp_geo, state):
        sl_dist = abs(intent_sl - entry_price)
        if tp_geo is None:
            from paper_trading.entry.tp_compiler import compute_take_profit

            tp_geo = compute_take_profit(
                entry_price,
                sl_dist,
                state,
                getattr(asset, "_entry_archetype", "UNKNOWN"),
                asset._structure_detector.detect(data),
            )
        raw_tp = entry_price + (tp_geo.tp_distance if side == PositionSide.LONG else -tp_geo.tp_distance)
        final_tp = max(raw_tp, entry_price * 0.001)
        if raw_tp <= 0:
            logger.warning(
                "%s: clamped negative TP %.6f -> %.6f (entry=%.6f tp_dist=%.6f)",
                asset.name,
                raw_tp,
                final_tp,
                entry_price,
                tp_geo.tp_distance,
            )
        return tp_geo, final_tp

    def _validate_sltp_invariants(
        self,
        asset,
        side,
        entry_price,
        intent_sl,
        final_tp,
        sl_dist,
        sl_mult,
        tp_mult,
        tp_geo,
    ):
        assert sl_dist > 0, f"SL distance must be positive, got {sl_dist}"
        assert tp_geo.tp_distance > 0, f"TP distance must be positive, got {tp_geo.tp_distance}"
        assert not pd.isna(intent_sl), f"NaN stop loss computed for {asset.name}"
        assert not pd.isna(final_tp), f"NaN take profit computed for {asset.name}"
        assert sl_mult > 0, f"SL multiplier must be positive, got {sl_mult}"
        assert tp_mult > 0, f"TP multiplier must be positive, got {tp_mult}"
        assert intent_sl > 0, f"Stop loss must be positive, got {intent_sl}"
        assert final_tp > 0, f"Take profit must be positive, got {final_tp}"

        rr = abs(final_tp - entry_price) / (sl_dist + 1e-9)
        min_rr = asset.config.get("dynamic_sltp", {}).get("min_rr_ratio", 1.5)
        if rr < min_rr:
            logger.warning(
                "%s: RR=%.2f < min=%.2f, aborting entry (sl_dist=%.6f tp=%.6f)",
                asset.name,
                rr,
                min_rr,
                sl_dist,
                final_tp,
            )
            return False
        if pd.isna(intent_sl) or pd.isna(final_tp):
            logger.error("%s: NaN SL=%.6f or TP=%.6f, aborting entry", asset.name, intent_sl, final_tp)
            return False
        return True

    def _submit_to_broker(self, asset, side, entry_price, intent_sl, final_tp, state, order_type=OrderType.ENTRY):
        fill_price = entry_price
        entry_slippage_bps = 0.0
        mt5_ticket = None
        if asset.execution_bridge is None:
            return fill_price, entry_slippage_bps, mt5_ticket

        cfg = asset.config
        dd_pct = getattr(asset, "_cycle_drawdown_pct", 0.0)
        sl_dist = abs(intent_sl - entry_price)
        is_mt5 = hasattr(asset.execution_bridge, "_is_real_broker") and asset.execution_bridge._is_real_broker
        side_str = side.value if hasattr(side, "value") else side
        broker_side = "buy" if side_str == "long" else "sell"

        if not is_mt5:
            dd_taper = self.drawdown_taper(
                dd_pct,
                start_dd=cfg.get("size_taper_start_dd", -0.05),
                end_dd=cfg.get("size_taper_end_dd", -0.15),
                min_size=cfg.get("size_taper_min", 0.50),
            )
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
                drawdown_taper=dd_taper,
            )

            sizing_input = SizingInput(
                equity=effective_cap,
                drawdown_pct=dd_pct,
                size_scalar=size_scalar,
                max_position_pct=cfg.get("max_position_pct_of_equity", 0.15),
                max_risk_pct=cfg.get("max_risk_per_trade_pct", 2.0),
                min_viable_pct=cfg.get("min_viable_position_pct", 0.01),
                drawdown_taper_start=cfg.get("size_taper_start_dd", -0.05),
                drawdown_taper_end=cfg.get("size_taper_end_dd", -0.15),
                drawdown_taper_min=cfg.get("size_taper_min", 0.50),
                entry_price=entry_price,
                sl_distance=sl_dist,
                is_mt5=False,
                ticker=asset.name,
            )
            result = SizingChain.compute(sizing_input)
        else:
            result = SizingResult(notional=0.0)

        if not is_mt5:
            if not result.is_viable:
                asset._last_entry_notional = 0.0
                asset._last_sizing_chain = {
                    "drawdown_taper": round(result.drawdown_taper, 4),
                    "effective_cap": round(result.effective_cap, 2),
                    "size_scalar": round(result.size_scalar_applied, 4),
                    "reason": result.skip_reason or "sizing_chain_blocked",
                }
                return None, entry_slippage_bps, mt5_ticket

            qty = result.quantity
            notional = result.notional
            asset._last_entry_notional = notional
            asset._last_sizing_chain = result.chain_breakdown

            logger.info(
                "SIZING %s: eff_cap=%.2f scalar=%.4f dd=%.2f pos_cap=%.2f risk_cap=%.2f -> final_not=%.2f qty=%.6f",
                asset.name,
                result.effective_cap,
                result.size_scalar_applied,
                result.drawdown_taper,
                result.position_cap,
                result.risk_cap_used,
                notional,
                qty,
            )
            fill_price, entry_slippage_bps, _ = asset.execution_bridge.fill_price(
                asset.ticker,
                broker_side,
                qty,
                entry_price,
            )
            return fill_price, entry_slippage_bps, mt5_ticket

        # ── MT5 path ────────────────────────────────────────────────────
        return self._submit_mt5_order(asset, broker_side, entry_price, intent_sl, final_tp, order_type=order_type)

    def _compute_mt5_qty(self, asset, entry_price, intent_sl):
        broker = asset.execution_bridge.broker
        if broker is None or not hasattr(broker, "get_account_summary"):
            return 0.0

        try:
            summary = broker.get_account_summary()
            mt5_equity = summary.portfolio_value
        except Exception:
            logger.error("%s: failed to fetch MT5 equity for independent sizing", asset.name)
            return 0.0

        if not mt5_equity or mt5_equity <= 0:
            logger.warning("%s: MT5 equity is %.2f, skipping MT5 sizing", asset.name, mt5_equity)
            return 0.0

        cfg = asset.config
        mt5_dd = getattr(broker, "current_mt5_drawdown_pct", lambda: 0.0)()
        sl_dist = abs(intent_sl - entry_price)

        sizing_input = SizingInput(
            equity=mt5_equity,
            drawdown_pct=mt5_dd,
            kelly_multiplier=getattr(asset, "_kelly_multiplier", 1.0),
            max_position_pct=cfg.get("max_position_pct_of_equity", 0.15),
            max_risk_pct=cfg.get("max_risk_per_trade_pct", 2.0),
            min_viable_pct=cfg.get("min_viable_position_pct", 0.01),
            drawdown_taper_start=cfg.get("size_taper_start_dd", -0.05),
            drawdown_taper_end=cfg.get("size_taper_end_dd", -0.15),
            drawdown_taper_min=cfg.get("size_taper_min", 0.50),
            entry_price=entry_price,
            sl_distance=sl_dist,
            is_mt5=True,
            ticker=asset.ticker,
        )
        result = SizingChain.compute(sizing_input)

        if not result.is_viable:
            return 0.0

        # MT5 lot conversion: sizing_chain computes qty = notional / entry_price (base units).
        # For pairs where quote ≠ account currency (USD), entry_price is not the correct
        # divisor. Determine the correct base-to-account-currency rate.
        ticker = asset.ticker
        if ticker.startswith("USD") and "=X" in ticker:
            # Base is account currency (USDJPY, USDCAD, USDCHF)
            base_to_acc = 1.0
        elif "=X" in ticker:
            quote = ticker[3:6]
            if quote != "USD":
                # Cross pair (e.g., GBPJPY, EURCHF) — need base-to-USD rate
                base = ticker[:3]
                base_usd = f"{base}USD=X"
                try:
                    cross_rate = broker.get_current_price(base_usd)
                    base_to_acc = cross_rate if cross_rate and cross_rate > 0 else entry_price
                except Exception:
                    base_to_acc = entry_price
            else:
                # Quote is USD (EURUSD, GBPUSD, etc.) — entry_price is correct
                base_to_acc = entry_price
        else:
            # Futures/indices (^DJI, NQ=F, GC=F, ES=F) — priced in USD
            base_to_acc = entry_price

        mt5_qty = result.notional / base_to_acc

        logger.info(
            "MT5_SIZING %s: equity=%.2f dd=%.2f kelly=%.4f max_pct=%.2f%% risk_cap=%.2f "
            "min_viable=%.2f -> final_not=%.2f base_to_acc=%.4f qty=%.4f",
            asset.name,
            mt5_equity,
            result.drawdown_taper,
            result.kelly_applied,
            sizing_input.max_position_pct * 100,
            result.risk_cap_used,
            result.min_viable_notional,
            result.notional,
            base_to_acc,
            mt5_qty,
        )
        return mt5_qty

    def _submit_mt5_order(self, asset, broker_side, entry_price, intent_sl, final_tp, order_type=OrderType.ENTRY):
        qty = self._compute_mt5_qty(asset, entry_price, intent_sl)
        if qty <= 0:
            return entry_price, 0.0, None

        broker = asset.execution_bridge.broker
        existing_positions = broker.get_positions()
        mt5_symbol = broker.ticker_to_mt5_symbol(asset.ticker)
        matching = [p for p in existing_positions if p.asset == mt5_symbol]
        if matching:
            # Stacking bypass: MT5 netting absorbs additional same-side orders
            if order_type == OrderType.STACK:
                logger.info(
                    "%s: stacking bypass MT5_ORPHAN guard — sending stack order on %s",
                    asset.name,
                    mt5_symbol,
                )
            else:
                paper_pos = asset.position
                # Phase D: orphan adoption — paper has position but no ticket (crash recovery / gap B)
                if paper_pos and paper_pos.get("mt5_ticket") is None:
                    ticket = int(matching[0].position_id)
                    logger.info(
                        "%s: PHASE_D_ADOPT adopting orphan ticket=%s on %s (sl=%.5f tp=%.5f)",
                        asset.name,
                        ticket,
                        mt5_symbol,
                        matching[0].stop_loss or 0.0,
                        matching[0].take_profit or 0.0,
                    )
                    return entry_price, 0.0, ticket
                # Load-bearing guard: prevents double-position on MT5 (paper already has ticket)
                tickets = [p.position_id or "?" for p in matching]
                logger.error(
                    "%s: MT5_ORPHAN blocking entry — %d open position(s) on %s (tickets=%s)",
                    asset.name,
                    len(matching),
                    mt5_symbol,
                    tickets,
                )
                return entry_price, 0.0, None

        mt5_sl = float(intent_sl)
        mt5_tp = float(final_tp)
        if pd.isna(mt5_sl) or pd.isna(mt5_tp):
            logger.error("%s: NaN SL/TP, aborting MT5 order", asset.name)
            return entry_price, 0.0, None

        fill_price, order_id = asset.execution_bridge.submit_market_order(
            asset.ticker,
            broker_side,
            qty,
            entry_price,
            sl=mt5_sl,
            tp=mt5_tp,
        )
        mt5_ticket = int(order_id) if order_id else None
        if not order_id:
            logger.error(
                "%s: MT5 order rejected — no ticket returned (fill_price=%s, qty=%s)",
                asset.name,
                fill_price,
                qty,
            )
            return None, 0.0, None
        logger.info("%s: MT5 order submitted — ticket=%s sl=%.5f tp=%.5f", asset.name, order_id, mt5_sl, mt5_tp)

        stored_sl, stored_tp = float(intent_sl), float(final_tp)
        if abs(mt5_sl - stored_sl) / max(abs(stored_sl), 1e-9) > 0.001:
            logger.error("%s: BROKER SL MISMATCH submitted=%.5f stored=%.5f", asset.name, mt5_sl, stored_sl)
        if abs(mt5_tp - stored_tp) / max(abs(stored_tp), 1e-9) > 0.001:
            logger.error("%s: BROKER TP MISMATCH submitted=%.5f stored=%.5f", asset.name, mt5_tp, stored_tp)
        return fill_price, 0.0, mt5_ticket

    def _record_position_state(
        self, asset, side, intent, sl_mult, tp_mult, tp_geo, vol, fill_price, state, mt5_ticket, data
    ):
        asset.pos_mgr.open(intent)

        # Initialize first stack layer
        first_layer = {
            "entry_price": float(fill_price),
            "size": vol,
            "timestamp": intent.entry_date,
            "signal_id": "entry",
            "pnl_at_time": 0.0,
        }
        layers_list = [first_layer]
        total_sz = vol

        # Position avg_price = fill price for first entry
        avg_price = float(fill_price)

        if asset._shadow_sltp is not None:
            asset._shadow_sltp.record_entry(
                side=side,
                entry_price=float(fill_price),
                entry_date=intent.entry_date,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=getattr(asset, "_current_regime", "neutral"),
                meta_confidence=getattr(asset, "_last_meta_proba", None),
            )
        sl_pct = abs(avg_price - intent.stop_loss) / (avg_price + 1e-9) * 100
        tp_pct = abs(intent.take_profit - avg_price) / (avg_price + 1e-9) * 100
        logger.info(
            "%s: ENTRY %s sz=%.4f entry=%.4f SL=%.4f (%.2f%%) TP=%.4f (%.2f%%) RR=%.2f",
            asset.name,
            intent.side,
            total_sz,
            avg_price,
            intent.stop_loss,
            sl_pct,
            intent.take_profit,
            tp_pct,
            tp_pct / (sl_pct + 1e-9),
        )
        new_position = {
            "side": intent.side,
            "entry": avg_price,
            "sl": intent.stop_loss,
            "tp": intent.take_profit,
            "entry_date": intent.entry_date,
            "vol": total_sz,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "tp_geo": tp_geo,
            "mt5_ticket": mt5_ticket,
            "layers": layers_list,
            "avg_price": avg_price,
            "total_size": total_sz,
            "base_entry_size": vol,
        }
        # Defensive: preserve existing mt5_ticket if broker didn't return one
        if mt5_ticket is None and asset.position and asset.position.get("mt5_ticket") is not None:
            new_position["mt5_ticket"] = asset.position["mt5_ticket"]
        asset.position = new_position
        asset.pos_mgr.position.base_entry_size = vol
        asset.pos_mgr.enforce_invariant(asset.name)
        asset._entry_vol = vol
        asset._bars_at_entry = 0
        asset._initial_sl = float(intent.stop_loss)
        asset._initial_tp = float(intent.take_profit)
        if asset.config.get("dynamic_sltp", {}).get("enabled", False) and asset._initial_sl is not None:
            asset._sltp_engine.reset_best_price(fill_price)
        asset._entry_price = intent.entry_price
        asset._regime_adjusted_entry = asset.regime_geometry.get(state, {}).get("sl_mult", 1.0) < 1.0
        asset._scale_out_plan = None
        if asset._scale_out_engine is not None:
            asset._scale_out_plan = asset._scale_out_engine.build_plan(
                side,
                float(intent.entry_price),
                float(intent.take_profit),
                tier_specs=tp_geo.scale_out_tiers,
            )

    def _record_stack_layer(self, asset, layer: StackLayer, mt5_ticket):
        if asset.position is None:
            logger.error("%s: cannot stack — no existing position", asset.name)
            return
        layers = asset.position.setdefault("layers", [])
        layer_dict = {
            "entry_price": layer.entry_price,
            "size": layer.size,
            "timestamp": layer.timestamp,
            "signal_id": layer.signal_id,
            "pnl_at_time": layer.pnl_at_time,
        }
        if layer.stop_loss > 0:
            layer_dict["stop_loss"] = layer.stop_loss
        layers.append(layer_dict)
        total_sz = sum(_l["size"] for _l in layers)
        avg = sum(_l["entry_price"] * _l["size"] for _l in layers) / max(total_sz, 1e-9)
        asset.position["avg_price"] = avg
        asset.position["total_size"] = total_sz
        asset.position["entry"] = avg
        asset.position["vol"] = total_sz
        if mt5_ticket is not None:
            asset.position["mt5_ticket"] = mt5_ticket
        # Update risk floor: the tightest SL across all layers
        if layer.stop_loss > 0:
            pos_side = asset.position.get("side", "long")
            if pos_side == "long":
                asset.position["risk_floor"] = max(asset.position.get("risk_floor", 0), layer.stop_loss)
            else:
                floor = asset.position.get("risk_floor", 0)
                asset.position["risk_floor"] = min(floor, layer.stop_loss) if floor > 0 else layer.stop_loss
        asset.pos_mgr.position.base_entry_size = asset.position.get("base_entry_size", total_sz)
        asset.pos_mgr.enforce_invariant(asset.name)

    def _record_attribution(self, asset, side, entry_date, entry_price, fill_price, entry_slippage_bps, intent, tp_geo):
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

    def poll_pending_entries(self, df: pd.DataFrame, asset) -> None:
        if not asset._pending_entries:
            return

        # ── Bypass-protection checks ─────────────────────────────────
        # Deferred entries bypass the governance pipeline's spread gate
        # and profit lock. Apply these checks inline here.

        # 1. Spread gate check
        from paper_trading.execution.gate_constants import SPREAD_GATE_STALENESS_SECS, SPREAD_TIER_BPS

        last_spread = getattr(asset, "_last_spread_bps", None)
        last_spread_time = getattr(asset, "_last_spread_time", 0.0)
        if last_spread is not None and last_spread_time > 0:
            spread_age = time.time() - last_spread_time
            if spread_age > SPREAD_GATE_STALENESS_SECS:
                logger.info("%s: deferred entry blocked — spread data stale (%ds old)", asset.name, spread_age)
                self._cancel_all_pending(asset, reason="stale_spread")
                return
            tier = asset.config.get("spread_tier", "fx_cross")
            threshold = SPREAD_TIER_BPS.get(tier, 20.0)
            if last_spread > threshold:
                logger.info(
                    "%s: deferred entry blocked — spread %.1fbps > %s threshold %.1fbps",
                    asset.name,
                    last_spread,
                    tier,
                    threshold,
                )
                self._cancel_all_pending(asset, reason="spread_gate")
                return

        # 2. Profit lock check (flip protection)
        profit_lock_pct = asset.config.get("profit_lock_threshold_pct", 15.0)
        if asset.pos_mgr.has_position():
            current_price = getattr(asset, "current_price", None)
            if current_price is not None and current_price > 0:
                unrealized_pnl = asset.pos_mgr.position_pnl(current_price)
                if unrealized_pnl > profit_lock_pct:
                    logger.info(
                        "%s: deferred flip blocked — unrealized PnL %.1f%% > profit lock %.1f%%",
                        asset.name,
                        unrealized_pnl,
                        profit_lock_pct,
                    )
                    self._cancel_all_pending(asset, reason="profit_lock")
                    return

        to_remove = []
        structure = asset._structure_detector.detect(df)
        today = str(pd.Timestamp.now(tz=ET).date())

        for direction, entry in asset._pending_entries.items():
            if not entry.is_active:
                to_remove.append(direction)
                continue

            # SELL_ONLY filter: suppress deferred BUY entries on flagged assets
            if direction == "long":
                from paper_trading.execution.gate_constants import get_sell_only_assets

                if asset.name in get_sell_only_assets():
                    logger.info(
                        "%s: sell-only filter — canceling deferred BUY entry",
                        asset.name,
                    )
                    entry.cancel(reason="sell_only_filter")
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
                dynamic_sltp_enabled = asset.config.get("dynamic_sltp", {}).get("enabled", False)
                if not dynamic_sltp_enabled:
                    vol = self.tb_vol(df["close"] if isinstance(df, pd.DataFrame) and "close" in df.columns else df)
                    state = asset.validity_sm.current_state.value if asset.validity_sm else "YELLOW"
                    curr_sl_mult, curr_tp_mult, _ = compute_effective_multipliers(
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
                        float(df["close"].iloc[-1]),
                        sl_dist,
                        state,
                        entry.decision.archetype,
                        structure,
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
                    last_stop_out_cycle=asset._last_stop_out_cycle,
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

    def _cancel_all_pending(self, asset, reason: str) -> None:
        for direction, entry in list(asset._pending_entries.items()):
            entry.cancel(reason=reason)
        asset._pending_entries.clear()
