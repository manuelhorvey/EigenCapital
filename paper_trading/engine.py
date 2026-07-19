import logging
import os
from pathlib import Path
import time
from datetime import datetime
from enum import Enum

import pytz
from dotenv import load_dotenv

# Re-exported from child modules for backward compatibility
from paper_trading.alerting.manager import setup_alerting_from_config
from paper_trading.asset_engine import AssetEngine  # noqa: F401
from paper_trading.config_manager import get_config
from paper_trading.execution.bridge import ExecutionBridge
from paper_trading.execution.mt5_broker import MT5Broker  # noqa: F401  (re-exported for backward compat)
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution_context import ExecutionContext
from paper_trading.factories.broker_factory import BrokerFactory
from paper_trading.logging.correlation import CorrelationIdFilter
from paper_trading.logging.json_formatter import install_json_logging
from paper_trading.observability.resource_monitor import get_resource_monitor
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
from paper_trading.ops.simulation_snapshot import SimulationStore
from paper_trading.orchestrator._engine import EngineOrchestrator
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.replay.wal import WalWriter
from paper_trading.services.asset_registry_service import AssetRegistryService
from paper_trading.services.benchmark_service import BenchmarkService
from paper_trading.services.data_retention_service import DataRetentionService
from paper_trading.services.engine_initialize_service import EngineInitializeService
from paper_trading.services.engine_narrative_service import EngineNarrativeService
from paper_trading.services.engine_rebalance_service import EngineRebalanceService
from paper_trading.services.engine_recovery_service import EngineRecoveryService
from paper_trading.services.engine_state_service import EngineStateService
from paper_trading.services.full_panel_service import FullPanelService
from paper_trading.services.model_integrity_service import ModelIntegrityService
from paper_trading.services.snapshot_restorer import SnapshotRestorer
from paper_trading.state_store import _SKIP_JOURNAL, StateStore, sanitize  # noqa: F401
from paper_trading.writer import BackgroundWriter
from shared.execution_config import build_execution_configs

load_dotenv()


