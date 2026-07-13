import hashlib
import logging
import os
import statistics
import time
from datetime import datetime
from enum import Enum

import pytz
from dotenv import load_dotenv

# Re-exported from child modules for backward compatibility
from paper_trading.alerting.manager import setup_alerting_from_config
from paper_trading.asset_engine import AssetEngine  # noqa: F401
from paper_trading.asset_engine_factory import build_asset_engine
from paper_trading.config_manager import get_config
from paper_trading.execution.bridge import ExecutionBridge
from paper_trading.execution.mt5_broker import MT5Broker
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution_context import ExecutionContext
from paper_trading.governance.risk import reset as _reset_risk_governance
from paper_trading.logging.correlation import CorrelationIdFilter
from paper_trading.logging.json_formatter import install_json_logging
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
from paper_trading.ops.mt5_client import MT5Client
from paper_trading.ops.simulation_snapshot import SimulationStore
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator
from paper_trading.portfolio_builder import build_paper_portfolio
from paper_trading.replay.wal import WalWriter
from paper_trading.services.engine_narrative_service import EngineNarrativeService
from paper_trading.services.engine_rebalance_service import EngineRebalanceService
from paper_trading.services.engine_recovery_service import EngineRecoveryService
from paper_trading.services.engine_state_service import EngineStateService
from paper_trading.state_store import _SKIP_JOURNAL, StateStore, sanitize  # noqa: F401
from paper_trading.writer import BackgroundWriter
from shared.execution_config import build_execution_configs
from shared.registry import StrategyRegistry

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

    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "live")
    log_path = os.path.join(log_dir, "engine.log")
    os.makedirs(log_dir, exist_ok=True)

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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIVE_DIR = os.path.join(BASE, "data", "live")
STATE_PATH = os.path.join(_LIVE_DIR, "state.json")
CACHE_DIR = os.path.join(_LIVE_DIR, "cache")
LOG_PATH = os.path.join(_LIVE_DIR, "engine.log")  # backward compat
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

