import logging
import os
from datetime import datetime

import pandas as pd
import pytz

from paper_trading.api.common import set_mt5_status
from paper_trading.config_manager import get_config
from paper_trading.execution.gate_constants import get_sell_only_assets
from paper_trading.governance.risk import get_sell_tripwire_state
from paper_trading.metrics.engine_metrics import update_engine_metrics
from paper_trading.ops.experiment_context import ExperimentContext
from paper_trading.ops.simulation_snapshot import build_asset_snapshot
from paper_trading.performance.live_sharpe import LiveSharpeTracker
from paper_trading.state_store import EngineSnapshot

logger = logging.getLogger("quorrin.engine_state_service")

ET = pytz.timezone("US/Eastern")

_PC_FALLBACK = {
    "long": 0,
    "short": 0,
    "total": 0,
    "skew": 0.0,
    "dominant_side": "unknown",
    "threshold": 0.75,
    "alert": False,
}

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EngineStateService:
    def __init__(self, engine):
        self.engine = engine

    def compute_mtm_total(self) -> float:
        engine = self.engine
        if not hasattr(engine, "_cycle_count"):
            engine._cycle_count = 0
            engine._mtm_cache_value = None
            engine._mtm_cache_cycle = -1
        elif not hasattr(engine, "_mtm_cache_value"):
            engine._mtm_cache_value = None
            engine._mtm_cache_cycle = -1
        if engine._mtm_cache_value is not None and engine._mtm_cache_cycle == engine._cycle_count:
            return engine._mtm_cache_value
        mtm = sum(a.mtm_value for a in engine.assets.values())
        engine._mtm_cache_value = mtm
        engine._mtm_cache_cycle = engine._cycle_count
        return mtm

    def get_state(self) -> dict:
        engine = self.engine
        ad = {}
        overall_validity = 0.0
        any_halted = False
        for name, asset in engine.assets.items():
            asset.refresh_price()
            metrics = asset.get_metrics()
            halt = asset.check_halt_conditions(metrics=metrics)
            validity = asset.update_validity(halt=halt)
            overall_validity += validity.get("exposure", 0.0)
            if halt["halted"]:
                any_halted = True
            signal = dict(asset.prob_history[-1]) if asset.prob_history else None
            # signal.close_price has the signal-time price from prob_history — do not overwrite
            meta_inf = metrics.get("meta_inference") or {}
            feat_stab = metrics.get("feature_stability") or {}
            sig_flip = False
            if signal and asset.pos_mgr.has_position():
                sig_dir = 1 if signal.get("signal") == "BUY" else (-1 if signal.get("signal") == "SELL" else 0)
                pos_dir = 1 if asset.pos_mgr.position.side == "long" else -1
                sig_flip = sig_dir != 0 and pos_dir != 0 and sig_dir != pos_dir

            ad[name] = {
                "metrics": metrics,
                "halt": halt,
                "validity_state": validity.get("state", "YELLOW"),
                "validity_exposure": validity.get("exposure", 0.5),
                "last_signal": signal,
                "gate_override": halt.get("halted", False),
                "signal_flip": sig_flip,
                "final_signal": getattr(asset, "_last_final_signal", None),
                "execution_state": "HALTED" if halt["halted"] else "ACTIVE",
                "sl_mult": asset.sl_mult,
                "tp_mult": asset.tp_mult,
                "meta_confidence": meta_inf.get("meta_confidence"),
                "meta_decision": meta_inf.get("meta_decision"),
                "feature_stability_jaccard": feat_stab.get("jaccard_top_10"),
                "feature_stability_spearman": feat_stab.get("spearman_rank_corr"),
                "sell_only": name in get_sell_only_assets(),
                "tripwire_active": get_sell_tripwire_state(name, sell_only=name in get_sell_only_assets())["tripped"],
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
                "stop_out_last_cycle": getattr(asset, "_last_stop_out_cycle", None),
                "total_exits": getattr(asset, "_total_exits", 0),
                "sl_exits": getattr(asset, "_sl_exits", 0),
                "sl_hit_rate": (
                    asset._sl_exits / asset._total_exits if getattr(asset, "_total_exits", 0) > 0 else None
                ),
                "last_regime_long_prob": getattr(asset, "_last_regime_long_prob", None),
                "last_regime_label": (
                    asset._last_regime_row.regime_label
                    if getattr(asset, "_last_regime_row", None) is not None
                    else None
                ),
                "sizing_chain": getattr(asset, "_last_sizing_chain", None),
            }
        total_value = self.compute_mtm_total()
        rp_weights = {}
        rp_allocations = {}
        if engine._rebalance_weights:
            for name, asset in engine.assets.items():
                w = engine._rebalance_weights.get(name, 0.0)
                rp_weights[name] = round(w, 4)
                rp_allocations[name] = round(asset.capital_base, 2)
        return {
            "portfolio": self._compute_portfolio_summary(overall_validity, any_halted),
            "assets": ad,
            "halt_conditions": get_config().halt,
            "risk_parity": {
                "weights": rp_weights,
                "capital_allocations": rp_allocations,
                "total_value": round(total_value, 2),
            },
        }

    def _compute_portfolio_summary(self, overall_validity: float, any_halted: bool) -> dict:
        engine = self.engine
        n = len(engine.assets) or 1
        from paper_trading.engine import ExecutionState

        exec_state = (
            ExecutionState.HALTED
            if any_halted
            else (ExecutionState.PAUSED if (overall_validity / n) < 0.5 else ExecutionState.ACTIVE)
        )
        # FIXED 2026-06-22: was sum(a.capital_base) which got overwritten by
        # rebalancing, making denominator chase numerator → return ≈ 0%.
        # Now uses sum(a.initial_capital) — set once at init, never overwritten.
        # Use get_config().capital only if no assets have initial_capital yet.
        deployed = sum(a.initial_capital for a in engine.assets.values())
        tc = deployed if deployed > 0 else (get_config().capital or 1.0)

        mtm_total = self.compute_mtm_total()

        unrealized_dollars = sum(
            (a.mtm_value - (a.current_value if not pd.isna(a.current_value) else a.initial_capital))
            for a in engine.assets.values()
        )

        realized_pnl = sum(t.get("pnl", 0) for a in engine.assets.values() for t in a.trade_log)
        realized_total = tc + realized_pnl
        realized_return = (realized_total - tc) / tc * 100 if tc > 0 else 0.0

        mtm_return = (mtm_total - tc) / tc * 100 if tc > 0 else 0
        delta = datetime.now(tz=ET) - engine.start_date

        if engine.portfolio_peak_value is None or mtm_total > engine.portfolio_peak_value:
            engine.portfolio_peak_value = mtm_total
        peak = engine.portfolio_peak_value
        portfolio_dd = (mtm_total - peak) / peak if peak else 0.0

        return {
            "total_value": round(mtm_total, 2),
            "mtm_value": round(mtm_total, 2),
            "total_return": round(mtm_return, 2),
            "realized_value": round(realized_total, 2),
            "realized_return": round(realized_return, 2),
            "unrealized_pnl": round(unrealized_dollars, 2),
            "days_running": delta.days,
            "runtime_hours": round(delta.total_seconds() / 3600, 1),
            "start_date": engine.start_date.strftime("%Y-%m-%d"),
            "start_datetime": engine.start_date.isoformat(),
            "last_update": engine.last_update.isoformat() if engine.last_update else None,
            "capital": get_config().capital,
            "allocations": {n: a.allocation for n, a in engine.assets.items()},
            "deployment_cleared": True,
            "open_positions": sum(a.pos_mgr.has_position() for a in engine.assets.values()),
            "closed_trades": sum(len(a.trade_log) for a in engine.assets.values()),
            "execution_state": exec_state.value,
            "average_validity_exposure": round(overall_validity / n, 4),
            "portfolio_drawdown": round(portfolio_dd * 100, 2),
            "portfolio_peak_value": round(engine.portfolio_peak_value, 2) if engine.portfolio_peak_value else None,
            "position_concentration": getattr(
                getattr(engine, "_orchestrator", None),
                "_position_concentration",
                _PC_FALLBACK,
            )
            or _PC_FALLBACK,
            "factor_exposures": self._compute_factor_exposures(),
        }

    @staticmethod
    def _extract_pek(orch: object) -> dict:
        """Extract PEK state from orchestrator for dashboard display.

        Returns a dict with optional keys: performance_state, risk_budget,
        portfolio_snapshot.  Each sub-key is populated only if the
        corresponding orchestrator instance variable is set.
        """
        pek: dict = {}

        # PerformanceState scalars + velocity
        perf = getattr(orch, "_performance_state", None)
        if perf is not None:
            vel = getattr(perf, "velocity", None)
            pek["performance_state"] = {
                "outcome_scalar": round(perf.outcome_scalar, 4),
                "degradation_scalar": round(perf.degradation_scalar, 4),
                "market_scalar": round(perf.market_scalar, 4),
                "execution_scalar": round(perf.execution_scalar, 4),
                "velocity_scalar": round(perf.velocity_scalar, 4),
                "composite_scalar": round(perf.composite_scalar, 4),
                "win_rate_20": round(perf.win_rate_20, 4),
                "consecutive_losses": perf.consecutive_losses,
                "r_cumulative_20": round(perf.r_cumulative_20, 4),
                "calibration_ece": round(perf.calibration_ece, 6),
                "atr_ratio": round(perf.atr_ratio, 4),
                "regime_label": perf.regime_label,
                "slippage_p90": round(perf.slippage_p90, 6),
            }
            if vel is not None:
                pek["performance_state"]["velocity"] = {
                    "pnl_velocity": round(vel.pnl_velocity, 6),
                    "pnl_acceleration": round(vel.pnl_acceleration, 6),
                    "vol_velocity": round(vel.vol_velocity, 6),
                    "degradation_velocity": round(vel.degradation_velocity, 6),
                    "execution_velocity": round(vel.execution_velocity, 6),
                }

        # RiskBudget scalars
        budget = getattr(orch, "_risk_budget", None)
        if budget is not None:
            pek["risk_budget"] = {
                "max_risk_per_trade_pct": round(budget.max_risk_per_trade_pct, 4),
                "max_portfolio_heat": round(budget.max_portfolio_heat, 4),
                "max_concurrent_positions": budget.max_concurrent_positions,
                "volatility_scalar": round(budget.volatility_scalar, 4),
                "drawdown_scalar": round(budget.drawdown_scalar, 4),
                "performance_scalar": round(budget.performance_scalar, 4),
                "velocity_scalar": round(budget.velocity_scalar, 4),
            }

        # PortfolioStateSnapshot summary (scalar fields only)
        snap = getattr(orch, "_portfolio_snapshot", None)
        if snap is not None:
            pek["portfolio_snapshot"] = {
                "total_equity": round(snap.total_equity, 2),
                "drawdown_pct": round(snap.drawdown_pct, 6),
                "gross_exposure": round(snap.gross_exposure, 4),
                "net_exposure": round(snap.net_exposure, 4),
                "open_position_count": snap.open_position_count,
                "daily_pnl": round(snap.daily_pnl, 2),
                "max_daily_loss": round(snap.max_daily_loss, 2),
                "drawdown_remaining": round(snap.drawdown_remaining, 4),
                "leverage_remaining": round(snap.leverage_remaining, 4),
                "max_leverage": snap.max_leverage,
                "concurrent_remaining": snap.concurrent_remaining,
                "max_concurrent": snap.max_concurrent,
            }

        return pek

    def _compute_factor_exposures(self) -> dict:
        from shared.factor_model import summary as factor_summary

        try:
            rw = getattr(self.engine, "_rebalance_weights", None)
            if rw:
                return factor_summary(rw)
            return {"exposures": {}, "violations": {}, "n_violations": 0, "within_limits": True}
        except Exception as e:
            logger.debug("Failed to compute factor exposures: %s", e)
            return {"exposures": {}, "violations": {}, "n_violations": 0, "within_limits": True}

    def save_state(self):
        engine = self.engine
        state = self.get_state()

        # Live Sharpe from equity history
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            tracker = LiveSharpeTracker(base_dir=base)
            sharpe_data = tracker.compute()
            state["portfolio"]["live_sharpe"] = sharpe_data
        except Exception as exc:
            logger.debug("Failed to compute live Sharpe: %s", exc)
            state["portfolio"]["live_sharpe"] = {"available": False}

        # Edge health from live trade tracker
        try:
            from paper_trading.performance.edge_health import get_monitor

            monitor = get_monitor()
            state["portfolio"]["edge_health"] = monitor.summary
        except Exception as exc:
            logger.debug("Failed to compute edge health: %s", exc)
            state["portfolio"]["edge_health"] = {"available": False}

        # PEK state from orchestrator
        try:
            orch = getattr(engine, "_orchestrator", None)
            if orch is not None:
                pek_data = self._extract_pek(orch)
                if pek_data:
                    state["portfolio"]["pek"] = pek_data
                adm = getattr(orch, "_last_admission", None)
                if adm is not None:
                    state["portfolio"]["admission"] = adm
        except Exception as exc:
            logger.debug("Failed to extract PEK state: %s", exc)

        # Capture MT5 connection status for the API endpoint
        try:
            broker = getattr(engine, "broker", None)
            if broker is not None and hasattr(broker, "_client"):
                client = broker._client
                is_connected = bool(client.connected)
                last_hb = getattr(client, "_last_heartbeat", None)
                last_hb_iso = datetime.fromtimestamp(last_hb, tz=ET).isoformat() if last_hb is not None else None
                account = None
                try:
                    if is_connected:
                        raw = broker.get_account_summary()
                        account = {
                            "total_cash": raw.total_cash,
                            "buying_power": raw.buying_power,
                            "portfolio_value": raw.portfolio_value,
                            "positions": [
                                {
                                    "asset": p.asset,
                                    "quantity": p.quantity,
                                    "avg_entry_price": p.avg_entry_price,
                                    "current_price": p.current_price,
                                    "unrealized_pnl": p.unrealized_pnl,
                                    "realized_pnl": p.realized_pnl,
                                    "position_id": p.position_id,
                                }
                                for p in raw.positions
                            ],
                        }
                except Exception:
                    pass
                set_mt5_status(
                    {
                        "connected": is_connected,
                        "status": "CONNECTED" if is_connected else "DISCONNECTED",
                        "last_heartbeat": last_hb_iso,
                        "account": account,
                    }
                )
            else:
                set_mt5_status({"connected": False, "status": "DISCONNECTED", "last_heartbeat": None, "account": None})
        except Exception:
            set_mt5_status({"connected": False, "status": "ERROR", "last_heartbeat": None, "account": None})
        snapshot = EngineSnapshot(
            schema_version=EngineSnapshot.__dataclass_fields__["schema_version"].default,
            timestamp=datetime.now(tz=ET).isoformat(),
            portfolio=state.get("portfolio"),
            assets=state.get("assets"),
            open_positions={},
            engine_status={
                "initialized": True,
                "last_update": engine.last_update.isoformat() if engine.last_update else None,
                "start_time": engine.start_date.isoformat(),
            },
            halt_conditions=state.get("halt_conditions"),
            risk_signals={
                name: asset._risk_signal for name, asset in engine.assets.items() if asset._risk_signal is not None
            }
            or None,
            shadow_actions={
                name: asset._shadow_action for name, asset in engine.assets.items() if asset._shadow_action is not None
            }
            or None,
        )

        # Capture orchestrator emergency halt state for restart recovery.
        # peak_portfolio_value from the orchestrator is authoritative
        # (updated every cycle via run_once peak tracking).
        # breaker_daily_pnl is only available from CircuitBreaker.
        orch = getattr(engine, "_orchestrator", None)
        if orch is not None:
            snapshot.emergency_halt = orch._emergency_halt
            snapshot.halt_reason = orch._halt_reason.value if orch._halt_reason is not None else ""
            snapshot.halt_detail = orch._halt_detail
            snapshot.peak_portfolio_value = orch._peak_portfolio_value
            breaker = getattr(orch, "_circuit_breaker", None)
            if breaker is not None:
                _, snapshot.breaker_daily_pnl = breaker.snapshot_state()
        for name, asset in engine.assets.items():
            if asset.pos_mgr.has_position():
                pos = asset.pos_mgr.position
                ap = asset.position or {}
                layers_list: list = ap.get("layers") or []
                snapshot.open_positions[name] = {
                    "position": {
                        "side": pos.side,
                        "entry": ap.get("avg_price") or pos.entry_price,
                        "sl": pos.stop_loss,
                        "tp": pos.take_profit,
                        "entry_date": pos.entry_date,
                        "vol": ap.get("total_size") or pos.vol,
                        "mt5_ticket": ap.get("mt5_ticket"),
                        "layers": layers_list,
                        "avg_price": ap.get("avg_price") or pos.entry_price,
                        "total_size": ap.get("total_size") or pos.vol,
                        "base_entry_size": ap.get("base_entry_size") or pos.vol,
                    },
                    "current_value": asset.pos_mgr.current_value,
                    "peak_value": asset.pos_mgr.peak_value,
                    "running_mae": getattr(asset, "_running_mae", None),
                    "running_mfe": getattr(asset, "_running_mfe", None),
                    "bars_at_entry": getattr(asset, "_bars_at_entry", 0),
                    "initial_sl": getattr(asset, "_initial_sl", None),
                    "initial_tp": getattr(asset, "_initial_tp", None),
                    "trade_log": asset.pos_mgr.trade_log,
                    "prob_history": asset.prob_history,
                    "adaptive_exit_phase": getattr(getattr(asset, "_adaptive_exit_engine", None), "phase", "STATIC"),
                    "peak_mfe_r": getattr(getattr(asset, "_adaptive_exit_engine", None), "peak_mfe_r", None),
                    "sl_update_count": getattr(getattr(asset, "_adaptive_exit_engine", None), "sl_update_count", 0),
                }
        self._append_equity_history(state)
        engine.state_store.save_snapshot(snapshot)
        self._capture_simulation_snapshot(state)
        self._flush_experiment_state()

        try:
            update_engine_metrics(engine)
        except Exception:
            logger.debug("Failed to update Prometheus engine metrics", exc_info=True)

        return state

    def _capture_simulation_snapshot(self, state: dict) -> None:
        engine = self.engine
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

        cash_buffer = max(0, get_config().capital - portfolio.get("realized_value", 0))

        engine._sim_store.capture(
            portfolio_value=portfolio.get("total_value", 0),
            total_return=portfolio.get("total_return", 0),
            cash_buffer=cash_buffer,
            asset_snapshots=asset_snapshots,
        )

    def _append_equity_history(self, state):
        engine = self.engine
        p = state.get("portfolio", {})
        total_value = p.get("total_value", 0)
        total_return = p.get("total_return", 0)

        gross = sum(
            a.get("metrics", {}).get("mtm_value", a.get("metrics", {}).get("current_value", 0))
            for a in state.get("assets", {}).values()
        )

        net_side = sum(
            (a.get("metrics", {}).get("position") or {}).get("side") == "long" for a in state.get("assets", {}).values()
        )
        net = (net_side / len(state.get("assets", {}))) * 2 - 1 if state.get("assets") else 0

        drawdown = p.get("portfolio_drawdown", p.get("drawdown", 0.0))

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
        engine.state_store.append_equity_history(record)

    def _flush_experiment_state(self) -> None:
        engine = self.engine
        for name, asset in engine.assets.items():
            asset.flush_attribution()

        ctx = ExperimentContext.get()
        if ctx is not None:
            export_dir = os.path.join(BASE, "data", "research", "attribution")
            os.makedirs(export_dir, exist_ok=True)
            metadata_path = os.path.join(export_dir, f"experiment_{ctx.freeze.experiment_id}.json")
            if not os.path.exists(metadata_path):
                import json

                with open(metadata_path, "w") as f:
                    json.dump(ctx.freeze.to_dict(), f, indent=2, default=str)
                logger.info(
                    "experiment: exported freeze metadata to %s (experiment_id=%s)",
                    metadata_path,
                    ctx.freeze.experiment_id,
                )
