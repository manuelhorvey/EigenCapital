import logging
import os
from datetime import datetime

import pandas as pd
import pytz

from monitoring.importance_tracker import ImportanceStore, StabilityResult
from monitoring.psi_monitor import PSIMonitor, PSISnapshot
from monitoring.validity_state_machine import ValidityStateMachine as _ValidityStateMachine
from paper_trading.asset_pnl_controller import AssetPnlController
from paper_trading.attribution.collector import AttributionCollector, TradeAttributionRecord
from paper_trading.config_manager import get_config
from paper_trading.entry.decision import EntryAction, PositionSide, SignalType, TradeDecision
from paper_trading.governance.asset import AssetGovernance
from paper_trading.governance.conviction_gate import RegimeRow
from paper_trading.governance.multipliers import compute_effective_multipliers
from paper_trading.governance.regime import RegimeClassifier
from paper_trading.inference.pipeline import AssetInferencePipeline
from paper_trading.inference.training import AssetTrainingPipeline
from paper_trading.ops.data_fetcher import flatten
from paper_trading.ops.market_data_service import get_market_data_service
from paper_trading.position.dynamic_sltp import DynamicSLTPEngine, build_dynamic_sltp_from_config
from paper_trading.position.manager import PositionManager
from paper_trading.position.scale_out import build_scale_out_from_config
from paper_trading.services.entry_service import EntryService
from paper_trading.services.position_service import PositionService
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
        max_depth=2,
        regime_geometry=None,
        initial_capital=None,
        position_size=None,
        retrain_window=None,
        execution_bridge=None,
        market_data_service=None,
        engine_config=None,
    ):
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        engine_cfg = engine_config or get_config()
        self._engine_cfg = engine_cfg
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
        self.model_path = os.path.join(BASE, "paper_trading", "models", f"{contract.name}_model.json")
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
        self.max_depth = max_depth
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
        self._last_regime_row: RegimeRow | None = None
        self._regime_bar_counter: int = 0
        self._last_regime_label: str | None = None
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
        self._last_stop_out_cycle: int = -999
        self._last_stop_out_price: float | None = None
        self._cooldown_score: float = 0.0
        self._last_cooldown_update_cycle: int = -999
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
        self._entry = EntryService()
        self._attribution = AttributionCollector()
        from paper_trading.services.attribution_service import AttributionService as _AttributionService

        self._position = PositionService(
            name=self.name,
            ticker=self.ticker,
            config=self.config,
            pos_mgr=self.pos_mgr,
            state_store=self.state_store,
            attribution=self._attribution,
            attribution_svc=_AttributionService,
            execution_bridge=self.execution_bridge,
            model=self.model,
            shadow_sltp=self._shadow_sltp,
        )
        self._market_data = market_data_service or get_market_data_service()
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
        from paper_trading.services.attribution_service import AttributionService

        self._attribution_export_dir = AttributionService.set_experiment_context(
            attribution_export_dir=self._attribution_export_dir,
            experiment_id=experiment_id,
            export_dir=export_dir,
        )
        self._experiment_id = experiment_id

    def flush_attribution(self) -> None:
        from paper_trading.services.attribution_service import AttributionService

        AttributionService.flush_attribution(
            name=self.name,
            attribution_buffer=self._attribution_buffer,
            attribution_export_dir=self._attribution_export_dir,
            experiment_id=self._experiment_id,
        )

    def set_narrative_state(self, narr) -> None:
        self.governance.set_narrative_state(narr)

    def _refresh_liquidity(self, df) -> None:
        self.governance.refresh_liquidity(df)

    def _effective_capital(self) -> float:
        return self._entry.effective_capital(
            initial_capital=self.initial_capital,
            capital_base=self.capital_base,
            current_value=self.current_value,
        )

    def _meta_size_multiplier(self) -> float:
        from paper_trading.services.signal_service import SignalService

        return SignalService.meta_size_multiplier(self.config, getattr(self, "_last_meta_proba", None))

    def _composite_size_scalar(self, extra_scalar: float = 1.0) -> float:
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        return self._entry.composite_size_scalar(
            extra_scalar,
            validity_state=state,
            sl_mult=self.sl_mult,
            tp_mult=self.tp_mult,
            regime_geometry=self.regime_geometry,
            governance=self.governance,
            pos_mgr=self.pos_mgr,
            meta_size_multiplier=self._meta_size_multiplier(),
        )

    def _compute_notional(self, extra_scalar: float = 1.0) -> float:
        effective = self._effective_capital()
        size_scalar = self._composite_size_scalar(extra_scalar)
        return self._entry.compute_notional(effective, size_scalar)

    def _sizing_config(self, close: pd.Series, position_size_scalar: float = 1.0) -> dict:
        effective = self._effective_capital()
        size_scalar = self._composite_size_scalar(position_size_scalar)
        return self._entry.sizing_config(
            close,
            position_size_scalar,
            execution_bridge=self.execution_bridge,
            ticker=self.ticker,
            config=self.config,
            effective_capital_val=effective,
            size_scalar_val=size_scalar,
        )

    def _macro_blend_trade_returns(self, trade_ret: float) -> tuple[float, float]:
        return self._position.macro_blend_trade_returns(
            trade_ret,
            entry_signal_dir=self._entry_signal_dir,
            last_macro_dir=self._last_macro_dir,
            last_blend_dir=self._last_blend_dir,
        )

    def _enable_adaptive_macro(self) -> None:
        if not self.config.get("adaptive_macro") or self.model is None:
            return
        macro_head = getattr(self.model, "macro_head", None)
        if macro_head is not None:
            macro_head.online_weight = True

    def _load_meta_label_model(self) -> None:
        from paper_trading.services.signal_service import SignalService

        self._meta_label_model = SignalService.load_meta_label_model(self.config, self.name)

    def _tb_vol(self, close_series):
        return self._entry.tb_vol(close_series)

    def _open_position(self, side, entry_price, entry_date, df=None, tp_geo=None):
        self._entry.open_position(side, entry_price, entry_date, self, df, tp_geo)

    def _close_position(self, exit_price, exit_date, reason):
        mutations = self._position.close_position(
            exit_price,
            exit_date,
            reason,
            position=self.position,
            current_value=self.current_value,
            entry_archetype=getattr(self, "_entry_archetype", None),
            current_trade_id=self._current_trade_id,
            attribution_buffer=self._attribution_buffer,
            cycle_counter=self._cycle_counter,
            last_entry_slippage=getattr(self, "_last_entry_slippage", 0.0),
            last_policy_hash=getattr(self, "_last_policy_hash", ""),
            exit_archetype=getattr(self, "_exit_archetype", ""),
            attribution_export_dir=self._attribution_export_dir,
            experiment_id=self._experiment_id,
            entry_signal_dir=self._entry_signal_dir,
            last_macro_dir=self._last_macro_dir,
            last_blend_dir=self._last_blend_dir,
        )
        if not mutations:
            return
        self.position = mutations.get("position", self.position)
        self.current_value = mutations.get("current_value", self.current_value)
        self.trade_log = mutations.get("trade_log", self.trade_log)
        if "last_signal_flip_cycle" in mutations:
            self._last_signal_flip_cycle = mutations["last_signal_flip_cycle"]

    def _record_stop_out(self, side: str, exit_price: float) -> None:
        mutations = self._position.record_stop_out(
            side,
            exit_price,
            pos_mgr=self.pos_mgr,
            regime_adjusted_entry=self._regime_adjusted_entry,
            entry_price=self._entry_price,
            churn_ratio_threshold=self._churn_ratio_threshold,
            cycle_counter=self._cycle_counter,
        )
        if not mutations:
            return
        self._last_stop_out_price = mutations["_last_stop_out_price"]
        self._last_stop_out_side = mutations["_last_stop_out_side"]
        self._last_stop_out_cycle = mutations["_last_stop_out_cycle"]
        self._cooldown_score = mutations["_cooldown_score"]
        self._last_cooldown_update_cycle = mutations["_last_cooldown_update_cycle"]

    def _cooldown_penalty(self, side: str) -> float:
        new_score = self._position.cooldown_penalty(
            side,
            last_stop_out_side=self._last_stop_out_side,
            cooldown_score=self._cooldown_score,
            last_cooldown_update_cycle=self._last_cooldown_update_cycle,
            config=self.config,
            cycle_counter=self._cycle_counter,
        )
        self._cooldown_score = new_score
        self._last_cooldown_update_cycle = self._cycle_counter
        if new_score < 0.05:
            self._last_stop_out_side = None
        return self._cooldown_score

    def _can_enter(self, side: str, price: float, context: dict | None = None) -> tuple[bool, str]:
        return self._entry.can_enter(
            side,
            price,
            last_stop_out_cycle=self._last_stop_out_cycle,
            last_stop_out_side=self._last_stop_out_side,
            config=self.config,
            cooldown_penalty_func=self._cooldown_penalty,
            pending_entries=self._pending_entries,
            cycle_counter=self._cycle_counter,
            last_signal_flip_cycle=self._last_signal_flip_cycle,
            min_flip_interval_bars=self._min_flip_interval_bars,
            context=context,
        )

    def _evaluate_flip_gate(self) -> tuple[bool, str]:
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate

        gate_cfg = self.config.get("optimizations", {}).get("regime_conviction_flip_gate", {})
        if not gate_cfg.get("enabled", False):
            return True, "gate_disabled"
        return evaluate_regime_conviction_gate(
            regime_row=self._last_regime_row,
            model_confidence=getattr(self, "_last_confidence", 0.0),
            bars_in_current_regime=self._regime_bar_counter,
            regime_margin_threshold=gate_cfg.get("regime_margin_threshold", 0.35),
            confidence_threshold=gate_cfg.get("confidence_threshold", 0.50),
            min_bars_in_regime=gate_cfg.get("min_bars_in_regime", 3),
        )

    def refresh_price(self):
        # 1. Try real-time price first
        lp = self._market_data.get_realtime_price(self.ticker)
        if lp is not None:
            self.current_price = lp
            return

        # 2. Fallback to 5d download
        try:
            df = self._market_data.get_historical(self.ticker, period="5d", auto_adjust=True, progress=False)
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
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.debug("MAE/MFE tracking skipped for %s: %s", self.name, e)
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

        # Regime bar counter (used by conviction flip gate)
        current_regime = getattr(self, "_current_regime", "neutral")
        if current_regime != self._last_regime_label:
            self._regime_bar_counter = 1
            self._last_regime_label = current_regime
        else:
            self._regime_bar_counter += 1

        # Conviction gate — only flip if regime is decisive and model is uncertain
        flip_allowed = True
        if new_side != current_side and self.pos_mgr.has_position():
            flip_allowed, flip_reason = self._evaluate_flip_gate()
            if not flip_allowed:
                logger.info("%s: flip blocked by conviction gate — %s", self.name, flip_reason)

        if new_side != current_side:
            if self.pos_mgr.has_position() and flip_allowed:
                self._close_position(decision.close_price, today, "signal_flip")
            if new_side and flip_allowed:
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
                        vol = self._tb_vol(df["close"]) if hasattr(self, "_tb_vol") else 0.01
                        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
                        curr_sl_mult, _, _ = compute_effective_multipliers(
                            base_sl=self.sl_mult,
                            base_tp=self.tp_mult,
                            validity_state=state,
                            regime_geometry=self.regime_geometry,
                            narrative_sl_mult=self.governance._narrative_sl_mult,
                            liquidity_sl_mult=self.governance._liquidity_sl_mult,
                            narrative_size_scalar=self.governance._narrative_size_scalar,
                            liquidity_size_scalar=self.governance._liquidity_size_scalar,
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
        self._entry.poll_pending_entries(df, self)

    def _decision_to_dict(self, decision: TradeDecision):
        from paper_trading.services.metrics_service import MetricsService

        return MetricsService.decision_to_dict(
            decision,
            pos_mgr=self.pos_mgr,
            model=self.model,
            name=self.name,
        )

    def _ensure_position_synced(self):
        self._position.ensure_position_synced(
            position=self.position,
            pos_mgr=self.pos_mgr,
        )

    def update_pnl(self):
        self._pnl.update_pnl()

    @property
    def mtm_value(self) -> float:
        return self._pnl.mtm_value

    def get_metrics(self):
        from paper_trading.services.metrics_service import MetricsService

        return MetricsService.get_metrics(
            name=self.name,
            ensure_position_synced=self._ensure_position_synced,
            pos_mgr=self.pos_mgr,
            current_value=self.current_value,
            peak_value=self.peak_value,
            initial_capital=self.initial_capital,
            model=self.model,
            trade_log=self.trade_log,
            prob_history=self.prob_history,
            last_signal_date=self.last_signal_date,
            validity_sm=self.validity_sm,
            sl_mult=self.sl_mult,
            tp_mult=self.tp_mult,
            regime_geometry=self.regime_geometry,
            governance=self.governance,
            current_price=self.current_price,
            position=self.position,
            _meta_label_model=getattr(self, "_meta_label_model", None),
            _last_meta_proba=getattr(self, "_last_meta_proba", None),
            _scale_out_plan=self._scale_out_plan,
            _last_stability=self._last_stability,
            _last_psi_drift=self._last_psi_drift,
            mtm_value=self.mtm_value,
        )

    def _log_confidence_buckets(self):
        from paper_trading.services.metrics_service import MetricsService

        MetricsService.log_confidence_buckets(
            name=self.name,
            prob_history=self.prob_history,
            state_store=self.state_store,
        )

    def update_validity(self, halt: dict | None = None):
        from paper_trading.services.governance_service import GovernanceService

        return GovernanceService.update_validity(
            name=self.name,
            halt=halt,
            check_halt_conditions=self.check_halt_conditions,
            validity_sm=self.validity_sm,
            last_stability=self._last_stability,
            last_psi_drift=self._last_psi_drift,
        )

    def check_halt_conditions(self, metrics: dict | None = None):
        from paper_trading.services.governance_service import GovernanceService

        return GovernanceService.check_halt_conditions(
            get_metrics=(lambda: metrics if metrics is not None else self.get_metrics()),
            name=self.name,
            halt_config=self.halt_config,
            last_signal_date=self.last_signal_date,
            prob_history=self.prob_history,
            expected_prob_conf=self.expected_prob_conf,
            governance=self.governance,
            last_psi_drift=self._last_psi_drift,
        )

    def set_capital_base(self, new_base: float) -> None:
        self._pnl.set_capital_base(new_base)
