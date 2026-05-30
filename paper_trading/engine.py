import logging
import os
import statistics
import time
from datetime import datetime
from enum import Enum

import pandas as pd
import pytz
from dotenv import load_dotenv

from features.fxstreet_fetcher import (
    confirm_pending_narrative,
    get_narrative_status,
    run_weekly_narrative_pipeline,
)
from paper_trading.asset_engine import AssetEngine
from paper_trading.config_manager import get_config
from paper_trading.entry.decision import PositionIntent, PositionSide
from paper_trading.execution.bridge import ExecutionBridge
from paper_trading.execution.paper_broker import PaperBroker

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
from paper_trading.ops.simulation_snapshot import SimulationStore, build_asset_snapshot
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator
from paper_trading.replay.wal import WalWriter
from paper_trading.satellite.engine import HighVolSatellite, SatelliteConfig
from paper_trading.satellite.runner import (
    compute_btc_context,
    compute_core_returns,
    fetch_btc_price,
    fetch_macro_context,
)
from paper_trading.state_store import _SKIP_JOURNAL, EngineSnapshot, StateStore, sanitize  # noqa: F401
from shared.execution_config import build_execution_configs
from shared.registry import StrategyRegistry
from shared.sizing import compute_equal_risk_weights

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
    def __init__(self, state_store=None, wal_writer=None):
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

        snapshot = self.state_store.load_snapshot()
        if snapshot is not None and snapshot.engine_status:
            self.start_date = datetime.fromisoformat(
                snapshot.engine_status.get("start_time", self.start_date.isoformat())
            )
        saved_positions = (snapshot.open_positions or {}) if snapshot else {}

        cfg = get_config()
        self.execution_configs = build_execution_configs(cfg.assets, defaults=cfg.execution_defaults)
        self.broker = PaperBroker(
            initial_capital=cfg.capital,
            execution_configs=self.execution_configs,
        )
        self.execution_bridge = ExecutionBridge(self.broker)

        self._build_asset_registry()
        self._init_experiment_context()
        self._init_narrative()
        self._init_satellite()
        self._restore_positions(saved_positions)
        self._sim_store = SimulationStore(BASE)
        self._rebalance_last_day: datetime | None = None
        self._rebalance_weights: dict[str, float] = {}

        # Performance benchmark state
        self._cycle_times: list[float] = []
        self._cycle_times_maxlen = 1000
        self._cached_mtm_total: float | None = None
        self._cached_mtm_cycle: int = 0
        self._cycle_count: int = 0

        # Fault-isolated actor orchestrator (Phase 5)
        self._orchestrator = EngineOrchestrator(
            actors={name: AssetActor(name, asset, wal_writer=self._wal) for name, asset in self.assets.items()},
            satellite_actor=(
                AssetActor("BTC", self.satellite, wal_writer=self._wal) if self.satellite is not None else None
            ),
            wal_writer=self._wal,
        )

    def _build_asset_registry(self) -> None:
        from paper_trading.portfolio_builder import build_paper_portfolio as _build_paper_portfolio

        portfolio = _build_paper_portfolio(get_config().halt)
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
            execution_config=get_config().execution_defaults,
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

    def _init_narrative(self) -> None:
        self._narrative_api_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
        self._apply_active_narrative()

    def _apply_active_narrative(self) -> None:
        status = get_narrative_status()
        active = status.get("active")
        if active:
            from features.macro_narrative import MacroNarrativeFeatures

            narr = MacroNarrativeFeatures(**active)
            for asset in self.assets.values():
                asset.set_narrative_state(narr)

    def _refresh_narrative(self) -> bool:
        now = datetime.now(tz=ET)
        is_monday = now.weekday() == 0
        status = get_narrative_status()
        stale = status.get("stale", True)
        if not is_monday and not stale:
            return False
        if stale or (is_monday and status.get("needs_confirmation")):
            api_key = self._narrative_api_key or None
            ok = run_weekly_narrative_pipeline(api_key)
            if ok:
                deadline_hour = get_config().narrative_config.get("auto_confirm_deadline_hour", 12)
                if now.hour >= deadline_hour or not api_key:
                    confirm_pending_narrative()
                    self._apply_active_narrative()
                    logger.info("Narrative auto-confirmed for week")
                else:
                    logger.info("Narrative pending — awaiting confirmation (deadline %d:00 ET)", deadline_hour)
            else:
                logger.warning("Narrative refresh failed — carrying forward last week")
        return True

    def _init_satellite(self) -> None:
        self.satellite = None
        sat_cfg = get_config().satellite
        btc_sat = sat_cfg.get("BTC", {})
        if btc_sat:
            sconfig = SatelliteConfig(
                max_allocation_pct=btc_sat.get("max_allocation_pct", 0.05),
                vol_target=btc_sat.get("vol_target", 0.40),
                max_drawdown_pct=btc_sat.get("max_drawdown_pct", -0.25),
                sl_mult=btc_sat.get("sl_mult", 0.58),
                tp_mult=btc_sat.get("tp_mult", 1.51),
            )
            self.satellite = HighVolSatellite(
                total_aum=get_config().capital,
                config=sconfig,
                name="BTC",
            )

    @staticmethod
    def _restore_saved_position(asset, pos_data: dict) -> None:
        pos_dict = pos_data.get("position")
        if pos_dict:
            intent = PositionIntent(
                side=PositionSide(pos_dict["side"]),
                entry_price=pos_dict["entry"],
                entry_date=pos_dict["entry_date"],
                stop_loss=pos_dict["sl"],
                take_profit=pos_dict["tp"],
                vol=pos_dict["vol"],
            )
            asset.position = pos_dict
            asset.pos_mgr.open(intent)
        cv = pos_data.get("current_value")
        if cv is not None:
            asset.current_value = cv
            asset.pos_mgr.current_value = cv
        pv = pos_data.get("peak_value")
        if pv is not None:
            asset.peak_value = pv
            asset.pos_mgr.peak_value = pv
        asset.trade_log = pos_data.get("trade_log", [])
        asset.pos_mgr.trade_log = list(pos_data.get("trade_log", []))
        asset.prob_history = pos_data.get("prob_history", [])

    def _restore_positions(self, saved_positions: dict) -> None:
        for name, pos_data in saved_positions.items():
            if name in self.assets:
                self._restore_saved_position(self.assets[name], pos_data)
            elif name == "satellite" and self.satellite is not None:
                self._restore_satellite_position(self.satellite, pos_data)

    def _restore_satellite_position(self, sat, pos_data: dict) -> None:
        pos_dict = pos_data.get("position")
        if pos_dict:
            sat.position_active = True
            sat.position_side = pos_dict["side"]
            sat.entry_price = pos_dict["entry"]
            sat.stop_price = pos_dict["sl"]
            sat.target_price = pos_dict["tp"]
            sat.position_entry_date = pos_dict["entry_date"]
            sat.position_vol = pos_dict["vol"]

        cv = pos_data.get("current_value")
        if cv is not None:
            sat.current_value = cv
        pv = pos_data.get("peak_value")
        if pv is not None:
            sat.peak_value = pv
        ic = pos_data.get("initial_capital")
        if ic is not None:
            sat.initial_capital = ic
        ec = pos_data.get("entry_capital")
        if ec is not None:
            sat._entry_capital = ec
        dr = pos_data.get("daily_returns")
        if dr is not None:
            sat._daily_returns = list(dr)

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
        """Compute total portfolio MTM with cycle-level caching.

        Invalidated once per run_once() cycle to avoid redundant O(N)
        iterations over all assets.
        """
        if not hasattr(self, "_cached_mtm_total"):
            self._cached_mtm_total = None
            self._cached_mtm_cycle = 0
            self._cycle_count = 0
        if self._cached_mtm_total is not None and self._cached_mtm_cycle == self._cycle_count:
            return self._cached_mtm_total
        mtm = sum(a.mtm_value for a in self.assets.values())
        if self.satellite is not None:
            mtm += self.satellite.current_value
        self._cached_mtm_total = mtm
        self._cached_mtm_cycle = self._cycle_count
        return mtm

    def run_once(self):
        _t0 = time.perf_counter()
        if not hasattr(self, "_cycle_count"):
            self._cycle_count = 0
            self._cached_mtm_total = None
            self._cached_mtm_cycle = 0
            self._cycle_times = []
        self._cycle_count += 1

        if is_market_closed():
            logger.debug("Market closed — core assets skipped")
            return self._run_satellite_only()

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

        pd_limit = get_config().portfolio_drawdown_limit
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

        # ── Satellite run ──────────────────────────────────────────────
        if self.satellite is not None:
            try:
                self._run_satellite(results)
            except Exception as e:
                logger.error("satellite run failed: %s", e)
                results["satellite"] = {"asset": "BTC", "error": str(e)}

        # ── WAL: engine-level state committed ──────────────────────────
        self._wal.write(
            "state_committed",
            {
                "assets": {name: {"has_position": a.pos_mgr.has_position()} for name, a in self.assets.items()},
                "satellite_active": self.satellite is not None and self.satellite.position_active
                if hasattr(self.satellite, "position_active")
                else False,
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
        _sat_time = _elapsed - (_t3 - _t0)
        if len(self._cycle_times) % 20 == 0:
            recent = self._cycle_times[-100:]
            p50 = statistics.median(recent)
            p95 = sorted(recent)[int(len(recent) * 0.95)]
            logger.info(
                "BENCHMARK: cycle=%.3fs  orch=%.3fs  narr=%.3fs  rebal=%.3fs  sat=%.3fs  p50=%.3fs  p95=%.3fs  n=%d",
                _elapsed,
                _orch_time,
                _narr_time,
                _rebal_time,
                _sat_time,
                p50,
                p95,
                len(recent),
            )

        return results

    def _run_satellite(self, results: dict) -> None:
        """Evaluate regime gate and manage satellite (BTC) position."""
        sat = self.satellite
        if sat is None:
            return

        try:
            btc_price_data = fetch_btc_price(self.assets)
            if btc_price_data is None or btc_price_data.empty:
                results["satellite"] = {"asset": "BTC", "error": "no BTC price data"}
                return

            ctx = compute_btc_context(btc_price_data)
            vix, dxy_mom = fetch_macro_context()
            core_rets_63d = compute_core_returns(self.assets)

            decision = sat.evaluate_gate(
                vix=vix,
                dxy_mom_21=dxy_mom,
                btc_vol_zscore=ctx["vol_zscore"],
                portfolio_returns_63d=core_rets_63d,
                btc_returns_63d=ctx["returns_63d"],
                crisis_regime_active=self._detect_crisis_regime(),
            )

            current_price = float(btc_price_data["close"].ffill().iloc[-1])
            sat.current_price = current_price
            returns_all = ctx.get("returns_all")
            current_return = float(returns_all[-1]) if returns_all is not None and len(returns_all) >= 1 else 0.0

            # Compute vol from BTC returns (EWMA, same as AssetEngine._tb_vol)
            if returns_all is not None and len(returns_all) >= 20:
                returns_series = pd.Series(returns_all)
                vol = float(returns_series.ewm(span=100).std().iloc[-1])
            else:
                vol = 0.45  # fallback BTC vol baseline

            # Deploy capital on first run
            if sat.initial_capital == 0.0:
                sat.deploy_capital(sat.max_capital)
                logger.info("BTC satellite: deployed capital %.2f", sat.max_capital)

            # Snapshot pre-exit satellite state for trade persistence
            sat_entry = sat.entry_price
            sat_entry_date = getattr(sat, "position_entry_date", None)
            sat_entry_capital = getattr(sat, "_entry_capital", 0.0)
            sat_stop = sat.stop_price
            was_active = sat.position_active

            # Record return for satellite contribution metrics. Live P&L is
            # marked from entry capital so dashboard value follows BTC price.
            sat.record_return(current_return)
            if sat.position_active and sat.entry_price is not None and sat.entry_price > 0:
                entry_capital = sat._entry_capital or sat.max_capital or sat.current_value
                sat.current_value = entry_capital * (current_price / sat.entry_price)
                sat.peak_value = max(sat.peak_value, sat.current_value)

            # Check SL/TP exit (only if position active)
            exit_reason = sat.check_exit(current_price) if sat.position_active else None

            # Gate → position management (only if not already exited via SL/TP)
            if exit_reason is None:
                if decision.allowed and not sat.position_active:
                    sat.open_position(entry_price=current_price, vol=vol)
                elif not decision.allowed and sat.position_active:
                    sat.close_position(reason="GATE_CLOSED")

            # Persist satellite trade if one just closed
            if was_active and not sat.position_active and sat._last_exit_reason is not None:
                exit_price = current_price
                pnl_pct = (exit_price / sat_entry - 1.0) if sat_entry else 0.0
                risk_pct = abs(sat_entry - sat_stop) / sat_entry if sat_stop and sat_entry else 0.0
                r_mult = pnl_pct / risk_pct if risk_pct > 0 else 0.0
                entry_dt = str(sat_entry_date) if sat_entry_date else str(datetime.now(tz=ET).date())
                exit_dt = str(datetime.now(tz=ET).date())
                trade = {
                    "asset": sat.name,
                    "side": "long",
                    "entry": round(float(sat_entry), 4) if sat_entry else None,
                    "exit": round(float(exit_price), 4),
                    "entry_date": entry_dt,
                    "exit_date": exit_dt,
                    "return": round(pnl_pct, 6),
                    "pnl": round(pnl_pct * sat_entry_capital, 2),
                    "total_pnl": round(pnl_pct * sat_entry_capital, 2),
                    "reason": sat._last_exit_reason.lower(),
                    "realized_r": round(r_mult, 4),
                    "bars": 0,
                }
                self.state_store.append_trade(trade)
                self.state_store.write_trade_outcomes_cache()
                self.state_store.write_analytics_snapshot()

            logger.info(
                "%s satellite: gate=%s, position=%s, value=%.2f%s",
                sat.name,
                "OPEN" if decision.allowed else "CLOSED",
                "ACTIVE" if sat.position_active else "FLAT",
                sat.current_value,
                f", exit={exit_reason}" if exit_reason else "",
            )

            results["satellite"] = {
                "asset": "BTC",
                "gate_allowed": decision.allowed,
                "gate_reasons": decision.reasons_blocked,
                "position_active": sat.position_active,
                "current_value": round(sat.current_value, 2),
                "current_price": round(current_price, 2),
                "entry_price": sat.entry_price,
                "stop_price": sat.stop_price,
                "target_price": sat.target_price,
                "exit_reason": sat._last_exit_reason,
            }
        except Exception as e:
            logger.error("satellite gating failed: %s", e)
            results["satellite"] = {"asset": "BTC", "error": str(e)}

    def _run_satellite_only(self) -> dict:
        results: dict[str, object] = {}
        if self.satellite is not None:
            try:
                self._run_satellite(results)
            except Exception as e:
                logger.error("satellite weekend run failed: %s", e)
                results["satellite"] = {"asset": "BTC", "error": str(e)}
        if not results.get("satellite"):
            results["satellite"] = {"asset": "BTC", "message": "no satellite configured"}
        return results

    def _detect_crisis_regime(self) -> bool:
        """Check if any core asset has an active CRISIS validity state."""
        for name, asset in self.assets.items():
            state = getattr(asset.validity_sm, "current_state", None)
            if state is not None and "CRISIS" in str(state).upper():
                return True
        return False

    def _should_rebalance(self) -> bool:
        """Check if the portfolio should be rebalanced.

        Rebalance once per week on Monday (same cadence as narrative refresh),
        but only if there are enough assets with price data.
        """
        want = getattr(self, "_rebalance_dow", None)
        if want is None:
            self._rebalance_dow = datetime.now(tz=ET).weekday()
        if self._rebalance_last_day is None or self._rebalance_last_day != datetime.now(tz=ET).date():
            self._rebalance_last_day = datetime.now(tz=ET).date()
            return True
        return False

    def _collect_daily_returns(self, window: int = 252) -> pd.DataFrame:
        """Collect daily returns for all assets that have price data.

        Returns a DataFrame with columns=asset names, index=dates,
        values=daily returns.  Only includes assets with ``current_price``.
        """
        price_data: dict[str, pd.Series] = {}
        for name, asset in self.assets.items():
            px = asset.current_price
            if px is None or px <= 0:
                continue
            try:
                hist = fetch_history(asset.ticker, period=f"{window + 60}d", interval="1d")
                if hist is not None and "close" in hist.columns and len(hist) >= window:
                    price_data[name] = hist["close"]
            except Exception:
                continue
        if not price_data:
            return pd.DataFrame()
        df = pd.DataFrame(price_data)
        returns = df.pct_change().dropna()
        return returns.iloc[-window:] if len(returns) > window else returns

    def _rebalance_portfolio(self) -> None:
        """Compute risk-parity weights and reallocate capital across assets.

        Uses governance-adjusted volatility: each asset's raw vol is scaled
        by 1/combined_size_scalar so that assets with tighter governance
        constraints receive lower risk parity weight.
        """
        window = 252
        returns = self._collect_daily_returns(window)
        if returns.empty or len(returns.columns) < 2:
            logger.info("Risk parity skipped — insufficient price data")
            return

        # Compute governance-adjusted vols per asset
        total_value = self._compute_mtm_total()

        adjusted = returns.copy()
        for col in adjusted.columns:
            if col not in self.assets:
                continue
            asset = self.assets[col]
            combined_size = max(
                asset.governance._narrative_size_scalar * asset.governance._liquidity_size_scalar,
                AssetEngine._MIN_SIZE_SCALAR,
            )
            vol_scale = 1.0 / combined_size if combined_size > 0 else 1.0
            adjusted[col] = adjusted[col] * vol_scale

        try:
            weights = compute_equal_risk_weights(adjusted)
        except Exception as e:
            logger.error("Risk parity optimization failed: %s", e)
            return

        if not weights:
            return

        # Normalize to available assets only
        total_w = sum(weights.get(n, 0.0) for n in self.assets)
        if total_w <= 0:
            return

        # Save weights for dashboard exposure
        self._rebalance_weights = {n: weights.get(n, 0.0) / total_w for n in self.assets}

        # Apply target capital to each asset
        for name, asset in self.assets.items():
            target = total_value * self._rebalance_weights[name]
            asset.set_capital_base(target)

        logger.info(
            "Risk parity rebalanced %d assets — weights: %s",
            len(self.assets),
            {n: f"{w:.3f}" for n, w in self._rebalance_weights.items()},
        )

    def get_state(self) -> dict:
        """Build the dashboard/state snapshot for the current engine state."""
        ad = {}
        overall_validity = 0.0
        any_halted = False
        for name, asset in self.assets.items():
            asset.refresh_price()
            metrics = asset.get_metrics()
            halt = asset.check_halt_conditions(metrics=metrics)
            validity = asset.update_validity(halt=halt)
            overall_validity += validity.get("exposure", 0.0)
            if halt["halted"]:
                any_halted = True
            signal = dict(asset.prob_history[-1]) if asset.prob_history else None
            if signal and metrics.get("current_price"):
                signal["close_price"] = metrics["current_price"]
            meta_inf = metrics.get("meta_inference") or {}
            feat_stab = metrics.get("feature_stability") or {}
            ad[name] = {
                "metrics": metrics,
                "halt": halt,
                "validity_state": validity.get("state", "YELLOW"),
                "validity_exposure": validity.get("exposure", 0.5),
                "last_signal": signal,
                "execution_state": "HALTED" if halt["halted"] else "ACTIVE",
                "sl_mult": asset.sl_mult,
                "tp_mult": asset.tp_mult,
                "meta_confidence": meta_inf.get("meta_confidence"),
                "meta_decision": meta_inf.get("meta_decision"),
                "feature_stability_jaccard": feat_stab.get("jaccard_top_10"),
                "feature_stability_spearman": feat_stab.get("spearman_rank_corr"),
                "liquidity_regime": asset.governance._liquidity_regime,
                "liquidity_sl_mult": asset.governance._liquidity_sl_mult,
                "liquidity_size_scalar": asset.governance._liquidity_size_scalar,
                "narrative_sl_mult": asset.governance._narrative_sl_mult,
                "narrative_size_scalar": asset.governance._narrative_size_scalar,
                "narrative_regime": asset.governance._narrative_active.overall_regime
                if asset.governance._narrative_active
                else None,
                "narrative_stale": asset.governance._narrative_stale,
                "regime_geometry": asset.regime_geometry,
                "soft_warnings": halt.get("soft_warnings", []),
                "stop_out_last_side": getattr(asset, "_last_stop_out_side", None),
                "stop_out_last_date": (str(d) if (d := getattr(asset, "_last_stop_out_date", None)) else None),
            }
        total_value = self._compute_mtm_total()
        rp_weights = {}
        rp_allocations = {}
        if self._rebalance_weights:
            for name, asset in self.assets.items():
                w = self._rebalance_weights.get(name, 0.0)
                rp_weights[name] = round(w, 4)
                rp_allocations[name] = round(asset.capital_base, 2)
        return {
            "portfolio": self._compute_portfolio_summary(overall_validity, any_halted),
            "assets": ad,
            "satellite": self._satellite_snapshot(),
            "halt_conditions": get_config().halt,
            "risk_parity": {
                "weights": rp_weights,
                "capital_allocations": rp_allocations,
                "total_value": round(total_value, 2),
            },
        }

    def _compute_portfolio_summary(self, overall_validity: float, any_halted: bool) -> dict:
        n = len(self.assets) or 1
        exec_state = (
            ExecutionState.HALTED
            if any_halted
            else (ExecutionState.PAUSED if (overall_validity / n) < 0.5 else ExecutionState.ACTIVE)
        )
        # tc is the theoretical full portfolio capital (Core + Satellite)
        tc = get_config().capital or sum(a.initial_capital for a in self.assets.values())

        # mtm_total = sum of all assets MTM + satellite MTM + cash buffer
        mtm_total = self._compute_mtm_total()
        sat_unrealized = 0.0
        if self.satellite is not None:
            mtm_total += self.satellite.current_value
            if self.satellite.position_active and self.satellite.entry_price:
                # Unrealized for satellite = current_value - entry_capital
                entry_cap = getattr(self.satellite, "_entry_capital", self.satellite.max_capital)
                sat_unrealized = self.satellite.current_value - entry_cap

        # Cash buffer fills the gap to full capital, absorbing PnL drift from
        # position_size leverage and asset current_value vs initial_capital differences
        cash_buffer = max(0, tc - mtm_total)
        mtm_total += cash_buffer

        satellite_value = self.satellite.current_value if self.satellite is not None else 0.0
        satellite_pct = satellite_value / max(tc, 1) * 100

        unrealized_dollars = (
            sum(
                (a.mtm_value - (a.current_value if not pd.isna(a.current_value) else a.initial_capital))
                for a in self.assets.values()
            )
            + sat_unrealized
        )

        # Realized = actual closed-trade PnL, not derived from cash_buffer-inflated mtm_total
        realized_pnl = sum(t.get("pnl", 0) for a in self.assets.values() for t in a.trade_log)
        realized_total = tc + realized_pnl
        realized_return = (realized_total - tc) / tc * 100 if tc > 0 else 0.0

        mtm_return = (mtm_total - tc) / tc * 100 if tc > 0 else 0
        delta = datetime.now(tz=ET) - self.start_date

        # Track portfolio peak for drawdown
        if self.portfolio_peak_value is None or mtm_total > self.portfolio_peak_value:
            self.portfolio_peak_value = mtm_total
        portfolio_dd = (
            (mtm_total - self.portfolio_peak_value) / self.portfolio_peak_value if self.portfolio_peak_value else 0.0
        )

        return {
            "total_value": round(mtm_total, 2),
            "mtm_value": round(mtm_total, 2),
            "total_return": round(mtm_return, 2),
            "realized_value": round(realized_total, 2),
            "realized_return": round(realized_return, 2),
            "unrealized_pnl": round(unrealized_dollars, 2),
            "days_running": delta.days,
            "runtime_hours": round(delta.total_seconds() / 3600, 1),
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "start_datetime": self.start_date.isoformat(),
            "last_update": self.last_update.strftime("%Y-%m-%d %H:%M:%S") if self.last_update else None,
            "capital": get_config().capital,
            "allocations": {n: a.allocation for n, a in self.assets.items()},
            "deployment_cleared": True,
            "open_positions": sum(a.pos_mgr.has_position() for a in self.assets.values()),
            "closed_trades": sum(len(a.trade_log) for a in self.assets.values()),
            "execution_state": exec_state.value,
            "average_validity_exposure": round(overall_validity / n, 4),
            "satellite_allocation_pct": round(satellite_pct, 2),
            "portfolio_drawdown": round(portfolio_dd * 100, 2),
            "portfolio_peak_value": round(self.portfolio_peak_value, 2) if self.portfolio_peak_value else None,
        }

    def _satellite_snapshot(self) -> dict | None:
        if self.satellite is None:
            return None
        s = self.satellite.get_state()
        return {
            "name": self.satellite.name,
            "allocation_pct": s.allocation_pct,
            "gate_open": s.gate_open,
            "gate_reasons": s.gate_reasons,
            "current_value": s.current_value,
            "current_price": s.current_price,
            "total_return_pct": s.total_return_pct,
            "sharpe_contribution": s.sharpe_contribution,
            "position_active": s.position_active,
            "drawdown_pct": s.drawdown_pct,
            "entry_price": s.entry_price,
            "stop_price": s.stop_price,
            "target_price": s.target_price,
            "exit_reason": s.exit_reason,
        }

    def save_state(self):
        state = self.get_state()
        snapshot = EngineSnapshot(
            schema_version=EngineSnapshot.__dataclass_fields__["schema_version"].default,
            timestamp=datetime.now(tz=ET).isoformat(),
            portfolio=state.get("portfolio"),
            assets=state.get("assets"),
            open_positions={},
            engine_status={
                "initialized": True,
                "last_update": self.last_update.strftime("%Y-%m-%d %H:%M:%S") if self.last_update else None,
                "start_time": self.start_date.isoformat(),
                "satellite": state.get("satellite"),
            },
            halt_conditions=state.get("halt_conditions"),
            risk_signals={
                name: asset._risk_signal for name, asset in self.assets.items() if asset._risk_signal is not None
            }
            or None,
            shadow_actions={
                name: asset._shadow_action for name, asset in self.assets.items() if asset._shadow_action is not None
            }
            or None,
        )
        for name, asset in self.assets.items():
            if asset.pos_mgr.has_position():
                pos = asset.pos_mgr.position
                snapshot.open_positions[name] = {
                    "position": {
                        "side": pos.side,
                        "entry": pos.entry_price,
                        "sl": pos.stop_loss,
                        "tp": pos.take_profit,
                        "entry_date": pos.entry_date,
                        "vol": pos.vol,
                    },
                    "current_value": asset.pos_mgr.current_value,
                    "peak_value": asset.pos_mgr.peak_value,
                    "trade_log": asset.pos_mgr.trade_log,
                    "prob_history": asset.prob_history,
                }
        if self.satellite is not None and self.satellite.position_active:
            sat = self.satellite
            snapshot.open_positions["satellite"] = {
                "position": {
                    "side": sat.position_side,
                    "entry": sat.entry_price,
                    "sl": sat.stop_price,
                    "tp": sat.target_price,
                    "entry_date": getattr(sat, "position_entry_date", str(datetime.now(tz=ET).date())),
                    "vol": getattr(sat, "position_vol", 0.02),
                },
                "current_value": sat.current_value,
                "peak_value": sat.peak_value,
                "initial_capital": sat.initial_capital,
                "entry_capital": getattr(sat, "_entry_capital", sat.max_capital),
                "daily_returns": getattr(sat, "_daily_returns", []),
            }
        self._append_equity_history(state)
        self.state_store.save_snapshot(snapshot)
        self._capture_simulation_snapshot(state)
        self._flush_experiment_state()
        return state

    def _capture_simulation_snapshot(self, state: dict) -> None:
        """Capture per-asset simulation snapshots for replay."""
        timestamp = datetime.now(tz=ET).isoformat()
        portfolio = state.get("portfolio", {})
        assets_state = state.get("assets", {})

        asset_snapshots = []
        for name, adata in assets_state.items():
            metrics = adata.get("metrics", {})
            snap = build_asset_snapshot(
                asset_name=name,
                metrics=metrics,
                validity_state=adata.get("validity_state", "YELLOW"),
                validity_exposure=adata.get("validity_exposure", 1.0),
                meta_inference=metrics.get("meta_inference"),
                feature_stability=metrics.get("feature_stability"),
                timestamp=timestamp,
            )
            asset_snapshots.append(snap)

        satellite = state.get("satellite", {})
        satellite_value = satellite.get("current_value", 0.0) if satellite else 0.0
        cash_buffer = get_config().capital - portfolio.get("realized_value", 0) - satellite_value

        self._sim_store.capture(
            portfolio_value=portfolio.get("total_value", 0),
            total_return=portfolio.get("total_return", 0),
            cash_buffer=max(0.0, cash_buffer),
            satellite_value=satellite_value,
            asset_snapshots=asset_snapshots,
        )

    def _append_equity_history(self, state):
        p = state.get("portfolio", {})
        total_value = p.get("total_value", 0)
        total_return = p.get("total_return", 0)

        # Gross exposure should use MTM values
        gross = sum(
            a.get("metrics", {}).get("mtm_value", a.get("metrics", {}).get("current_value", 0))
            for a in state.get("assets", {}).values()
        )

        net_side = sum(
            (a.get("metrics", {}).get("position") or {}).get("side") == "long" for a in state.get("assets", {}).values()
        )
        net = (net_side / len(state.get("assets", {}))) * 2 - 1 if state.get("assets") else 0

        # Portfolio drawdown from summary
        drawdown = p.get("drawdown", 0.0)

        record = {
            "timestamp": datetime.now(tz=ET).isoformat(),
            "portfolio_value": total_value,
            "portfolio_return": total_return,
            "drawdown": drawdown,
            "gross_exposure": round(gross / total_value, 4) if total_value else 0,
            "net_exposure": round(net, 4),
            "assets": {
                name: (a.get("metrics", {}).get("mtm_value") or a.get("metrics", {}).get("current_value") or 0)
                for name, a in state.get("assets", {}).items()
            },
        }
        self.state_store.append_equity_history(record)

    def _flush_experiment_state(self) -> None:
        """Flush attribution buffer and export experiment freeze metadata."""
        # Flush any remaining attribution records from all assets
        for name, asset in self.assets.items():
            asset.flush_attribution()

        # Export experiment freeze metadata
        ctx = ExperimentContext.get()
        if ctx is not None:
            export_dir = os.path.join(BASE, "data", "research", "attribution")
            os.makedirs(export_dir, exist_ok=True)
            metadata_path = os.path.join(export_dir, f"experiment_{ctx.freeze.experiment_id}.json")
            if not os.path.exists(metadata_path):
                import json  # noqa: F401  # defer import

                with open(metadata_path, "w") as f:
                    json.dump(ctx.freeze.to_dict(), f, indent=2, default=str)
                logger.info(
                    "experiment: exported freeze metadata to %s (experiment_id=%s)",
                    metadata_path,
                    ctx.freeze.experiment_id,
                )
