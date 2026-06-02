import logging
import os
import statistics
import time
from datetime import datetime
from enum import Enum

import pytz
from dotenv import load_dotenv

from paper_trading.asset_engine import AssetEngine
from paper_trading.config_manager import get_config
from paper_trading.execution.bridge import ExecutionBridge
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.governance.risk import reset as _reset_risk_governance

# Re-exported from child modules for backward compatibility
from paper_trading.ops.data_fetcher import (  # noqa: F401
    _cache_path,
    fetch_history,
    fetch_live,
    fetch_ref,
    flatten,
    norm_index,
    safe_download,
)
from paper_trading.ops.experiment_context import ExperimentContext
from paper_trading.ops.market_hours import is_market_closed
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator
from paper_trading.replay.wal import WalWriter
from paper_trading.services.engine_narrative_service import EngineNarrativeService
from paper_trading.services.engine_rebalance_service import EngineRebalanceService
from paper_trading.services.engine_recovery_service import EngineRecoveryService
from paper_trading.services.engine_state_service import EngineStateService
from paper_trading.state_store import _SKIP_JOURNAL, StateStore, sanitize  # noqa: F401
from shared.execution_config import build_execution_configs
from shared.registry import StrategyRegistry

load_dotenv()


class ExecutionState(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


ET = pytz.timezone("US/Eastern")

logger = logging.getLogger("quantforge.engine")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)
STATE_PATH = _STORE.state_path
CACHE_DIR = _STORE.cache_dir
LOG_PATH = os.path.join(BASE, "data", "live", "engine.log")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

os.makedirs(MODEL_DIR, exist_ok=True)


