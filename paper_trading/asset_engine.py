import hashlib
import logging
import os
import time
from datetime import datetime

import pandas as pd
import pytz

from features.archetypes import ArchetypeClassifier
from features.market_structure import MarketStructureDetector
from monitoring.importance_tracker import ImportanceStore
from monitoring.psi_monitor import PSIMonitor
from monitoring.validity_state_machine import ValidityStateMachine as _ValidityStateMachine
from paper_trading.asset_pnl_controller import AssetPnlController
from paper_trading.attribution.collector import AttributionCollector
from paper_trading.compat import (
    ExecutionContext,
    GovernanceService,
    MetricsService,
    SignalService,
    evaluate_regime_conviction_gate,
    run_decision_pipeline,
)
from paper_trading.config_manager import get_config  # noqa: F401  (patched by tests)
from paper_trading.entry.decision import TradeDecision
from paper_trading.entry.optimizer import EntryOptimizer
from paper_trading.entry.policy import ExecutionPolicyLayer
from paper_trading.governance.asset import AssetGovernance
from paper_trading.governance.regime import RegimeClassifier
from paper_trading.inference.pipeline import AssetInferencePipeline
from paper_trading.inference.training import AssetTrainingPipeline
from paper_trading.ops.data_fetcher import flatten
from paper_trading.ops.tracer import trace_exit
from paper_trading.position.dynamic_sltp import DynamicSLTPEngine, build_dynamic_sltp_from_config
from paper_trading.position.manager import PositionManager
from paper_trading.position.scale_out import build_scale_out_from_config
from paper_trading.services.attribution_service import AttributionService as _AttributionService
from paper_trading.services.entry_service import EntryService
from paper_trading.services.position_service import PositionService
from paper_trading.shadow.engine import ShadowSLTPEngine
from paper_trading.state_store import _SKIP_JOURNAL
from shared.registry import StrategyRegistry

