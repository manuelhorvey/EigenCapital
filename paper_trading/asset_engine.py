import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from labels.meta_labels import MetaLabelModel
from monitoring.importance_tracker import ImportanceStore, StabilityResult
from monitoring.psi_monitor import PSIMonitor, PSISnapshot
from monitoring.validity_state_machine import (
    ValidityStateMachine as _ValidityStateMachine,
)
from paper_trading.asset_pnl_controller import AssetPnlController
from paper_trading.attribution.collector import AttributionCollector, TradeAttributionRecord
from paper_trading.config_manager import get_config
from paper_trading.entry.decision import EntryAction, PositionIntent, PositionSide, SignalType, TradeDecision
from paper_trading.entry.deferred_entry import DeferredEntryStatus
from paper_trading.governance.asset import AssetGovernance
from paper_trading.governance.regime import RegimeClassifier
from paper_trading.governance.risk import record_trade_outcome as _record_exit_outcome
from paper_trading.inference.pipeline import AssetInferencePipeline
from paper_trading.inference.training import AssetTrainingPipeline
from paper_trading.ops.data_fetcher import flatten, safe_download
from paper_trading.position.dynamic_sltp import DynamicSLTPEngine, build_dynamic_sltp_from_config
from paper_trading.position.manager import PositionManager
from paper_trading.position.scale_out import build_scale_out_from_config
from paper_trading.shadow.engine import ShadowSLTPEngine
from paper_trading.state_store import _SKIP_JOURNAL, StateStore
from shared.registry import StrategyRegistry

logger = logging.getLogger("quantforge.asset_engine")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)


