import logging
import os
from datetime import datetime

import pandas as pd
import pytz

from paper_trading.config_manager import get_config
from paper_trading.ops.experiment_context import ExperimentContext
from paper_trading.ops.simulation_snapshot import build_asset_snapshot
from paper_trading.state_store import EngineSnapshot

logger = logging.getLogger("quantforge.engine_state_service")

ET = pytz.timezone("US/Eastern")

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
                "stop_out_last_cycle": getattr(asset, "_last_stop_out_cycle", None),
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
        # Use post-sync capital as baseline so dashboard returns match
        # the actual capital used for sizing (not raw config which may
        # diverge when MT5 broker equity is synced).
        tc = sum(a.capital_base for a in engine.assets.values()) or get_config().capital or 1.0

        mtm_total = self.compute_mtm_total()
        cash_buffer = max(0, tc - mtm_total)
        mtm_total += cash_buffer

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
            "last_update": engine.last_update.strftime("%Y-%m-%d %H:%M:%S") if engine.last_update else None,
            "capital": get_config().capital,
            "allocations": {n: a.allocation for n, a in engine.assets.items()},
            "deployment_cleared": True,
            "open_positions": sum(a.pos_mgr.has_position() for a in engine.assets.values()),
            "closed_trades": sum(len(a.trade_log) for a in engine.assets.values()),
            "execution_state": exec_state.value,
            "average_validity_exposure": round(overall_validity / n, 4),
            "portfolio_drawdown": round(portfolio_dd * 100, 2),
            "portfolio_peak_value": round(engine.portfolio_peak_value, 2) if engine.portfolio_peak_value else None,
        }

    def save_state(self):
        engine = self.engine
        state = self.get_state()
        snapshot = EngineSnapshot(
            schema_version=EngineSnapshot.__dataclass_fields__["schema_version"].default,
            timestamp=datetime.now(tz=ET).isoformat(),
            portfolio=state.get("portfolio"),
            assets=state.get("assets"),
            open_positions={},
            engine_status={
                "initialized": True,
                "last_update": engine.last_update.strftime("%Y-%m-%d %H:%M:%S") if engine.last_update else None,
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
        for name, asset in engine.assets.items():
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
                    "running_mae": getattr(asset, "_running_mae", None),
                    "running_mfe": getattr(asset, "_running_mfe", None),
                    "trade_log": asset.pos_mgr.trade_log,
                    "prob_history": asset.prob_history,
                }
        self._append_equity_history(state)
        engine.state_store.save_snapshot(snapshot)
        self._capture_simulation_snapshot(state)
        self._flush_experiment_state()
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

        cash_buffer = get_config().capital - portfolio.get("realized_value", 0)

        engine._sim_store.capture(
            portfolio_value=portfolio.get("total_value", 0),
            total_return=portfolio.get("total_return", 0),
            cash_buffer=max(0.0, cash_buffer),
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