class PaperTradingEngine:
    def __init__(self, state_store=None, wal_writer=None, config=None):
        from tools.import_guard import verify_feature_pipeline

        report = verify_feature_pipeline()
        if report["status"] != "CLEAN":
            logger.warning(
                "Import firewall: %d forbidden module(s) loaded — %s",
                len(report["forbidden_modules_loaded"]),
                ", ".join(report["forbidden_modules_loaded"]),
            )

        self.state_store = state_store or _STORE
        self.assets = {}
        self.start_date = datetime.now(tz=ET)
        self.last_update = None
        self.portfolio_peak_value: float | None = None
        self._wal = wal_writer or WalWriter(BASE, source="engine")

        # Reset global risk governance state to prevent stale data from
        # a previous session leaking into the new run.
        _reset_risk_governance()

        snapshot = self.state_store.load_snapshot()
        if snapshot is not None and snapshot.engine_status:
            self.start_date = datetime.fromisoformat(
                snapshot.engine_status.get("start_time", self.start_date.isoformat())
            )
        saved_positions = (snapshot.open_positions or {}) if snapshot else {}

        cfg = config or get_config()
        self._engine_cfg = cfg
        self.execution_configs = build_execution_configs(cfg.assets, defaults=cfg.execution_defaults)
        self.broker = PaperBroker(
            initial_capital=cfg.capital,
            execution_configs=self.execution_configs,
        )
        self.execution_bridge = ExecutionBridge(self.broker)

        self._narrative = EngineNarrativeService(self)
        self._rebalance = EngineRebalanceService(self)
        self._recovery = EngineRecoveryService(self)
        self._state = EngineStateService(self)

        self._build_asset_registry()
        self._init_experiment_context()
        self._narrative.init_narrative()
        self._recovery.restore_positions(saved_positions)
        from paper_trading.ops.simulation_snapshot import SimulationStore

        self._sim_store = SimulationStore(BASE)
        self._rebalance_last_day: datetime | None = None
        self._rebalance_weights: dict[str, float] = {}

        # Rebalance target day: 0 = Monday (weekly narrative sync)
        self._rebalance_dow: int = 0

        self._cycle_times: list[float] = []
        self._cycle_times_maxlen = 1000
        self._cycle_count: int = 0
        self._mtm_cache_value: float | None = None
        self._mtm_cache_cycle: int = -1

        # Fault-isolated actor orchestrator (Phase 5)
        self._orchestrator = EngineOrchestrator(
            actors={name: AssetActor(name, asset, wal_writer=self._wal) for name, asset in self.assets.items()},
            wal_writer=self._wal,
        )

    def _build_asset_registry(self) -> None:
        from paper_trading.portfolio_builder import build_paper_portfolio as _build_paper_portfolio

        portfolio = _build_paper_portfolio(self._engine_cfg.halt)
        _reg = StrategyRegistry.get_instance()
        _reg.register_defaults(list(portfolio.keys()))
        for name, spec in portfolio.items():
            self.assets[name] = AssetEngine(
                spec["ticker"],
                name,
                spec["contract"],
                spec["alloc"],
                halt_config=spec["halt"],
                config=spec["config"],
                sl_mult=spec.get("sl_mult", 1.0),
                tp_mult=spec.get("tp_mult", 2.5),
                regime_geometry=spec.get("regime_geometry", {}),
                state_store=self.state_store,
                execution_bridge=self.execution_bridge,
            )

    def _init_experiment_context(self) -> None:
        """Initialize pipeline freeze and stamp attribution context on all assets."""
        universe = tuple(sorted(self.assets.keys()))
        ctx = ExperimentContext.initialize(
            asset_universe=universe,
            execution_config=self._engine_cfg.execution_defaults,
        )
        export_dir = os.path.join(BASE, "data", "research", "attribution")
        for name, asset in self.assets.items():
            asset.set_experiment_context(ctx.freeze.experiment_id, export_dir=export_dir)
        logger.info(
            "experiment: initialized experiment_id=%s (%d assets, %d components frozen)",
            ctx.freeze.experiment_id,
            len(self.assets),
            len(ctx.freeze.component_hashes),
        )

    def __getattr__(self, name):
        if name in ("_narrative", "_rebalance", "_recovery", "_state"):
            mod_map = {
                "_narrative": ("paper_trading.services.engine_narrative_service", "EngineNarrativeService"),
                "_rebalance": ("paper_trading.services.engine_rebalance_service", "EngineRebalanceService"),
                "_recovery": ("paper_trading.services.engine_recovery_service", "EngineRecoveryService"),
                "_state": ("paper_trading.services.engine_state_service", "EngineStateService"),
            }
            mod_path, cls_name = mod_map[name]
            import importlib

            mod = importlib.import_module(mod_path)
            svc = getattr(mod, cls_name)(self)
            object.__setattr__(self, name, svc)
            return svc
        if name == "_rebalance_weights":
            object.__setattr__(self, name, {})
            return {}
        if name == "_rebalance_dow":
            object.__setattr__(self, name, 0)
            return 0
        if name == "_rebalance_last_day":
            object.__setattr__(self, name, None)
            return None
        if name == "_sim_store":
            from paper_trading.ops.simulation_snapshot import SimulationStore

            svc = SimulationStore(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: F823
            object.__setattr__(self, name, svc)
            return svc
        if name == "_cycle_times":
            object.__setattr__(self, name, [])
            return []
        if name == "_cycle_times_maxlen":
            object.__setattr__(self, name, 1000)
            return 1000
        if name == "_cycle_count":
            object.__setattr__(self, name, 0)
            return 0
        if name == "_mtm_cache_value":
            object.__setattr__(self, name, None)
            return None
        if name == "_mtm_cache_cycle":
            object.__setattr__(self, name, -1)
            return -1
        if name == "_narrative_api_key":
            import os

            key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
            object.__setattr__(self, name, key)
            return key
        if name == "state_store":
            object.__setattr__(self, name, None)
            return None
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _refresh_narrative(self) -> bool:
        return self._narrative._refresh_narrative()

    def _should_rebalance(self) -> bool:
        return self._rebalance.should_rebalance()

    def _rebalance_portfolio(self) -> None:
        self._rebalance.rebalance_portfolio()

    def _detect_crisis_regime(self) -> bool:
        return self._rebalance.detect_crisis_regime()

    def _compute_mtm_total(self) -> float:
        return self._state.compute_mtm_total()

    def get_state(self) -> dict:
        return self._state.get_state()

    def save_state(self):
        return self._state.save_state()

    def initialize(self):
        from features.registry import ASSET_LABEL_PARAMS

        for name, asset in self.assets.items():
            registry_params = ASSET_LABEL_PARAMS.get(name)
            if registry_params is not None and (
                asset.sl_mult != registry_params["sl"] or asset.tp_mult != registry_params["pt"]
            ):
                logger.warning(
                    "%s: runtime exit (sl=%.2f,tp=%.2f) != "
                    "training label params (sl=%.2f,pt=%.2f) — "
                    "asymmetric exits OK, but monitor ΔSharpe impact",
                    name,
                    asset.sl_mult,
                    asset.tp_mult,
                    registry_params["sl"],
                    registry_params["pt"],
                )
            try:
                asset.train(force=True)
                logger.info("%s: training done", name)
            except Exception as e:
                logger.error("%s: training FAILED - %s", name, e)

    def _compute_mtm_total(self) -> float:
        if not hasattr(self, "_cycle_count"):
            self._cycle_count = 0
            self._mtm_cache_value = None
            self._mtm_cache_cycle = -1
        elif not hasattr(self, "_mtm_cache_value"):
            self._mtm_cache_value = None
            self._mtm_cache_cycle = -1
        if self._mtm_cache_value is not None and self._mtm_cache_cycle == self._cycle_count:
            return self._mtm_cache_value
        mtm = sum(a.mtm_value for a in self.assets.values())
        self._mtm_cache_value = mtm
        self._mtm_cache_cycle = self._cycle_count
        return mtm

    def run_once(self):
        _t0 = time.perf_counter()
        self._cycle_count += 1

        if is_market_closed():
            logger.debug("Market closed — core assets skipped")
            return {}

        # Pipeline integrity check (Phase 7 prelude)
        ctx = ExperimentContext.get()
        if ctx is not None:
            changes = ctx.check_integrity()
            if changes:
                logger.warning(
                    "experiment: %d component(s) changed during experiment %s — attribution data may degrade",
                    len(changes),
                    ctx.freeze.experiment_id,
                )

        pd_limit = self._engine_cfg.portfolio_drawdown_limit
        results: dict[str, object] = {}

        # ── Portfolio drawdown check (BEFORE any new trading) ────────
        mtm = self._compute_mtm_total()
        if self.portfolio_peak_value is None or mtm > self.portfolio_peak_value:
            self.portfolio_peak_value = mtm
        portfolio_dd = (
            (mtm - self.portfolio_peak_value) / self.portfolio_peak_value
            if self.portfolio_peak_value and self.portfolio_peak_value > 0
            else 0.0
        )

        if pd_limit is not None and portfolio_dd <= pd_limit:
            logger.warning(
                "PORTFOLIO CIRCUIT BREAKER: drawdown %.2f%% <= %.2f%% limit — closing all positions",
                portfolio_dd * 100,
                pd_limit * 100,
            )
            for name, asset in self.assets.items():
                if asset.pos_mgr.has_position():
                    asset._close_position(
                        asset.current_price,
                        str(datetime.now(tz=ET).date()),
                        "portfolio_circuit_breaker",
                    )
            results["circuit_breaker"] = {
                "triggered": True,
                "portfolio_drawdown": round(portfolio_dd * 100, 2),
                "limit": round(pd_limit * 100, 2),
            }
            self._wal.write(
                "state_committed",
                {
                    "circuit_breaker": results["circuit_breaker"],
                    "portfolio_drawdown": round(portfolio_dd * 100, 2),
                },
            )
            self.last_update = datetime.now(tz=ET)
            return results

        # ── Fault-isolated asset execution via orchestrator ──────────
        # Replaces Phases 1 (refresh+pnl), 3 (signal), 4 (validity).
        # Each asset runs in its own actor; no single failure halts others.
        orch_results = self._orchestrator.run_once()

        # Propagate orchestrator health snapshot to results
        if orch_results.get("health"):
            results["orchestrator_health"] = orch_results["health"]

        # Extract per-asset signals (backward-compat: {name: signal_dict})
        asset_results = orch_results.get("assets", {})
        for name, sig in asset_results.items():
            if isinstance(sig, dict):
                results[name] = sig

        # Check orchestrator-level emergency halt
        if orch_results.get("circuit_breaker"):
            logger.error("Orchestrator circuit breaker triggered — actor halt ratio exceeded threshold")
            results["orchestrator_circuit_breaker"] = orch_results["circuit_breaker"]

        # Drain all actor persist queues into engine persist buffer
        persist_commands = self._orchestrator.drain_persist_buffer()
        for cmd in persist_commands:
            if cmd["kind"] == "signal":
                pass  # signals already captured in results
            # Future: route trades, snapshots, attribution to state store

        _t1 = time.perf_counter()

        # ── Narrative refresh ──────────────────────────────────────────
        self._refresh_narrative()

        _t2 = time.perf_counter()

        # ── Periodic risk-parity rebalance ─────────────────────────────
        if self._should_rebalance():
            self._rebalance_portfolio()

        _t3 = time.perf_counter()

        # ── WAL: engine-level state committed ──────────────────────────
        self._wal.write(
            "state_committed",
            {
                "assets": {name: {"has_position": a.pos_mgr.has_position()} for name, a in self.assets.items()},
                "last_update": str(self.last_update),
            },
        )

        self.last_update = datetime.now(tz=ET)

        # ── Cycle benchmark ───────────────────────────────────────────
        _elapsed = time.perf_counter() - _t0
        self._cycle_times.append(_elapsed)
        if len(self._cycle_times) > self._cycle_times_maxlen:
            self._cycle_times = self._cycle_times[-self._cycle_times_maxlen :]
        _orch_time = _t1 - _t0
        _narr_time = _t2 - _t1
        _rebal_time = _t3 - _t2
        if len(self._cycle_times) % 20 == 0:
            recent = self._cycle_times[-100:]
            p50 = statistics.median(recent)
            p95 = sorted(recent)[int(len(recent) * 0.95)]
            logger.info(
                "BENCHMARK: cycle=%.3fs  orch=%.3fs  narr=%.3fs  rebal=%.3fs  p50=%.3fs  p95=%.3fs  n=%d",
                _elapsed,
                _orch_time,
                _narr_time,
                _rebal_time,
                p50,
                p95,
                len(recent),
            )

        return results