class ExecutionState(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


ET = pytz.timezone("US/Eastern")


# ── Logging setup ────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    """Configure structured logging with file rotation and correlation IDs.

    Replaces the legacy ``logging.basicConfig()`` default with:
      - RotatingFileHandler (10 MB, 5 backups) for durable capture
      - StreamHandler for stdout (JSON format, for log aggregators)
      - CorrelationIdFilter on all handlers
    """
    root = logging.getLogger("eigencapital")
    root.setLevel(logging.INFO)

    log_dir = str(Path(__file__).resolve().parent.parent / "data" / "live")
    log_path = str(Path(log_dir) / "engine.log")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # File handler with rotation (10 MB per file, keep 5 backups)
    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s")
    )
    file_handler.addFilter(CorrelationIdFilter())
    root.addHandler(file_handler)

    # JSON stream handler for aggregators (stdout)
    json_handler = install_json_logging(logger=root, level=logging.INFO, replace=False)
    json_handler.addFilter(CorrelationIdFilter())

    # Ensure only one set of handlers is active
    logger = logging.getLogger("eigencapital.engine")
    return logger


logger = _setup_logging()

BASE = str(Path(__file__).resolve().parent.parent)
_LIVE_DIR = str(Path(BASE) / "data" / "live")
STATE_PATH = str(Path(_LIVE_DIR) / "state.json")
CACHE_DIR = str(Path(_LIVE_DIR) / "cache")
LOG_PATH = str(Path(_LIVE_DIR) / "engine.log")  # backward compat
MODEL_DIR = str(Path(__file__).resolve().parent / "models")

Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)

# Backward-compat: _STORE was eagerly created here; now None unless explicitly set.
_STORE: StateStore | None = None


def _set_module_store(store: StateStore | None) -> None:
    """Set the module-level _STORE for backward compat with scripts that import
    ``paper_trading.engine._STORE``. Call once at engine startup."""
    global _STORE
    _STORE = store


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

        self.state_store = state_store or StateStore(BASE)
        _set_module_store(self.state_store)
        # Wire the store into data_fetcher for cache operations
        from paper_trading.ops.data_fetcher import _set_store as _set_df_store

        _set_df_store(self.state_store)
        self.assets = {}
        self.start_date = datetime.now(tz=ET)
        self.last_update = None
        self.portfolio_peak_value: float | None = None
        self._wal = wal_writer or WalWriter(BASE, source="engine")

        snapshot = self.state_store.load_snapshot()

        self._snapshot_restorer = SnapshotRestorer(self)
        saved_positions = self._snapshot_restorer.restore(snapshot)

        cfg = config or get_config()
        self._engine_cfg = cfg
        self.execution_configs = build_execution_configs(cfg.assets, defaults=cfg.execution_defaults)

        # Initialize alerting channels from config
        try:
            setup_alerting_from_config(cfg)
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            logger.debug("Alerting setup skipped (no config section or invalid)", exc_info=True)

        if cfg.mt5.enabled:
            self.broker = BrokerFactory.create_mt5_broker(cfg)
            # Wire WAL writer into broker for MT5 order lifecycle events
            if hasattr(self.broker, "set_wal_writer"):
                self.broker.set_wal_writer(self._wal)
            is_real_broker = True
            # Install MT5 client as global data provider for data_fetcher
            BrokerFactory.install_mt5_data_provider(cfg)
            # Populate broker's MT5 connection pool before first cycle so
            # refresh_spread() in Phase 1a doesn't hit "No connections in pool"
            if self.broker.ensure_connected():
                logger.debug("MT5 broker connection pool populated at init")
            else:
                logger.warning("MT5 broker pool unavailable at init - spreads will fail until connected")
        else:
            self.broker = PaperBroker(
                initial_capital=cfg.capital,
                execution_configs=self.execution_configs,
            )
            is_real_broker = False
        self.execution_bridge = ExecutionBridge(self.broker, is_real_broker=is_real_broker)

        self._narrative = EngineNarrativeService(self)
        self._rebalance = EngineRebalanceService(self)
        self._recovery = EngineRecoveryService(self)
        self._state = EngineStateService(self)
        self._full_panel = FullPanelService(self)
        self._data_retention = DataRetentionService(self)
        self._model_integrity = ModelIntegrityService(self)
        self._benchmark = BenchmarkService(self)
        self._initializer = EngineInitializeService(self)

        self._execution_context = ExecutionContext(
            state_store=self.state_store,
            execution_bridge=self.execution_bridge,
            engine_config=self._engine_cfg,
        )
        self._asset_registry = AssetRegistryService(self)
        self.assets = self._asset_registry.build()
        # Filter broker symbol map to only dashboard assets so MT5
        # client doesn't fetch/subscribe to non-portfolio symbols.
        if cfg.mt5.enabled and hasattr(self.broker, "_symbol_map"):
            valid_tickers = {a.ticker for a in self.assets.values()}
            self.broker._symbol_map = {k: v for k, v in self.broker._symbol_map.items() if k in valid_tickers}
            from paper_trading.ops.data_fetcher import _mt5_symbol_map

            _mt5_symbol_map.clear()
            _mt5_symbol_map.update(self.broker._symbol_map)
        self._init_experiment_context()
        self._narrative.init_narrative()

        self._snapshot_restorer.restore_asset_values(snapshot)

        # Restore open positions (may overwrite current_value for assets with positions)
        self._recovery.restore_positions(saved_positions)

        self._sim_store = SimulationStore(BASE)
        self._rebalance_last_day: datetime | None = None
        self._rebalance_weights: dict[str, float] = {}

        # Rebalance target day: 0 = Monday (weekly narrative sync)
        self._rebalance_dow: int = 0

        self._cycle_times: list[float] = []
        self._cycle_times_maxlen = 1000
        self._cycle_count: int = 0
        self._cycle_weekend: bool = False
        self._mtm_cache_value: float | None = None
        self._mtm_cache_cycle: int = -1

        # Auto-prune runs once per day
        self._last_prune_date: str | None = None

        # Background persistence writer (single-threaded drain)
        self._background_writer = BackgroundWriter(
            wal_writer=self._wal,
            db_store=self.state_store.db if hasattr(self.state_store, "db") else None,
        )

        # Resource monitor (samples every cycle, warns on threshold breach)
        self._resource_monitor = get_resource_monitor()

        # Fault-isolated actor orchestrator (Phase 5)
        # Pass snapshot so emergency halt state survives a restart.
        self._orchestrator = EngineOrchestrator(
            actors={name: AssetActor(name, asset, wal_writer=self._wal) for name, asset in self.assets.items()},
            wal_writer=self._wal,
            snapshot=snapshot,
        )
        self._narrative_api_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")

    def shutdown(self) -> None:
        """Graceful shutdown: drain actor pool, flush background writer, persist state.

        Order matters: futures may still be producing WAL events, so the pool
        must be drained BEFORE the background writer, and state must be saved
        last so the final snapshot includes all persisted data.
        """
        self._orchestrator.shutdown()
        self._background_writer.shutdown()
        self.save_state()

    def _build_asset_registry(self) -> None:
        svc = getattr(self, "_asset_registry", None)
        if svc is not None:
            self.assets = svc.build()

    def _init_experiment_context(self) -> None:
        """Initialize pipeline freeze and stamp attribution context on all assets."""
        universe = tuple(sorted(self.assets.keys()))
        ctx = ExperimentContext.initialize(
            asset_universe=universe,
            execution_config=self._engine_cfg.execution_defaults,
        )
        export_dir = str(Path(BASE) / "data" / "research" / "attribution")
        for name, asset in self.assets.items():
            asset.set_experiment_context(ctx.freeze.experiment_id, export_dir=export_dir)
        logger.info(
            "experiment: initialized experiment_id=%s (%d assets, %d components frozen)",
            ctx.freeze.experiment_id,
            len(self.assets),
            len(ctx.freeze.component_hashes),
        )

    def _refresh_narrative(self) -> bool:
        """Check if narrative needs refresh and apply latest from disk.

        Applies the latest confirmed narrative from disk synchronously
        (fast — reads a small JSON file).  If a new week's narrative
        is needed, kicks off the LLM pipeline on a background daemon
        thread so the engine cycle is not blocked.
        """
        if hasattr(self._narrative, "apply_active_narrative"):
            self._narrative.apply_active_narrative()
        return bool(self._narrative._refresh_narrative())

    def _should_rebalance(self) -> bool:
        return bool(self._rebalance.should_rebalance())

    def _rebalance_portfolio(self) -> None:
        self._rebalance.rebalance_portfolio()

    def get_state(self) -> dict:
        return dict(self._state.get_state())

    def save_state(self) -> dict[str, object]:
        return dict(self._state.save_state() or {})

    def _prune_old_data(self) -> None:
        svc = getattr(self, "_data_retention", None)
        if svc is not None:
            svc.prune()

    def initialize(self):
        svc = getattr(self, "_initializer", None)
        if svc is not None:
            svc.initialize()

    def _get_weekend_eligible_assets(self) -> set[str]:
        """Return set of asset names with weekend_eligible: true in their config."""
        return {
            name for name, asset in self.assets.items() if getattr(asset, "config", {}).get("weekend_eligible", False)
        }

    def _build_full_panel(self):
        svc = getattr(self, "_full_panel", None)
        return svc.build() if svc is not None else None

    def _invalidate_full_panel(self) -> None:
        svc = getattr(self, "_full_panel", None)
        if svc is not None:
            svc.invalidate()

    def _collect_results(self, results: dict, orch_results: dict) -> None:
        """Propagate orchestrator results into the engine-level results dict."""
        if orch_results.get("health"):
            results["orchestrator_health"] = orch_results["health"]
        asset_results = orch_results.get("assets", {})
        for name, sig in asset_results.items():
            if isinstance(sig, dict):
                results[name] = sig

    def _run_weekend_cycle(self, results: dict) -> dict:
        """Execute a weekend cycle for weekend-eligible assets only.

        Runs the orchestrator with a filtered asset set, persists WAL,
        and returns the results dict.  Returns an empty dict if no
        weekend-eligible assets exist.
        """
        weekend_eligible = self._get_weekend_eligible_assets()
        if not weekend_eligible:
            logger.debug("Market closed — core assets skipped")
            return {}
        logger.info(
            "Weekend cycle: processing %d weekend-eligible asset(s): %s",
            len(weekend_eligible),
            ", ".join(sorted(weekend_eligible)),
        )
        results["weekend_cycle"] = True
        self._cycle_weekend = True
        orch_results = self._orchestrator.run_once(allowed_assets=weekend_eligible)
        self._collect_results(results, orch_results)
        if orch_results.get("circuit_breaker"):
            logger.error("Weekend circuit breaker triggered — reason=%s", orch_results["circuit_breaker"])
            results["orchestrator_circuit_breaker"] = orch_results["circuit_breaker"]
            self.last_update = datetime.now(tz=ET)
            return results
        # Don't skip post-cycle bookkeeping — still persist WAL
        persist_commands = self._orchestrator.drain_persist_buffer()
        for cmd in persist_commands:
            pass
        self._background_writer.flush()
        if self._wal is not None:
            try:
                self._wal.flush()
            except (OSError, RuntimeError, AttributeError):
                logger.exception("WAL flush failed at weekend cycle boundary")
        self._cycle_weekend = False
        self.last_update = datetime.now(tz=ET)
        return results

    def _run_post_cycle_bookkeeping(
        self,
        results: dict,
        _t0: float,
        _t1: float,
        _t2: float,
        _t3: float,
    ) -> None:
        """Run post-cycle bookkeeping: narrative, rebalance, prune, flush, benchmarks.

        Called after every normal (non-weekend) cycle.  Updates
        last_update, prunes old data, flushes the background writer
        and WAL, records benchmark timing, and samples resource usage.
        """
        self.last_update = datetime.now(tz=ET)

        # ── Auto-prune old data (once per day) ───────────────────────
        self._prune_old_data()

        # ── Flush background writer and WAL ──────────────────────────
        self._background_writer.flush()
        if self._wal is not None:
            try:
                self._wal.flush()
            except (OSError, RuntimeError, AttributeError):
                logger.exception("WAL flush failed at cycle boundary")

        svc_bm = getattr(self, "_benchmark", None)
        if svc_bm is not None:
            svc_bm.record_cycle(_t0, _t1, _t2, _t3)

        # ── Resource monitoring (every 10th cycle) ─────────────────
        if self._cycle_count % 10 == 0:
            try:
                self._resource_monitor.sample()
            except (OSError, RuntimeError, ValueError):
                logger.debug("Resource monitor sample failed (expected on non-Linux)", exc_info=True)

    def run_once(self):
        _t0 = time.perf_counter()
        self._cycle_count += 1
        from features.data_fetch import bump_cycle_id

        bump_cycle_id()

        results: dict[str, object] = {}

        if is_market_closed():
            return self._run_weekend_cycle(results)

        self._cycle_weekend = False

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

        svc = getattr(self, "_model_integrity", None)
        if svc is not None:
            svc.check_integrity()
            svc.auto_retrain()

        # ── Fault-isolated asset execution via orchestrator ──────────
        # The orchestrator owns Phases 1-4 (refresh, signal, validity,
        # portfolio health, persist).  It is the sole source of truth
        # for drawdown tracking and circuit breakers.
        orch_results = self._orchestrator.run_once()

        # Propagate orchestrator health snapshot to results
        if orch_results.get("health"):
            results["orchestrator_health"] = orch_results["health"]

        # Extract per-asset signals (backward-compat: {name: signal_dict})
        asset_results = orch_results.get("assets", {})
        for name, sig in asset_results.items():
            if isinstance(sig, dict):
                results[name] = sig

        # Check orchestrator-level circuit breaker
        if orch_results.get("circuit_breaker"):
            logger.error("Orchestrator circuit breaker triggered — reason=%s", orch_results["circuit_breaker"])
            results["orchestrator_circuit_breaker"] = orch_results["circuit_breaker"]
            self.last_update = datetime.now(tz=ET)
            return results

        # Drain the orchestrator's persist buffer (populated during Phase 4).
        # All persistence (trades, positions, WAL) is handled inside _phase_4_persist.
        # This call discards the buffer so it doesn't grow unbounded — commands are
        # not reprocessed here because doing so would double-write to state.json / WAL.
        #
        # DESIGN NOTES (2026-07-11):
        #   - Phase 4 writes directly to the WAL writer (self._wal). The persist_buffer
        #     is an in-memory batch that gets drained every cycle — commands are deliberately
        #     discarded after phase 4 has committed them to WAL.
        #   - PaperTradingEngine.run_once() does NOT need to re-process these commands.
        #     If we did, we'd double-write: once in _phase_4_persist → WAL, once here → WAL.
        #   - BackgroundWriter.flush() below handles the actual fsync to disk.
        #   - Verified: all trade/position persistence happens inside _phase_4_persist or
        #     earlier (Phase 1b PEK budget close, Phase 3a circuit breaker flatten).
        #     No writer outputs are lost by discarding this buffer.
        self._orchestrator.drain_persist_buffer()

        _t1 = time.perf_counter()

        # ── Narrative refresh (non-blocking to asset cycles) ────────────
        self._refresh_narrative()

        _t2 = time.perf_counter()

        # ── Periodic risk-parity rebalance ─────────────────────────────
        if self._should_rebalance():
            self._rebalance_portfolio()

        if hasattr(self._rebalance, "write_weights_to_wal"):
            self._rebalance.write_weights_to_wal()

        _t3 = time.perf_counter()

        self._run_post_cycle_bookkeeping(results, _t0, _t1, _t2, _t3)

        return results
