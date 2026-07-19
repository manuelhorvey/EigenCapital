"""Factory for constructing fully-wired AssetEngine instances.

Encapsulates the object graph wiring that was previously inlined
in AssetEngine.__init__ (171 lines). Each subsystem is constructed
with explicit defaults and injected dependencies.
"""

from __future__ import annotations

from __future__ import annotations

import logging
from pathlib import Path

import pytz

from features.archetypes import ArchetypeClassifier
from features.market_structure import MarketStructureDetector
from monitoring.importance_tracker import ImportanceStore
from monitoring.psi_monitor import PSIMonitor
from monitoring.validity_state_machine import ValidityStateMachine as _ValidityStateMachine
from paper_trading.asset_engine import AssetEngine
from paper_trading.asset_pnl_controller import AssetPnlController
from paper_trading.attribution.collector import AttributionCollector
from paper_trading.entry.optimizer import EntryOptimizer
from paper_trading.entry.policy import ExecutionPolicyLayer
from paper_trading.governance.asset import AssetGovernance
from paper_trading.inference.pipeline import AssetInferencePipeline
from paper_trading.inference.training import AssetTrainingPipeline
from paper_trading.position.dynamic_sltp import DynamicSLTPEngine, build_dynamic_sltp_from_config
from paper_trading.position.manager import PositionManager
from paper_trading.position.scale_out import build_scale_out_from_config
from paper_trading.services.attribution_service import AttributionService
from paper_trading.services.entry_service import EntryService
from paper_trading.services.position_service import PositionService
from paper_trading.shadow.engine import ShadowSLTPEngine
from shared.registry import StrategyRegistry

logger = logging.getLogger("eigencapital.asset_engine_factory")

ET = pytz.timezone("US/Eastern")
BASE = Path(__file__).resolve().parent.parent


def build_asset_engine(
    ticker: str,
    name: str,
    contract,
    allocation: float,
    halt_config: dict | None = None,
    config: dict | None = None,
    journal_path: str | None = None,
    sl_mult: float = 1.0,
    tp_mult: float = 2.5,
    max_depth: int = 2,
    regime_geometry: dict | None = None,
    initial_capital: float | None = None,
    position_size: float | None = None,
    retrain_window: int | None = None,
    context=None,
) -> AssetEngine:
    from paper_trading.execution_context import ExecutionContext

    ctx = context or ExecutionContext()
    engine_cfg = ctx.get_engine_config()
    resolved_initial_cap = initial_capital if initial_capital is not None else engine_cfg.capital * allocation  # type: ignore[union-attr]

    engine = AssetEngine(
        ticker=ticker,
        name=name,
        contract=contract,
        allocation=allocation,
        halt_config=halt_config,
        config=config,
        journal_path=journal_path,
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        max_depth=max_depth,
        regime_geometry=regime_geometry,
        initial_capital=resolved_initial_cap,
        position_size=position_size,
        retrain_window=retrain_window,
        context=ctx,
    )

    # ── Post-init wiring (moved from __init__) ──────────────────────────

    engine.model_path = str(BASE / "paper_trading" / "models" / f"{contract.name}_model.json")
    engine.pos_mgr = PositionManager(
        resolved_initial_cap,
        position_size if position_size is not None else engine_cfg.position_size,  # type: ignore[union-attr]
    )
    engine.validity_sm = _ValidityStateMachine()
    reg = getattr(engine, "_reg", None) or StrategyRegistry.get_instance()
    engine._reg = reg
    engine._model_iface = reg.get_model(engine.name)
    engine._signal_strategy = reg.get_signal(engine.name)
    engine._sizing_strategy = reg.get_sizing(engine.name)
    engine._pnl_strategy = reg.get_pnl(engine.name)
    engine._feature_pipeline = reg.get_features(engine.name)
    engine._importance_store = ImportanceStore(BASE)
    engine._psi_monitor = PSIMonitor(BASE)
    engine._sltp_engine = build_dynamic_sltp_from_config(engine.config)
    engine._scale_out_engine = build_scale_out_from_config(engine.config)

    if engine.config.get("regime_sizing"):
        engine._sizing_strategy.regime_aware = True

    # Shadow SL/TP engine (optional)
    engine._shadow_sltp = _build_shadow_sltp(engine.config)

    # Governance
    engine.governance = AssetGovernance(engine.name, engine.config, engine.halt_config)
    engine.governance.load_narrative_state()
    engine.governance.load_liquidity_state(getattr(engine, "price_data", None))

    # Service layer
    engine._attribution = AttributionCollector()
    engine._entry = EntryService()
    engine._position = PositionService(
        name=engine.name,
        ticker=engine.ticker,
        config=engine.config,
        pos_mgr=engine.pos_mgr,
        state_store=engine.state_store,
        attribution=engine._attribution,
        attribution_svc=AttributionService,
        execution_bridge=engine.execution_bridge,
        model=engine.model,
        shadow_sltp=engine._shadow_sltp,
    )
    # Inference & training pipelines
    engine._training = AssetTrainingPipeline(engine)
    engine._pnl = AssetPnlController(engine)
    engine._inference = AssetInferencePipeline(engine)

    # Entry artifacts pipeline
    engine._archetype_classifier = ArchetypeClassifier()
    engine._structure_detector = MarketStructureDetector()
    engine._entry_optimizer = EntryOptimizer()
    engine._execution_policy = ExecutionPolicyLayer()

    return engine


def _build_shadow_sltp(config: dict) -> ShadowSLTPEngine | None:
    if not config.get("shadow_sltp", {}).get("enabled", False):
        return None
    shadow_cfg = config.get("shadow_sltp", {})
    alt_engine = DynamicSLTPEngine(
        method=shadow_cfg.get("method", "atr"),
        atr_period=shadow_cfg.get("atr_period", config.get("dynamic_sltp", {}).get("atr_period", 14)),
        atr_mult_sl=shadow_cfg.get("atr_mult_sl", 2.5),
        atr_mult_tp=shadow_cfg.get("atr_mult_tp", 2.0),
        min_rr_ratio=shadow_cfg.get("min_rr_ratio", 1.2),
        trailing_activation_mult=shadow_cfg.get("trailing_activation_mult", 1.0),
        trailing_distance_mult=shadow_cfg.get("trailing_distance_mult", 1.5),
        confidence_sl_adjust=shadow_cfg.get("confidence_sl_adjust", 0.3),
    )
    return ShadowSLTPEngine(
        name=shadow_cfg.get("name", "tight_trail"),
        alt_engine=alt_engine,
    )