class AssetEngine:
    _MIN_SIZE_SCALAR = 0.30

    def __init__(
        self,
        ticker,
        name,
        contract,
        allocation,
        halt_config=None,
        config=None,
        expected_prob_conf=0.45,
        state_store=None,
        journal_path=None,
        sl_mult=1.0,
        tp_mult=2.5,
        regime_geometry=None,
        initial_capital=None,
        position_size=None,
        retrain_window=None,
        execution_bridge=None,
    ):
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        engine_cfg = get_config()
        self.initial_capital = initial_capital if initial_capital is not None else engine_cfg.capital * allocation
        self.capital_base = self.initial_capital
        self.halt_config = halt_config or dict(engine_cfg.halt)
        self.config = config or {}
        self.expected_prob_conf = expected_prob_conf
        self.model = None
        self.signal_data = None
        self.peak_value = self.initial_capital
        self.current_value = self.initial_capital
        self.start_time = datetime.now(tz=ET)
        self.last_signal_date = None
        self.trades = []
        self.prob_history = []
        self.model_path = os.path.join(BASE, "paper_trading", "models", f"{contract.name}_model.pkl")
        self._trained = False
        self.position = None
        self.trade_log = []
        self.current_price = None
        self.pos_mgr = PositionManager(
            self.initial_capital,
            position_size if position_size is not None else engine_cfg.position_size,
        )
        self.validity_sm = _ValidityStateMachine()
        self._reg = StrategyRegistry.get_instance()
        self._model_iface = self._reg.get_model(self.name)
        self._signal_strategy = self._reg.get_signal(self.name)
        self._sizing_strategy = self._reg.get_sizing(self.name)
        self._pnl_strategy = self._reg.get_pnl(self.name)
        self._feature_pipeline = self._reg.get_features(self.name)
        self._risk_signal = None
        self._shadow_action = None
        self._shadow_drift_intel = None
        self._shadow_learning = None
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.regime_geometry = regime_geometry or {}
        self.execution_bridge = execution_bridge
        self._research_mode = engine_cfg.research_mode
        self._last_macro_dir: int | None = None
        self._last_blend_dir: int | None = None
        self._entry_signal_dir: int = 0
        self._retrain_window = retrain_window if retrain_window is not None else engine_cfg.retrain_window
        if state_store is not None:
            self.state_store = state_store
        elif journal_path is _SKIP_JOURNAL:
            self.state_store = None
        else:
            self.state_store = _STORE
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._importance_store = ImportanceStore(base_dir)
        self._psi_monitor = PSIMonitor(base_dir)
        self.regime_classifier = RegimeClassifier()
        if self.config.get("regime_sizing"):
            self._sizing_strategy.regime_aware = True

        self._sltp_engine = build_dynamic_sltp_from_config(self.config)
        self._scale_out_engine = build_scale_out_from_config(self.config)

        # Shadow SL/TP engine — parallel counterfactual replay
        self._shadow_sltp: ShadowSLTPEngine | None = None
        if self.config.get("shadow_sltp", {}).get("enabled", False):
            shadow_cfg = self.config.get("shadow_sltp", {})
            alt_engine = DynamicSLTPEngine(
                method=shadow_cfg.get("method", "atr"),
                atr_period=shadow_cfg.get("atr_period", self.config.get("dynamic_sltp", {}).get("atr_period", 14)),
                atr_mult_sl=shadow_cfg.get("atr_mult_sl", 2.5),
                atr_mult_tp=shadow_cfg.get("atr_mult_tp", 2.0),
                min_rr_ratio=shadow_cfg.get("min_rr_ratio", 1.2),
                trailing_activation_mult=shadow_cfg.get("trailing_activation_mult", 1.0),
                trailing_distance_mult=shadow_cfg.get("trailing_distance_mult", 1.5),
                confidence_sl_adjust=shadow_cfg.get("confidence_sl_adjust", 0.3),
            )
            self._shadow_sltp = ShadowSLTPEngine(
                name=shadow_cfg.get("name", "tight_trail"),
                alt_engine=alt_engine,
            )
            logger.info("%s: shadow SL/TP engine '%s' initialized", self.name, self._shadow_sltp.name)
        self._scale_out_plan = None
        self._last_adjust_bar = 0
        self._bars_at_entry = 0
        self._entry_vol = None
        self._meta_label_model = None
        self._window_id_counter = 0
        self._current_window_train_start = ""
        self._current_window_train_end = ""
        self._last_stability: StabilityResult | None = None
        self._last_psi_drift: PSISnapshot | None = None
        self.governance = AssetGovernance(self.name, self.config, self.halt_config)
        self.governance.load_narrative_state()
        self.governance.load_liquidity_state(getattr(self, "price_data", None))
        self._last_stop_out_side: str | None = None
        self._last_stop_out_date: pd.Timestamp | None = None
        self._last_stop_out_price: float | None = None
        self._cooldown_score: float = 0.0
        self._last_cooldown_update: pd.Timestamp | None = None
        self._entry_price: float | None = None
        self._regime_adjusted_entry: bool = False
        self._churn_ratio_threshold = self.config.get("churn_ratio_threshold", 0.50)
        self._initial_settlement_done: bool = False
        self._last_signal_flip_cycle: int = -self.config.get("min_flip_interval_bars", 3) * 2
        self._min_flip_interval_bars = self.config.get("min_flip_interval_bars", 3)
        self._cycle_counter: int = 0
        self._training = AssetTrainingPipeline(self)
        self._pnl = AssetPnlController(self)
        self._inference = AssetInferencePipeline(self)
        from features.archetypes import ArchetypeClassifier

        self._archetype_classifier = ArchetypeClassifier()
        from features.market_structure import MarketStructureDetector
        from paper_trading.entry.optimizer import EntryOptimizer
        from paper_trading.entry.policy import ExecutionPolicyLayer

        self._structure_detector = MarketStructureDetector()
        self._entry_optimizer = EntryOptimizer()
        self._execution_policy = ExecutionPolicyLayer()
        self._pending_entries: dict[str, object] = {}  # direction -> DeferredEntry
        self._attribution = AttributionCollector()
        self._experiment_id: str = ""
        self._attribution_export_dir: str | None = None
        self._current_trade_id: str | None = None
        self._attribution_buffer: list[TradeAttributionRecord] = []

    def set_experiment_context(self, experiment_id: str, export_dir: str | None = None) -> None:
        """Set experiment tracking context for attribution export."""
        self._experiment_id = experiment_id
        if export_dir is not None:
            self._attribution_export_dir = export_dir
            os.makedirs(export_dir, exist_ok=True)

    def flush_attribution(self) -> None:
        """Append buffered attribution records to persistent parquet storage.

        Exports incrementally so data survives crash/restart.
        """
        if not self._attribution_buffer or not self._attribution_export_dir:
            return
        try:
            path = os.path.join(self._attribution_export_dir, f"{self.name}_attribution.parquet")
            records = list(self._attribution_buffer)
            self._attribution_buffer.clear()
            frame = TradeAttributionRecord.to_frame(records, experiment_id=self._experiment_id)
            if os.path.exists(path):
                existing = pd.read_parquet(path)
                frame = pd.concat([existing, frame], ignore_index=True)
            frame.to_parquet(path, index=False)
            logger.debug("attribution: flushed %d records for %s to %s", len(records), self.name, path)
        except Exception:
            logger.exception("attribution: failed to flush records for %s", self.name)

    def set_narrative_state(self, narr) -> None:
        self.governance.set_narrative_state(narr)

    def _refresh_liquidity(self, df) -> None:
        self.governance.refresh_liquidity(df)

    def _effective_capital(self) -> float:
        if self.initial_capital <= 0:
            return self.capital_base
        growth = self.current_value / self.initial_capital
        return self.capital_base * growth

    def _meta_size_multiplier(self) -> float:
        """Convert meta-label confidence to a position size multiplier.

        Meta-confidence is interpreted as "how much capital should we
        trust this prediction with?" — not "how far should this trade run?"

        Mapping (linear interpolation from threshold to certainty):
            [threshold, 1.0] → [min_size, 1.0]

        Below threshold → 0.0 (effectively blocks the trade).
        """
        if not self.config.get("meta_labeling", {}).get("enabled", False):
            return 1.0
        meta_proba = getattr(self, "_last_meta_proba", None)
        if meta_proba is None:
            return 1.0

        threshold = self.config.get("meta_labeling", {}).get("threshold", 0.55)
        min_size = self.config.get("meta_labeling", {}).get("min_size_on_threshold", 0.25)

        if meta_proba < threshold:
            return 0.0
        if meta_proba >= 1.0:
            return 1.0

        t = (meta_proba - threshold) / (1.0 - threshold)
        return min_size + t * (1.0 - min_size)

    def _composite_size_scalar(self, extra_scalar: float = 1.0) -> float:
        return (
            self.pos_mgr.position_size
            * self.pos_mgr.exposure_multiplier
            * extra_scalar
            * self._meta_size_multiplier()
            * max(
                self.governance._narrative_size_scalar * self.governance._liquidity_size_scalar, self._MIN_SIZE_SCALAR
            )
        )

    def _compute_notional(self, extra_scalar: float = 1.0) -> float:
        return self._effective_capital() * self._composite_size_scalar(extra_scalar)

    def _sizing_config(self, close: pd.Series, position_size_scalar: float = 1.0) -> dict:
        cfg = dict(self.config)
        if self.execution_bridge is None:
            return cfg
        price = float(close.iloc[-1]) if len(close) else 0.0
        if price <= 0:
            return cfg
        notional = self._compute_notional(position_size_scalar)
        cfg["impact_bps"] = self.execution_bridge.estimate_impact_bps(self.ticker, notional)
        return cfg

    def _macro_blend_trade_returns(self, trade_ret: float) -> tuple[float, float]:
        """Attribute trade PnL to macro-only vs blended heads by directional agreement."""
        entry = self._entry_signal_dir
        if entry == 0:
            return trade_ret, trade_ret
        macro_dir = self._last_macro_dir
        blend_dir = self._last_blend_dir
        macro_ret = trade_ret if macro_dir is None or macro_dir == entry else -trade_ret
        blend_ret = trade_ret if blend_dir is None or blend_dir == entry else -trade_ret
        return macro_ret, blend_ret

    def _enable_adaptive_macro(self) -> None:
        if not self.config.get("adaptive_macro") or self.model is None:
            return
        macro_head = getattr(self.model, "macro_head", None)
        if macro_head is not None:
            macro_head.online_weight = True

    def _load_meta_label_model(self) -> None:
        if not self.config.get("meta_labeling", {}).get("enabled", False):
            return
        try:
            model = MetaLabelModel(
                threshold=self.config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            model._load(model._model_path(self.name))
            if model._trained:
                self._meta_label_model = model
                logger.info("%s: meta-label model loaded from cache", self.name)
        except Exception as e:
            logger.debug("%s: no cached meta-label model: %s", self.name, e)

    def _tb_vol(self, close_series):
        returns = np.log(close_series / close_series.shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def _open_position(self, side, entry_price, entry_date, df=None, tp_geo=None):
        data = df if df is not None else self.price_data
        vol = self._tb_vol(data["close"])
        if pd.isna(vol) or pd.isna(entry_price) or entry_price == 0:
            logger.warning("%s: skipped entry — invalid price=%s or vol=%s", self.name, entry_price, vol)
            return

        # Regime-conditional geometry selection (multipliers on base sl_mult/tp_mult)
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})

        sl_mult = (
            self.sl_mult
            * geom.get("sl_mult", 1.0)
            * self.governance._narrative_sl_mult
            * self.governance._liquidity_sl_mult
        )
        tp_mult = self.tp_mult * geom.get("tp_mult", 1.0)

        fill_price = entry_price
        entry_slippage_bps = 0.0
        if self.execution_bridge is not None:
            broker_side = "buy" if side == "long" else "sell"
            notional = self._compute_notional()
            qty = max(notional / entry_price, 1e-6)
            fill_price, entry_slippage_bps, _ = self.execution_bridge.fill_price(
                self.ticker, broker_side, qty, entry_price
            )
        self._last_entry_slippage = entry_slippage_bps

        # Use DynamicSLTPEngine if configured, else fall back to original EWM vol method
        if self.config.get("dynamic_sltp", {}).get("enabled", False):
            regime = getattr(self, "_current_regime", "neutral")
            sltp_result = self._sltp_engine.compute_barriers(
                entry_price=fill_price,
                side=side,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=regime,
                vol=vol,
                meta_confidence=self._last_meta_proba,
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

        # Phase 2: Reward Geometry Compilation (Frozen at entry)
        if tp_geo is None:
            # Fallback if not provided by policy layer
            from paper_trading.entry.tp_compiler import compute_take_profit

            sl_dist = abs(intent.stop_loss - fill_price)
            tp_geo = compute_take_profit(
                fill_price,
                sl_dist,
                state,
                getattr(self, "_entry_archetype", "UNKNOWN"),
                self._structure_detector.detect(data),
            )

        # Override TP price based on compiler's reward shape
        if side == PositionSide.LONG:
            intent.take_profit = fill_price + tp_geo.tp_distance
        else:
            intent.take_profit = fill_price - tp_geo.tp_distance

        self.pos_mgr.open(intent)

        # Shadow entry recording (isolated counterfactual)
        if self._shadow_sltp is not None:
            self._shadow_sltp.record_entry(
                side=side,
                entry_price=float(fill_price),
                entry_date=entry_date,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=getattr(self, "_current_regime", "neutral"),
                meta_confidence=getattr(self, "_last_meta_proba", None),
            )

        self.position = {
            "side": intent.side,
            "entry": intent.entry_price,
            "sl": intent.stop_loss,
            "tp": intent.take_profit,
            "entry_date": intent.entry_date,
            "vol": intent.vol,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "tp_geo": tp_geo,
        }
        self._entry_vol = vol
        self._bars_at_entry = 0
        self._initial_sl = float(intent.stop_loss)
        self._initial_tp = float(intent.take_profit)

        if self.config.get("dynamic_sltp", {}).get("enabled", False) and self._initial_sl is not None:
            self._sltp_engine.reset_best_price(fill_price)

        self._entry_price = intent.entry_price
        self._regime_adjusted_entry = geom.get("sl_mult", 1.0) < 1.0

        # Phase 6: Attribution (observe, never mutate)
        trade_id = f"{entry_date}_{side}_{self.name}"
        self._current_trade_id = trade_id
        entry_action_type = "immediate" if self._pending_entries.get(side) is None else "deferred"
        deferred_bars = 0
        if entry_action_type == "deferred" and side in self._pending_entries:
            deferred_bars = (
                self._pending_entries[side]._bars_pending
                if hasattr(self._pending_entries.get(side), "_bars_pending")
                else 0
            )

        self._attribution.record_prediction(
            trade_id=trade_id,
            signal=side,
            label=getattr(self, "_last_label", 0),
            confidence=getattr(self, "_last_confidence", 0.0),
            prob_long=getattr(self, "_last_prob_long", 0.0),
            prob_short=getattr(self, "_last_prob_short", 0.0),
            prob_neutral=getattr(self, "_last_prob_neutral", 0.0),
            meta_proba=getattr(self, "_last_meta_proba", None),
            regime_at_entry=getattr(self, "_current_regime", "neutral"),
            archetype_at_entry=getattr(self, "_entry_archetype", "UNKNOWN"),
        )
        self._attribution.record_execution(
            trade_id=trade_id,
            entry_type=entry_action_type,
            deferred_bars=deferred_bars,
            entry_price=float(fill_price),
            mid_price_at_signal=float(entry_price),
            entry_slippage_bps=entry_slippage_bps,
        )
        self._attribution.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=0.0,
        )
        self._attribution.record_decision_quality(
            trade_id=trade_id,
            entry_pressure_pct=getattr(self, "_entry_pressure", None),
        )

        self._scale_out_plan = None
        if self._scale_out_engine is not None:
            self._scale_out_plan = self._scale_out_engine.build_plan(
                side, float(intent.entry_price), float(intent.take_profit), tier_specs=tp_geo.scale_out_tiers
            )

    def _close_position(self, exit_price, exit_date, reason):
        fill_price = exit_price
        exit_slippage_bps = 0.0
        if self.execution_bridge is not None and self.pos_mgr.has_position():
            side = self.pos_mgr.position.side
            broker_side = "sell" if side == "long" else "buy"
            notional = self.current_value * self.pos_mgr.position_size * self.pos_mgr.exposure_multiplier
            qty = max(notional / exit_price, 1e-6)
            fill_price, exit_slippage_bps, _ = self.execution_bridge.fill_price(
                self.ticker, broker_side, qty, exit_price
            )

        trade = self.pos_mgr.close(fill_price, exit_date, reason)
        if trade is None:
            return
        trade["asset"] = self.name
        trade["conf_at_entry"] = self.position.get("confidence") if self.position else None
        trade["archetype_at_entry"] = self._entry_archetype if hasattr(self, "_entry_archetype") else "UNKNOWN"

        # Phase 6: Finalize attribution (observe, never mutate)
        trade_id = self._current_trade_id
        if trade_id:
            realized_r = trade.get("realized_r", 0.0)
            realized_return = trade.get("return", 0.0)
            realized_pnl = trade.get("pnl", 0.0)
            theoretical_r = realized_r  # best estimate from realized
            self._attribution.record_friction(
                trade_id=trade_id,
                entry_slippage_bps=getattr(self, "_last_entry_slippage", 0.0),
                exit_slippage_bps=exit_slippage_bps,
            )
            record = self._attribution.finalize(
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
                policy_hash=getattr(self, "_last_policy_hash", ""),
                archetype_version="1.0",
                exit_archetype=getattr(self, "_exit_archetype", ""),
            )
            if record is not None:
                self._attribution_buffer.append(record)
                self.flush_attribution()
                # Persist to centralized store for dashboard queries
                if self.state_store is not None:
                    try:
                        self.state_store.append_attribution(record.to_dict())
                    except Exception:
                        logger.exception("attribution: failed to persist to centralized store")
                # Enrich trade journal with MAE/MFE and attribution fields
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

            # Persist completed shadow trades to centralized store
            if self.state_store is not None:
                try:
                    shadow = getattr(self, "_shadow_sltp", None)
                    if shadow is not None:
                        completed = shadow.flush_completed(asset_name=self.name)
                        for st in completed:
                            self.state_store.append_shadow_trade(st.__dict__)
                except Exception:
                    logger.exception("shadow: failed to persist completed shadow trades")

        try:
            macro_head = getattr(self.model, "macro_head", None) if self.model else None
            if macro_head is not None and macro_head.online_weight:
                trade_ret = float(trade.get("return", 0.0))
                macro_ret, blend_ret = self._macro_blend_trade_returns(trade_ret)
                macro_head.update_weight(macro_ret, blend_ret)
        except (AttributeError, ValueError, TypeError):
            pass

        self.position = None
        if reason == "signal_flip":
            self._last_signal_flip_cycle = self._cycle_counter
        self.current_value = self.pos_mgr.current_value
        self.trade_log = list(self.pos_mgr.trade_log)
        self._save_trade_journal(trade)
        if self.state_store is not None:
            self.state_store.write_trade_outcomes_cache()
            self.state_store.write_analytics_snapshot()
        _record_exit_outcome(self.name, reason)

    def _record_stop_out(self, side: str, exit_price: float) -> None:
        if self.pos_mgr.position is not None:
            self._last_stop_out_price = self.pos_mgr.position.stop_loss
        else:
            self._last_stop_out_price = None

        if self._regime_adjusted_entry and self._last_stop_out_price is not None and self._entry_price is not None:
            sl_distance = abs(self._last_stop_out_price - self._entry_price)
            price_beyond_sl = abs(exit_price - self._last_stop_out_price)
            if sl_distance > 0 and (price_beyond_sl / sl_distance) < self._churn_ratio_threshold:
                return

        self._last_stop_out_side = side
        self._last_stop_out_date = pd.Timestamp.now(tz="UTC").normalize()
        self._cooldown_score = 1.0
        self._last_cooldown_update = pd.Timestamp.now(tz="UTC")

    def _cooldown_penalty(self, side: str) -> float:
        """Calculate decaying entry threshold penalty after a stop-out."""
        if self._last_stop_out_side != side:
            return 0.0
        if not hasattr(self, "_cooldown_score") or self._cooldown_score <= 0:
            return 0.0

        now = pd.Timestamp.now(tz="UTC")
        elapsed_hours = (now - self._last_cooldown_update).total_seconds() / 3600

        # Decay: half-life of 4 hours
        half_life = self.config.get("cooldown_half_life_hours", 4.0)
        decay = 0.5 ** (elapsed_hours / half_life)
        self._cooldown_score *= decay
        self._last_cooldown_update = now

        if self._cooldown_score < 0.05:
            self._cooldown_score = 0.0
            self._last_stop_out_side = None

        return self._cooldown_score

    def _can_enter(self, side: str, price: float, context: dict | None = None) -> tuple[bool, str]:
        """Single entry gate — pure evaluation, never mutates state.

        Returns (allowed: bool, reason: str). All entry paths MUST
        route through this gate to maintain execution singularity.
        """
        # A. Hard same-bar stop-out lock
        if self._last_stop_out_date is not None and self._last_stop_out_side == side:
            now = pd.Timestamp.now(tz="UTC")
            if self._last_stop_out_date == now.normalize():
                return False, "same_day_stopout_lock"

        # B. Cooldown penalty (soft block)
        penalty = self._cooldown_penalty(side)
        if penalty > 0:
            return False, f"cooldown_active_{penalty:.2f}"

        # C. Pending-entry conflict — no duplicate direction in queue
        if side in self._pending_entries:
            return False, "pending_entry_exists"

        # D. Signal flip cooldown — prevent churn from rapid flip-reentry
        cycles_since_flip = self._cycle_counter - self._last_signal_flip_cycle
        if cycles_since_flip < self._min_flip_interval_bars:
            return False, f"signal_flip_cooldown_{cycles_since_flip}"

        return True, "ok"

    def refresh_price(self):
        # 1. Try absolute real-time price first
        from paper_trading.ops.data_fetcher import fetch_realtime_price

        lp = fetch_realtime_price(self.ticker)
        if lp is not None:
            self.current_price = lp
            return

        # 2. Fallback to 5d download
        try:
            df = safe_download(self.ticker, period="5d", auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                close = float(df["close"].ffill().iloc[-1])
                self.current_price = None if pd.isna(close) else close
        except (OSError, ValueError, KeyError):
            logger.debug("%s: fallback price download failed", self.name)

    def train(self, force=False):
        self._training.train(force=force)

    def generate_signal(self, threshold=0.45):
        return self._inference.generate_signal(threshold)

    def _apply_decision(self, decision: TradeDecision, df):
        today = decision.timestamp
        self._cycle_counter += 1
        current_side = self.pos_mgr.current_side()

        # Phase 6: Store prediction metadata for attribution at close
        self._last_label = decision.label
        self._last_confidence = decision.confidence
        self._last_prob_long = decision.prob_long
        self._last_prob_short = decision.prob_short
        self._last_prob_neutral = decision.prob_neutral
        self._entry_archetype = decision.archetype
        self._entry_pressure = None  # set by EntryOptimizer if available

        # Phase 6: Track MAE/MFE extremes while position is open
        if self.pos_mgr.has_position() and self._current_trade_id:
            try:
                high_val = float(df["high"].iloc[-1])
                low_val = float(df["low"].iloc[-1])
                if hasattr(self, "_bars_at_entry"):
                    self._attribution.update_trade_extremes(
                        self._current_trade_id, high_val, low_val, self._bars_at_entry
                    )
            except (KeyError, IndexError, ValueError, TypeError):
                pass
        new_side = (
            PositionSide.LONG
            if decision.signal == SignalType.BUY
            else PositionSide.SHORT
            if decision.signal == SignalType.SELL
            else None
        )

        # Minimum confidence gate — skip low-confidence entries
        min_conf = self.config.get("min_confidence", 0.0)
        if new_side and decision.confidence < min_conf:
            logger.debug("%s: skipping trade, confidence %.1f%% < min %.1f%%", self.name, decision.confidence, min_conf)
            new_side = None

        # Meta-label advisory (sizing handles suppression via _meta_size_multiplier)
        if (
            new_side
            and self._meta_label_model is not None
            and self.config.get("meta_labeling", {}).get("enabled", False)
            and hasattr(self, "_last_meta_proba")
            and self._last_meta_proba is not None
            and self._last_meta_proba < self._meta_label_model.threshold
        ):
            logger.info(
                "%s: meta-label below threshold (p(TP>SL)=%.2f < %.2f) — sizing will suppress",
                self.name,
                self._last_meta_proba,
                self._meta_label_model.threshold,
            )
            # new_side remains set; _meta_size_multiplier returns 0.0
            # which flows through _composite_size_scalar → zero notional

        if new_side != current_side:
            if self.pos_mgr.has_position():
                self._close_position(decision.close_price, today, "signal_flip")
            if new_side:
                ok, reason = self._can_enter(
                    new_side,
                    decision.close_price,
                    {"regime": getattr(self, "_current_regime", "neutral")},
                )
                if not ok:
                    logger.info(
                        "%s: entry gate blocking %s entry — %s",
                        self.name,
                        new_side,
                        reason,
                    )
                    new_side = None

                if new_side:
                    # 1. Gather Phase 1-3 Artifacts
                    structure = self._structure_detector.detect(df)
                    entry_action = self._entry_optimizer.evaluate(
                        decision.signal, decision.archetype, structure, self.config.get("entry_optimization", {})
                    )

                    tp_geo = None
                    deferred_entry = None

                    if entry_action == EntryAction.ENTER:
                        # Pre-calculate SL distance for TP compiler
                        # We use a simplified vol-based estimate here; _open_position will do the final physics.
                        vol = self._tb_vol(df["close"]) if hasattr(self, "_tb_vol") else 0.01
                        # Use SL mult from config
                        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
                        geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})
                        curr_sl_mult = (
                            self.sl_mult
                            * geom.get("sl_mult", 1.0)
                            * self.governance._narrative_sl_mult
                            * self.governance._liquidity_sl_mult
                        )
                        sl_dist = decision.close_price * vol * curr_sl_mult

                        from paper_trading.entry.tp_compiler import compute_take_profit

                        tp_geo = compute_take_profit(
                            decision.close_price, sl_dist, state, decision.archetype, structure
                        )

                    elif entry_action == EntryAction.DEFER:
                        from paper_trading.entry.deferred_entry import DeferredEntry

                        deferred_entry = DeferredEntry.from_decision(
                            decision, max_bars=self.config.get("entry_defer_max_bars", 5)
                        )

                    # 2. Unified Policy Routing (Phase 4)
                    policy_dec = self._execution_policy.handle(
                        entry_action, decision, decision.archetype, structure, tp_geo=tp_geo, deferred=deferred_entry
                    )
                    self._last_policy_hash = str(
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

                    # 3. Execute Policy Action
                    if policy_dec.action == EntryAction.ENTER:
                        logger.info(f"{self.name}: POLICY APPROVED ENTER ({policy_dec.reason})")
                        # Pass exit_plan to _open_position
                        self._open_position(new_side, decision.close_price, today, df, tp_geo=policy_dec.exit_plan)
                        if self.position is not None:
                            self.position["confidence"] = decision.confidence
                            self.position["policy_reason"] = policy_dec.reason

                    elif policy_dec.action == EntryAction.DEFER:
                        if policy_dec.entry_plan:
                            self._pending_entries[new_side.value] = policy_dec.entry_plan
                            logger.info(f"{self.name}: POLICY APPROVED DEFER ({policy_dec.reason})")

                    else:
                        logger.info(f"{self.name}: POLICY APPROVED SKIP ({policy_dec.reason})")

        # Bar-by-bar polling for deferred entries
        self._poll_pending_entries(df)

        self.prob_history.append(
            {
                "date": today,
                "prob_long": round(decision.prob_long * 100, 2),
                "prob_short": round(decision.prob_short * 100, 2),
                "signal": decision.signal,
                "confidence": decision.confidence,
                "close_price": decision.close_price,
            }
        )
        MAX_PROB_HISTORY = 1000
        if len(self.prob_history) > MAX_PROB_HISTORY:
            self.prob_history = self.prob_history[-MAX_PROB_HISTORY:]
        self._log_confidence_buckets()

    def _poll_pending_entries(self, df: pd.DataFrame) -> None:
        """Evaluates pending entries against current market structure."""
        if not self._pending_entries:
            return

        to_remove = []
        structure = self._structure_detector.detect(df)
        today = str(pd.Timestamp.now(tz=ET).date())

        for direction, entry in self._pending_entries.items():
            if not entry.is_active:
                to_remove.append(direction)
                continue

            entry.update()
            if entry.status == DeferredEntryStatus.EXPIRED:
                to_remove.append(direction)
                continue

            # Re-evaluate timing with optimizer (Phase 1)
            entry_action = self._entry_optimizer.evaluate(
                entry.decision.signal, entry.decision.archetype, structure, self.config.get("entry_optimization", {})
            )

            tp_geo = None
            if entry_action == EntryAction.ENTER:
                # Pre-calculate SL distance for triggered entry
                vol = self._tb_vol(df)
                state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
                geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})
                curr_sl_mult = (
                    self.sl_mult
                    * geom.get("sl_mult", 1.0)
                    * self.governance._narrative_sl_mult
                    * self.governance._liquidity_sl_mult
                )
                sl_dist = float(df["close"].iloc[-1]) * vol * curr_sl_mult

                from paper_trading.entry.tp_compiler import compute_take_profit

                tp_geo = compute_take_profit(
                    float(df["close"].iloc[-1]), sl_dist, state, entry.decision.archetype, structure
                )

            # Unified Policy Routing (Phase 4)
            policy_dec = self._execution_policy.handle(
                entry_action, entry.decision, entry.decision.archetype, structure, tp_geo=tp_geo, deferred=entry
            )
            self._last_policy_hash = str(
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
            self._entry_archetype = entry.decision.archetype

            if policy_dec.action == EntryAction.ENTER:
                side = PositionSide(direction)
                ok, reason = self._can_enter(
                    side,
                    float(df["close"].iloc[-1]),
                    {"regime": getattr(self, "_current_regime", "neutral")},
                )
                if not ok:
                    logger.info(
                        "%s: entry gate blocking deferred %s entry — %s",
                        self.name,
                        direction,
                        reason,
                    )
                    entry.cancel(reason=reason)
                    to_remove.append(direction)
                    continue
                logger.info(f"{self.name}: TRIGGERING deferred {direction} entry (Policy: {policy_dec.reason})")
                entry.trigger(float(df["close"].iloc[-1]))
                self._open_position(side, entry.decision.close_price, today, df, tp_geo=policy_dec.exit_plan)
                if self.position is not None:
                    self.position["confidence"] = entry.decision.confidence
                    self.position["policy_reason"] = policy_dec.reason
                entry.close()
                to_remove.append(direction)

            elif policy_dec.action == EntryAction.SKIP:
                logger.info(f"{self.name}: CANCELLING deferred {direction} entry (Policy: {policy_dec.reason})")
                entry.cancel(reason=policy_dec.reason)
                to_remove.append(direction)

        for direction in to_remove:
            del self._pending_entries[direction]

    def _decision_to_dict(self, decision: TradeDecision):
        pos = self.pos_mgr.position
        macro_weight = None
        macro_head = getattr(self.model, "macro_head", None) if self.model else None
        if macro_head is not None:
            macro_weight = round(float(getattr(macro_head, "current_weight", 0.45)), 4)

        return {
            "asset": self.name,
            "signal": decision.signal,
            "confidence": decision.confidence,
            "archetype": decision.archetype,
            "macro_weight": macro_weight,
            "close_price": decision.close_price,
            "date": decision.timestamp,
            "label": decision.label,
            "position": (
                {
                    "side": pos.side if pos else None,
                    "entry": round(pos.entry_price, 4) if pos else None,
                    "sl": round(pos.stop_loss, 4) if pos else None,
                    "tp": round(pos.take_profit, 4) if pos else None,
                    "current_pnl": (round(self._position_pnl(decision.close_price), 4) if pos else None),
                }
                if pos
                else None
            ),
        }

    def _position_pnl(self, current_price):
        return self.pos_mgr.position_pnl(current_price)

    def _ensure_position_synced(self):
        if self.position is not None and not self.pos_mgr.has_position():
            intent = PositionIntent(
                side=PositionSide(self.position["side"]),
                entry_price=self.position["entry"],
                entry_date=self.position.get("entry_date", ""),
                stop_loss=self.position["sl"],
                take_profit=self.position["tp"],
                vol=self.position.get("vol", 0.01),
            )
            self.pos_mgr.open(intent)

    def update_pnl(self):
        self._pnl.update_pnl()

    @property
    def mtm_value(self) -> float:
        return self._pnl.mtm_value

    def get_metrics(self):
        self._ensure_position_synced()
        cv = self.current_value if not pd.isna(self.current_value) else self.initial_capital
        pv = self.peak_value if not pd.isna(self.peak_value) else cv
        dd = (cv - pv) / pv if pv > 0 else 0
        total_return = (cv - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        monthly_pfs = []
        if self.trade_log:
            td = pd.DataFrame(self.trade_log)
            td["month"] = pd.to_datetime(td["exit_date"]).dt.to_period("M")
            for m, g in td.groupby("month"):
                profits = g[g["pnl"] > 0]["pnl"].sum()
                losses = abs(g[g["pnl"] < 0]["pnl"].sum())
                monthly_pfs.append({"month": str(m), "pf": profits / losses if losses > 0 else float("inf")})
        monthly_pf = monthly_pfs[-1]["pf"] if monthly_pfs else None

        total_profits = sum(t["pnl"] for t in self.trade_log if t["pnl"] > 0)
        total_losses = abs(sum(t["pnl"] for t in self.trade_log if t["pnl"] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float("inf") if total_profits > 0 else 0)

        win_rate = len([t for t in self.trade_log if t["pnl"] > 0]) / len(self.trade_log) if self.trade_log else 0
        sc = {"BUY": 0, "SELL": 0, "FLAT": 0}
        for p in self.prob_history:
            sc[p["signal"]] = sc.get(p["signal"], 0) + 1
        mean_conf = np.mean([p["confidence"] for p in self.prob_history]) if self.prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if self.pos_mgr.has_position():
            upnl = (
                self._position_pnl(self.current_price)
                if self.current_price is not None and not pd.isna(self.current_price)
                else 0.0
            )
            pos_info = {
                "side": self.pos_mgr.position.side,
                "entry": round(self.pos_mgr.position.entry_price, 4),
                "sl": round(self.pos_mgr.position.stop_loss, 4),
                "tp": round(self.pos_mgr.position.take_profit, 4),
                "current_vol": round(self.pos_mgr.position.vol, 6),
                "unrealized_pnl": round(upnl, 2),
                "sl_mult": self.position.get("sl_mult") if self.position else None,
                "tp_mult": self.position.get("tp_mult") if self.position else None,
            }

        mtm_val = self.mtm_value
        mtm_return = (mtm_val - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

        mean_pl = np.mean([p["prob_long"] for p in self.prob_history]) if self.prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p["prob_short"] for p in self.prob_history]) if self.prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        # Exit reason rates from trade_log (paper trading)
        exit_reasons = {}
        if self.trade_log:
            reasons = [t.get("reason", "unknown") for t in self.trade_log]
            n = len(reasons)
            exit_reasons = {
                "tp_rate": round(reasons.count("tp") / n, 4),
                "sl_rate": round(reasons.count("sl") / n, 4),
                "signal_flip_rate": round(reasons.count("signal_flip") / n, 4),
                "avg_r": round(np.mean([t.get("realized_r", 0) for t in self.trade_log]), 4),
            }

        # Stratified metrics by archetype (from attribution data)
        archetype_stats = {}
        if self.trade_log:
            for t in self.trade_log:
                arch = t.get("archetype_at_entry", "UNKNOWN")
                if arch not in archetype_stats:
                    archetype_stats[arch] = {"n": 0, "wins": 0, "total_r": 0.0, "sl": 0, "tp": 0}
                archetype_stats[arch]["n"] += 1
                if t.get("pnl", 0) > 0:
                    archetype_stats[arch]["wins"] += 1
                archetype_stats[arch]["total_r"] += t.get("realized_r", 0)
                if t.get("reason") == "sl":
                    archetype_stats[arch]["sl"] += 1
                elif t.get("reason") == "tp":
                    archetype_stats[arch]["tp"] += 1
        archetype_stats = {
            k: {
                "n": v["n"],
                "win_rate": round(v["wins"] / v["n"], 4) if v["n"] > 0 else 0,
                "avg_r": round(v["total_r"] / v["n"], 4) if v["n"] > 0 else 0,
                "sl_rate": round(v["sl"] / v["n"], 4) if v["n"] > 0 else 0,
                "tp_rate": round(v["tp"] / v["n"], 4) if v["n"] > 0 else 0,
            }
            for k, v in sorted(archetype_stats.items())
        }

        # Current regime-based geometry (multipliers applied to base)
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})
        current_sl = self.sl_mult * geom.get("sl_mult", 1.0)
        current_tp = self.tp_mult * geom.get("tp_mult", 1.0)

        meta_inference = None
        if self._meta_label_model is not None and self._last_meta_proba is not None:
            meta_inference = {
                "meta_confidence": round(self._last_meta_proba, 4),
                "meta_decision": "ENTER" if self._meta_label_model.should_enter(self._last_meta_proba) else "BLOCK",
            }

        remaining_frac = self.pos_mgr.get_remaining_fraction()
        scale_out_active = (
            self.pos_mgr._scale_out_active
            if hasattr(self.pos_mgr, "_scale_out_active") and self.pos_mgr._scale_out_active
            else False
        )

        # Scale-out tier info for dashboard
        scale_out_tiers = None
        if self._scale_out_plan is not None:
            scale_out_tiers = [
                {
                    "fraction": t.fraction,
                    "price": t.price,
                    "filled": t.filled,
                    "fill_price": t.fill_price,
                }
                for t in self._scale_out_plan.tiers
            ]

        _psi = self._last_psi_drift
        return {
            "asset": self.name,
            "current_value": round(mtm_val, 2),
            "settled_value": round(self.current_value, 2),
            "mtm_value": round(mtm_val, 2),
            "total_return": round(mtm_return, 2),
            "settled_return": round(total_return * 100, 2),
            "mtm_return": round(mtm_return, 2),
            "drawdown": round(dd * 100, 2),
            "profit_factor": round(pf, 2),
            "win_rate": round(win_rate * 100, 2),
            "n_trades": len(self.trade_log),
            "n_signals": len(self.prob_history),
            "signal_distribution": sc,
            "mean_confidence": round(float(mean_conf), 2),
            "mean_prob_long": round(float(mean_pl), 2),
            "mean_prob_short": round(float(mean_ps), 2),
            "current_price": round(self.current_price, 4) if self.current_price else None,
            "last_signal_date": str(self.last_signal_date.date()) if self.last_signal_date else None,
            "monthly_pf": round(float(monthly_pf), 2) if monthly_pf else None,
            "position": pos_info,
            "current_sl_mult": round(current_sl, 4),
            "current_tp_mult": round(current_tp, 4),
            "trade_log": self.trade_log[-10:],
            "feature_stability": {
                "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
                "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
                "penalty": self._last_stability.penalty if self._last_stability else 0.0,
                "window_id": self._last_stability.window_id if self._last_stability else None,
            },
            "exit_reasons": exit_reasons,
            "archetype_stats": archetype_stats,
            "meta_inference": meta_inference,
            "scale_out_active": scale_out_active,
            "remaining_fraction": round(remaining_frac, 4),
            "scale_out_tiers": scale_out_tiers,
            "psi_drift": {
                "per_feature": [
                    {
                        "feature": e.feature,
                        "psi": e.psi,
                        "classification": e.classification,
                        "trend": e.trend,
                        "importance_score": e.importance_score,
                    }
                    for e in (_psi.per_feature if _psi else [])
                ],
                "worst_classification": _psi.worst_classification if _psi else "NO_DRIFT",
                "moderate_count": _psi.moderate_count if _psi else 0,
                "severe_count": _psi.severe_count if _psi else 0,
                "psi_ok": _psi.psi_ok if _psi else True,
                "penalty": _psi.penalty if _psi else 0.0,
            },
        }

    def _save_trade_journal(self, trade):
        if self.state_store is not None:
            self.state_store.append_trade(trade)

    def _log_confidence_buckets(self):
        bucket = {"asset": self.name, "date": str(datetime.now(tz=ET).date())}
        for p in self.prob_history[-20:]:
            conf = p["confidence"]
            bucket.setdefault(f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}", 0)
            bucket[f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}"] += 1
        bucket["mean_conf"] = np.mean([p["confidence"] for p in self.prob_history[-20:]]) if self.prob_history else 0
        bucket["n_signals"] = min(20, len(self.prob_history))
        if self.state_store is not None:
            self.state_store.append_confidence_bucket(bucket)

    def update_validity(self, halt: dict | None = None):
        halt = self.check_halt_conditions() if halt is None else halt
        score = 0.80
        if not halt["drawdown_ok"]:
            score -= 0.25
        if not halt["monthly_pf_ok"]:
            score -= 0.20
        if not halt["drought_ok"]:
            score -= 0.15
        if not halt["drift_ok"]:
            score -= 0.15
        if not halt.get("liquidity_ok", True):
            score -= 0.10

        if self._last_stability is not None:
            penalty = self._last_stability.penalty
            if penalty < 0:
                logger.info(
                    "%s stability penalty: %.3f (jaccard=%.3f, spearman=%.3f)",
                    self.name,
                    penalty,
                    self._last_stability.jaccard_top_10,
                    self._last_stability.spearman_rank_corr,
                )
                score += penalty

        if self._last_psi_drift is not None and self._last_psi_drift.penalty < 0:
            psi_p = self._last_psi_drift.penalty
            logger.info(
                "%s PSI drift penalty: %.3f (worst=%s, moderate=%d, severe=%d)",
                self.name,
                psi_p,
                self._last_psi_drift.worst_classification,
                self._last_psi_drift.moderate_count,
                self._last_psi_drift.severe_count,
            )
            score += psi_p

        score = max(0.0, min(1.0, score))
        result = self.validity_sm.transition(score, pd.Timestamp.now(tz=ET))
        result["feature_stability"] = {
            "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
            "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
            "penalty_applied": self._last_stability.penalty if self._last_stability else 0.0,
        }
        result["psi_drift"] = {
            "worst_classification": self._last_psi_drift.worst_classification if self._last_psi_drift else "NO_DRIFT",
            "moderate_count": self._last_psi_drift.moderate_count if self._last_psi_drift else 0,
            "severe_count": self._last_psi_drift.severe_count if self._last_psi_drift else 0,
            "penalty_applied": self._last_psi_drift.penalty if self._last_psi_drift else 0.0,
        }
        return result

    def check_halt_conditions(self, metrics: dict | None = None):
        metrics = self.get_metrics() if metrics is None else metrics
        dd = metrics.get("drawdown", 0) / 100
        if pd.isna(dd):
            dd = 0
        hc = self.halt_config
        hard_reasons = []
        soft_warnings = []
        if dd <= hc["drawdown"]:
            hard_reasons.append(f"DD {metrics['drawdown']:.1f}% <= {hc['drawdown'] * 100:.0f}%")
        mpf = metrics.get("monthly_pf")
        if mpf is not None and not pd.isna(mpf) and mpf < hc["monthly_pf"]:
            hard_reasons.append(f"PF {mpf:.2f} < {hc['monthly_pf']:.2f}")
        drought_ok = True
        drought_days = hc.get("signal_drought", 30)
        if self.last_signal_date is not None:
            days_since = (datetime.now(tz=ET).date() - pd.Timestamp(self.last_signal_date).date()).days
            if days_since > drought_days:
                hard_reasons.append(f"Signal drought: {days_since}d > {drought_days}d")
                drought_ok = False
        drift_ok = True
        if len(self.prob_history) >= 3:
            prob_drift_limit = hc.get("prob_drift", 0.25)
            mean_conf = metrics.get("mean_confidence", 0) / 100
            if pd.isna(mean_conf):
                mean_conf = 0
            drift = abs(mean_conf - self.expected_prob_conf)
            if drift > prob_drift_limit:
                hard_reasons.append(f"Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}")
                drift_ok = False

        narrative_ok = True
        narr_warnings = self.governance.narrative_warnings()
        if narr_warnings:
            soft_warnings.extend(narr_warnings)

        liquidity_ok = True
        liq_warnings = self.governance.liquidity_warnings()
        if liq_warnings:
            hard_reasons.extend(liq_warnings)
            if self.governance._liquidity_halted:
                liquidity_ok = False

        psi_ok = True
        if self._last_psi_drift is not None and not self._last_psi_drift.psi_ok:
            hard_reasons.append(
                f"PSI drift SEVERE on {self._last_psi_drift.severe_count} features "
                f"(worst={self._last_psi_drift.worst_classification})"
            )
            psi_ok = False

        halted = len(hard_reasons) > 0
        return {
            "halted": halted,
            "reasons": [*hard_reasons, *soft_warnings],
            "hard_reasons": hard_reasons,
            "soft_warnings": soft_warnings,
            "drawdown_ok": dd > hc["drawdown"],
            "monthly_pf_ok": mpf is None or pd.isna(mpf) or mpf >= hc["monthly_pf"],
            "drought_ok": drought_ok,
            "drift_ok": drift_ok,
            "narrative_ok": narrative_ok,
            "liquidity_ok": liquidity_ok,
            "psi_ok": psi_ok,
        }

    def set_capital_base(self, new_base: float) -> None:
        self._pnl.set_capital_base(new_base)