os.makedirs(MODEL_DIR, exist_ok=True)

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

        # Reset global risk governance state, then restore persisted state
        # (sell tripwire deques) from snapshot so the 20-trade rolling window
        # survives restarts.
        from paper_trading.governance.risk import set_risk_state

        _reset_risk_governance()
        if snapshot is not None and snapshot.risk_state:
            try:
                set_risk_state(snapshot.risk_state)
                n_assets = len(snapshot.risk_state.get("sell_win_rates", {}))
                if n_assets:
                    logger.info(
                        "Restored risk governance state for %d asset(s) from snapshot",
                        n_assets,
                    )
            except (OSError, ValueError, TypeError, KeyError):
                logger.exception("Failed to restore risk state from snapshot")
        if snapshot is not None and snapshot.engine_status:
            self.start_date = datetime.fromisoformat(
                snapshot.engine_status.get("start_time", self.start_date.isoformat())
            )
        saved_positions = (snapshot.open_positions or {}) if snapshot else {}

        cfg = config or get_config()
        self._engine_cfg = cfg
        self.execution_configs = build_execution_configs(cfg.assets, defaults=cfg.execution_defaults)

        # Initialize alerting channels from config
        try:
            setup_alerting_from_config(cfg)
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            logger.debug("Alerting setup skipped (no config section or invalid)", exc_info=True)

        if cfg.mt5.enabled:
            self.broker = self._create_mt5_broker(cfg)
            # Wire WAL writer into broker for MT5 order lifecycle events
            if hasattr(self.broker, "set_wal_writer"):
                self.broker.set_wal_writer(self._wal)
            is_real_broker = True
            # Install MT5 client as global data provider for data_fetcher
            self._install_mt5_data_provider(cfg)
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

        self._execution_context = ExecutionContext(
            state_store=self.state_store,
            execution_bridge=self.execution_bridge,
            engine_config=self._engine_cfg,
        )
        self._build_asset_registry()
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

        # Restore current_value for ALL assets from the snapshot so the equity curve
        # starts at the correct baseline.  Previously, only assets with open positions
        # had their current_value restored — flat assets reset to initial_capital,
        # causing the "equity reset to baseline" symptom on restart.
        if snapshot is not None and snapshot.asset_values:
            for name, cv in snapshot.asset_values.items():
                if name in self.assets:
                    asset = self.assets[name]
                    asset.current_value = cv
                    asset.pos_mgr.current_value = cv
                    if cv > asset.peak_value:
                        asset.peak_value = cv
                        asset.pos_mgr.peak_value = cv
            logger.info(
                "Restored current_value for %d assets from snapshot",
                len(snapshot.asset_values),
            )

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

    def _create_mt5_broker(self, cfg):
        import yaml

        mt5 = cfg.mt5
        symbol_map: dict[str, str] = {}
        if mt5.symbol_map_path:
            map_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), mt5.symbol_map_path)
            if os.path.exists(map_path):
                with open(map_path) as f:
                    symbol_map = yaml.safe_load(f) or {}
                logger.info("Loaded MT5 symbol map from %s (%d symbols)", map_path, len(symbol_map))
            else:
                logger.warning("MT5 symbol map not found at %s", map_path)

        return MT5Broker(
            account=mt5.account,
            password=mt5.password,
            server=mt5.server,
            symbol_map=symbol_map,
            bridge_host=mt5.bridge_host,
            bridge_port=mt5.bridge_port,
        )

    def _install_mt5_data_provider(self, cfg) -> None:
        import yaml

        from paper_trading.ops.data_fetcher import set_mt5_client

        symbol_map: dict[str, str] = {}
        if cfg.mt5.symbol_map_path:
            map_path = os.path.join(BASE, cfg.mt5.symbol_map_path)
            if os.path.exists(map_path):
                with open(map_path) as f:
                    symbol_map = yaml.safe_load(f) or {}

        client = MT5Client(
            account=cfg.mt5.account,
            password=cfg.mt5.password,
            server=cfg.mt5.server,
            bridge_host=cfg.mt5.bridge_host,
            bridge_port=cfg.mt5.bridge_port,
            symbol_map=symbol_map,
        )
        if not client.connect():
            logger.error("MT5 data provider failed to connect — data fetches will fall back to yfinance")
        set_mt5_client(client, symbol_map)
        logger.info("MT5 data provider installed")

    def _build_asset_registry(self) -> None:
        portfolio = build_paper_portfolio(self._engine_cfg.halt)
        _reg = StrategyRegistry.get_instance()
        _reg.register_defaults(list(portfolio.keys()))
        for name, spec in portfolio.items():
            self.assets[name] = build_asset_engine(
                ticker=spec["ticker"],
                name=name,
                contract=spec["contract"],
                allocation=spec["alloc"],
                halt_config=spec["halt"],
                config=spec["config"],
                sl_mult=spec.get("sl_mult", 1.0),
                tp_mult=spec.get("tp_mult", 2.5),
                max_depth=spec.get("max_depth", 2),
                regime_geometry=spec.get("regime_geometry", {}),
                context=self._execution_context,
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

    def _refresh_narrative(self) -> bool:
        return self._narrative._refresh_narrative()

    def _should_rebalance(self) -> bool:
        return self._rebalance.should_rebalance()

    def _rebalance_portfolio(self) -> None:
        self._rebalance.rebalance_portfolio()

    def get_state(self) -> dict:
        return self._state.get_state()

    def save_state(self):
        return self._state.save_state()

    def _prune_old_data(self) -> None:
        """Prune data files and SQLite tables older than their per-type retention period.

        Runs at most once per calendar day to keep disk usage bounded
        without slowing down every cycle. Retention periods are read from
        the engine config (``self._engine_cfg.retention``), falling back
        to module-level defaults in ``prune_data.RETENTION``.
        """
        today = datetime.now(tz=ET).strftime("%Y-%m-%d")
        if self._last_prune_date == today:
            return
        self._last_prune_date = today

        try:
            from paper_trading.ops.prune_data import RETENTION, prune_all

            retention = dict(RETENTION)
            cfg_retention = getattr(self._engine_cfg, "retention", {})
            # Map config keys to prune_data keys
            key_map = {
                "trades_days": "trades",
                "attribution_days": "attribution",
                "equity_history_days": "equity_history",
                "trace_days": "trace.jsonl",
                "wal_days": "wal/engine.jsonl",
                "log_days": "engine.log",
                "shadow_feedback_days": "shadow_feedback",
                "shadow_memory_days": "shadow_memory",
            }
            for cfg_key, ret_key in key_map.items():
                val = cfg_retention.get(cfg_key)
                if val is not None and isinstance(val, (int, float)) and val > 0:
                    retention[ret_key] = int(val)

            logger.info(
                "Pruning data older than retention limits: trades=%dd, attr=%dd, eq=%dd, log=%dd",
                retention.get("trades", 365),
                retention.get("attribution", 365),
                retention.get("equity_history", 90),
                retention.get("engine.log", 14),
            )
            stats = prune_all(apply=True, retention=retention)
            total = sum(s.get("pruned", 0) + s.get("pruned_files", 0) for s in stats.values() if isinstance(s, dict))
            if total > 0:
                logger.info("Pruned %d items across %d data types", total, len(stats))
            else:
                logger.debug("No data needed pruning today")
        except (OSError, ValueError, TypeError, KeyError) as e:
            logger.warning("Auto-prune failed: %s", e)

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
                _full_panel = self._build_full_panel()
                asset.train(force=True, full_panel=_full_panel)
                logger.info("%s: training done", name)
            except (OSError, ValueError, TypeError, RuntimeError, ImportError) as e:
                logger.error("%s: training FAILED - %s", name, e)

    def _get_weekend_eligible_assets(self) -> set[str]:
        """Return set of asset names with weekend_eligible: true in their config."""
        return {
            name for name, asset in self.assets.items() if getattr(asset, "config", {}).get("weekend_eligible", False)
        }

    def _build_full_panel(self):
        """Pre-fetch all per-asset price series for cross-sectional (Group 1) features.

        Returns a DataFrame of close prices (one column per asset), ffill-cleaned,
        or None on failure. Used by train() so it includes the same Group 1
        cross-sectional feature set that the live inference pipeline produces —
        without this, retrained models get 74 features while inference expects
        84, breaking inference for the freshly-trained model.

        Cycle-cached: callers should hold the returned frame and pass it to
        train(force=..., full_panel=full_panel).
        """
        import pandas as pd

        from features.data_fetch import fetch_asset_data

        # If we already built it this engine instance, reuse (rare — process restart
        # usually degrades the cache). Otherwise construct fresh.
        cached = getattr(self, "_full_panel_cache", None)
        if cached is not None and not cached.empty and len(cached.columns) == len(self.assets):
            return cached

        panel_dict: dict[str, pd.Series] = {}
        for aname, aengine in self.assets.items():
            try:
                ticker = getattr(aengine, "ticker", None) or getattr(getattr(aengine, "asset", None), "ticker", None)
                if ticker is None:
                    continue
                aprices, _, _, _, _, _ = fetch_asset_data(aname, ticker)
                if aprices is not None and not aprices.empty:
                    panel_dict[aname] = aprices.iloc[:, 0]
            except (OSError, ValueError, KeyError, RuntimeError, AttributeError):
                continue

        if not panel_dict:
            self._full_panel_cache = None
            return None

        full_panel = pd.DataFrame(panel_dict).ffill().dropna(how="all")
        self._full_panel_cache = full_panel
        return full_panel

    def _invalidate_full_panel(self) -> None:
        """Clear the cached full panel (call after adding/removing an asset)."""
        self._full_panel_cache = None

    def _collect_results(self, results: dict, orch_results: dict) -> None:
        """Propagate orchestrator results into the engine-level results dict."""
        if orch_results.get("health"):
            results["orchestrator_health"] = orch_results["health"]
        asset_results = orch_results.get("assets", {})
        for name, sig in asset_results.items():
            if isinstance(sig, dict):
                results[name] = sig

    def run_once(self):
        _t0 = time.perf_counter()
        self._cycle_count += 1
        from features.data_fetch import bump_cycle_id

        bump_cycle_id()

        results: dict[str, object] = {}

        if is_market_closed():
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

        # Per-asset model file integrity: detect file changes mid-run and reload.
        # This catches e.g. parallel retrain jobs that update the model JSON on disk
        # while the engine is still using a stale in-memory copy.
        for _asset_name, asset in list(self.assets.items()):
            if not hasattr(asset, "_model_hash") or not hasattr(asset, "model_path"):
                continue
            model_path = asset.model_path
            if not os.path.exists(model_path):
                continue
            try:
                with open(model_path, "rb") as _fm:
                    current_hash = hashlib.sha256(_fm.read()).hexdigest()[:16]
                if current_hash != asset._model_hash and current_hash != "unknown":
                    logger.info(
                        "experiment: model hash changed for %s (%s… → %s…) — reloading",
                        _asset_name,
                        asset._model_hash[:8],
                        current_hash[:8],
                    )
                    asset.train(force=False)
            except (OSError, ValueError, TypeError, AttributeError):
                logger.debug(
                    "experiment: model integrity check skipped for %s",
                    _asset_name,
                    exc_info=True,
                )

        # ── Automatic retraining trigger (every 100 cycles ≈ 100min at 60s interval) ─────
        if not hasattr(self, "_retrain_cycle_counter"):
            self._retrain_cycle_counter = 0
        self._retrain_cycle_counter += 1
        if self._retrain_cycle_counter % 100 == 0:
            _rt_min_stale_days = 90
            for _rt_name, _rt_asset in list(self.assets.items()):
                _rt_mp = getattr(_rt_asset, "model_path", None)
                if _rt_mp and os.path.exists(_rt_mp):
                    try:
                        _rt_mtime = os.path.getmtime(_rt_mp)
                        _rt_age_days = (time.time() - _rt_mtime) / 86400
                        if _rt_age_days > _rt_min_stale_days:
                            logger.info(
                                "retrain: %s model is %.0f days old (threshold=%d) — retraining",
                                _rt_name,
                                _rt_age_days,
                                _rt_min_stale_days,
                            )
                            _rt_full_panel = self._build_full_panel()
                            _rt_asset.train(force=True, full_panel=_rt_full_panel)
                    except OSError:
                        pass

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

        # ── WAL: persist current portfolio weights ────────────────────
        if self._rebalance_weights and self._wal is not None:
            try:
                _weight_method = get_config().defaults.get("weight_method", "risk_parity_v1") or "risk_parity_v1"
                self._wal.write(
                    "portfolio_weights",
                    {
                        "timestamp": datetime.now(tz=ET).isoformat(),
                        "cycle": self._cycle_count,
                        "method": _weight_method,
                        "weights": {n: round(w, 4) for n, w in self._rebalance_weights.items()},
                        "n_assets": len(self._rebalance_weights),
                    },
                )
            except (OSError, RuntimeError, KeyError):
                logger.exception("WAL write failed for portfolio_weights")

        _t3 = time.perf_counter()

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