logger = logging.getLogger("quantforge.asset_engine")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        journal_path=None,
        sl_mult=1.0,
        tp_mult=2.5,
        max_depth=2,
        regime_geometry=None,
        initial_capital=None,
        position_size=None,
        retrain_window=None,
        context=None,
        wal_writer=None,
    ):
        ctx = context or ExecutionContext()
        engine_cfg = ctx.get_engine_config()
        self._engine_cfg = engine_cfg

        # ── Core identity ────────────────────────────────────────────
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        self.config = config or {}
        self.halt_config = halt_config or dict(engine_cfg.halt)
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.max_depth = max_depth
        self.regime_geometry = regime_geometry or {}

        # ── Capital & position management ────────────────────────────
        self.initial_capital = initial_capital if initial_capital is not None else engine_cfg.capital * allocation
        self.capital_base = self.initial_capital
        self.peak_value = self.initial_capital
        self.current_value = self.initial_capital
        self.pos_mgr = PositionManager(
            self.initial_capital,
            position_size if position_size is not None else engine_cfg.position_size,
        )

        # ── Runtime state ────────────────────────────────────────────
        self.start_time = datetime.now(tz=ET)
        self.model = None
        self.signal_data = None
        self.last_signal_date = None
        self.current_price = None
        self.position = None
        self.trades = []
        self.trade_log = []
        self.prob_history = []
        self._trained = False
        self._cycle_counter: int = 0
        self._research_mode = engine_cfg.research_mode
        self._retrain_window = retrain_window if retrain_window is not None else engine_cfg.retrain_window
        self.model_path = os.path.join(BASE, "paper_trading", "models", f"{contract.name}_model.json")
        self._wal_writer = wal_writer
        self._model_hash = self._load_model_hash()

        # ── Infrastructure dependencies ──────────────────────────────
        self.execution_bridge = ctx.get_execution_bridge()
        self.state_store = ctx.get_state_store()
        if journal_path is _SKIP_JOURNAL:
            self.state_store = None
        self._market_data = ctx.get_market_data_service()
        self._setup_registry_strategies()

        # ── Monitoring & governance ──────────────────────────────────
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._importance_store = ImportanceStore(base_dir)
        self._psi_monitor = PSIMonitor(base_dir)
        self.regime_classifier = RegimeClassifier()
        self.validity_sm = _ValidityStateMachine()
        self.governance = AssetGovernance(self.name, self.config, self.halt_config)
        self.governance.load_narrative_state()
        self.governance.load_liquidity_state(getattr(self, "price_data", None))
        self._setup_shadow_sltp()

        # ── SL/TP & entry machinery ──────────────────────────────────
        self._sltp_engine = build_dynamic_sltp_from_config(self.config)
        self._scale_out_engine = build_scale_out_from_config(self.config)
        self._scale_out_plan = None
        self._entry = EntryService()
        self._entry_optimizer = EntryOptimizer()
        self._execution_policy = ExecutionPolicyLayer()
        self._structure_detector = MarketStructureDetector()
        self._archetype_classifier = ArchetypeClassifier()
        self._pending_entries: dict[str, object] = {}
        self._deferred_entry = None

        # ── Working state for entry/exit logic ───────────────────────
        self._entry_price: float | None = None
        self._entry_vol = None
        self._entry_signal_dir: int = 0
        self._entry_archetype = "UNKNOWN"
        self._entry_pressure = None
        self._entry_validity_state = "YELLOW"
        self._bars_at_entry = 0
        self._last_adjust_bar = 0
        self._initial_sl = None
        self._initial_tp = None
        self._last_entry_slippage = 0.0
        self._last_policy_hash = ""
        self._regime_adjusted_entry = False
        self._cooldown_score = 0.0
        self._last_cooldown_update_cycle = -999
        self._last_stop_out_side = None
        self._last_stop_out_cycle = -999
        self._last_stop_out_price = None
        self._last_signal_flip_cycle = -self.config.get("min_flip_interval_bars", 3) * 2
        self._min_flip_interval_bars = self.config.get("min_flip_interval_bars", 3)
        self._churn_ratio_threshold = self.config.get("churn_ratio_threshold", 0.50)
        self._initial_settlement_done = False

        # ── MT5 orphan cleanup ────────────────────────────────────────
        self._mt5_cleanup_queue: list[tuple[str, int]] = []
        self._mt5_cleanup_retries: int = 0

        # ── Spread gate state ───────────────────────────────────────────
        self._last_spread_bps: float | None = None
        self._last_spread_time: float = 0.0
        self._spread_tier: str = self.config.get("spread_tier", "fx_cross")

        # ── Inference & training state ───────────────────────────────
        self._last_feature_vector: dict[str, float] | None = None
        self._last_feature_hash: str = ""
        self._last_feature_schema: list[str] | None = None
        self._last_label = None
        self._last_confidence = 0.0
        self._last_prob_long = 0.0
        self._last_prob_short = 0.0
        self._last_prob_neutral = 0.0
        self._last_meta_proba = None
        self._last_macro_dir = None
        self._last_blend_dir = None
        self._last_regime_row = None
        self._regime_bar_counter = 0
        self._last_regime_label = None
        self._current_regime = "neutral"
        self._alpha_feature_cols = None
        self.regime_feature_names = []
        self._ensemble = None
        self._regime_model = None
        self._meta_label_model = None
        self._ensemble_breakdown = {}
        self._window_id_counter = 0
        self._current_window_train_start = ""
        self._current_window_train_end = ""
        self._last_stability = None
        self._last_psi_drift = None
        self._last_gates_trace: dict[str, bool] | None = None
        self._last_sizing_chain: dict[str, float] | None = None
        self._truncate_inference = False
        self._psi_drift_initialized = False
        self._signal_chain: list = []
        self._last_bar_count: int | None = None
        self._suppress_until: float = 0.0

        # ── Regime raw output logging ───────────────────────────────────
        self._last_regime_raw_probas: tuple[float, float] | None = None  # (P_SHORT, P_LONG)
        self._last_regime_long_prob: float | None = None
        self._last_regime_features: dict[str, float] | None = None  # regime input feature values

        # ── Shadow engine ────────────────────────────────────────────
        self._shadow_sltp = None
        self._risk_signal = None
        self._shadow_action = None
        self._shadow_drift_intel = None
        self._shadow_learning = None

        # ── Attribution ──────────────────────────────────────────────
        self._attribution = AttributionCollector()
        self._experiment_id = ""
        self._attribution_export_dir = None
        self._current_trade_id = None
        self._attribution_buffer = []

        # ── Sub-pipelines (training, inference, PnL, position) ──────
        self._training = AssetTrainingPipeline(self)
        self._pnl = AssetPnlController(self)
        self._inference = AssetInferencePipeline(self)
        self._position = self._build_position_service()

    # ── Internal setup helpers ──────────────────────────────────────

    def _setup_registry_strategies(self) -> None:
        self._reg = StrategyRegistry.get_instance()
        self._model_iface = self._reg.get_model(self.name)
        self._signal_strategy = self._reg.get_signal(self.name)
        self._sizing_strategy = self._reg.get_sizing(self.name)
        self._pnl_strategy = self._reg.get_pnl(self.name)
        self._feature_pipeline = self._reg.get_features(self.name)
        if self.config.get("regime_sizing"):
            self._sizing_strategy.regime_aware = True

    def _setup_shadow_sltp(self) -> None:
        self._shadow_sltp: ShadowSLTPEngine | None = None
        shadow_cfg = self.config.get("shadow_sltp", {})
        if shadow_cfg.get("enabled", False):
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
        else:
            self._shadow_sltp = None

    def _build_position_service(self) -> PositionService:
        return PositionService(
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

    def _load_model_hash(self) -> str:
        hash_path = self.model_path.replace(".json", "_hash.txt")
        if os.path.exists(hash_path):
            with open(hash_path) as f:
                return f.read().strip()
        if os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        return "unknown"

    def set_experiment_context(self, experiment_id: str, export_dir: str | None = None) -> None:
        self._attribution_export_dir = _AttributionService.set_experiment_context(
            attribution_export_dir=self._attribution_export_dir,
            experiment_id=experiment_id,
            export_dir=export_dir,
        )
        self._experiment_id = experiment_id

    def flush_attribution(self) -> None:
        _AttributionService.flush_attribution(
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
        return SignalService.meta_size_multiplier(self.config, getattr(self, "_last_meta_proba", None))

    def _drawdown_taper(self) -> float:
        return self._entry.drawdown_taper(
            getattr(self, "_cycle_drawdown_pct", 0.0),
            start_dd=self.config.get("size_taper_start_dd", -0.05),
            end_dd=self.config.get("size_taper_end_dd", -0.15),
            min_size=self.config.get("size_taper_min", 0.50),
        )

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
            drawdown_taper=self._drawdown_taper(),
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
        self._meta_label_model = SignalService.load_meta_label_model(self.config, self.name)

    def _tb_vol(self, close_series):
        return self._entry.tb_vol(close_series)

    def _open_position(self, side, entry_price, entry_date, df=None, tp_geo=None):
        self._entry.open_position(side, entry_price, entry_date, self, df, tp_geo)

    def _close_position(self, exit_price, exit_date, reason) -> bool:
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
            return False
        self.position = mutations.get("position", self.position)
        self.current_value = mutations.get("current_value", self.current_value)
        self.trade_log = mutations.get("trade_log", self.trade_log)
        if "last_signal_flip_cycle" in mutations:
            self._last_signal_flip_cycle = mutations["last_signal_flip_cycle"]
        trade = mutations.get("trade", {})
        trace_exit(
            asset=self.name,
            exit_price=exit_price,
            reason=reason,
            realized_r=float(trade.get("realized_r", 0)),
            bars_held=int(trade.get("bars", 0)),
            regime_long_prob=self._last_regime_long_prob,
            regime_short_prob=(
                round(float(self._last_regime_raw_probas[0]), 6) if self._last_regime_raw_probas is not None else None
            ),
            regime_label=(
                self._last_regime_row.regime_label if getattr(self, "_last_regime_row", None) is not None else None
            ),
            regime_features=self._last_regime_features,
        )
        return True

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
        gate_cfg = self._engine_cfg.optimizations.get("regime_conviction_flip_gate", {})
        if not gate_cfg.get("enabled", False):
            return True, "gate_disabled"
        _conf = getattr(self, "_last_confidence", 0.0)
        return evaluate_regime_conviction_gate(
            regime_row=self._last_regime_row,
            model_confidence=_conf,
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

    def refresh_spread(self) -> None:
        """Fetch current spread from MT5 and store on asset.

        This is called every cycle from the inference pipeline.  If the MT5
        bridge is unavailable the spread is left at its previous value (the
        staleness check in the spread gate will catch stale data).
        """
        broker = getattr(self.execution_bridge, "broker", None)
        if broker is None:
            return
        client = getattr(broker, "_client", None)
        if client is None:
            return
        try:
            spread_bps = client.realtime_spread(self.ticker)
            if spread_bps is not None:
                self._last_spread_bps = spread_bps
                self._last_spread_time = time.time()
        except Exception:
            logger.debug("%s: refresh_spread failed", self.name, exc_info=True)

    def train(self, force=False):
        self._training.train(force=force)

    def generate_signal(self, threshold=0.45):
        halt = self.check_halt_conditions()
        if halt.get("halted", False):
            logger.info("%s: skip signal generation — asset halted", self.name)
            return None
        return self._inference.generate_signal(threshold)

    def _apply_decision(self, decision: TradeDecision, df):
        self._cycle_counter += 1
        self._last_final_signal = run_decision_pipeline(self, decision, df)

    def _poll_pending_entries(self, df: pd.DataFrame) -> None:
        self._entry.poll_pending_entries(df, self)

    def _decision_to_dict(self, decision: TradeDecision, final_signal: str | None = None):
        return MetricsService.decision_to_dict(
            decision,
            pos_mgr=self.pos_mgr,
            model=self.model,
            name=self.name,
            final_signal=final_signal,
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
        MetricsService.log_confidence_buckets(
            name=self.name,
            prob_history=self.prob_history,
            state_store=self.state_store,
        )

    def update_validity(self, halt: dict | None = None):
        return GovernanceService.update_validity(
            name=self.name,
            halt=halt,
            check_halt_conditions=self.check_halt_conditions,
            validity_sm=self.validity_sm,
            last_stability=self._last_stability,
            last_psi_drift=self._last_psi_drift,
        )

    def check_halt_conditions(self, metrics: dict | None = None):
        return GovernanceService.check_halt_conditions(
            get_metrics=(lambda: metrics if metrics is not None else self.get_metrics()),
            name=self.name,
            halt_config=self.halt_config,
            last_signal_date=self.last_signal_date,
            prob_history=self.prob_history,
            governance=self.governance,
            last_psi_drift=self._last_psi_drift,
        )

    def set_capital_base(self, new_base: float) -> None:
        self._pnl.set_capital_base(new_base)
