import logging
import math
from dataclasses import dataclass, field, fields
from typing import Any, cast

import numpy as np
import pandas as pd
import pytz

from eigencapital.domain.value_objects.statistical_metrics import (
    _moments,
    confidence_reliability_score,
    herfindahl_index,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)
from paper_trading.governance.multipliers import compute_effective_multipliers

logger = logging.getLogger("eigencapital.metrics_snapshot")

ET = pytz.timezone("US/Eastern")


@dataclass
class MetricsSnapshot:
    asset: str = ""
    current_value: float = 0.0
    settled_value: float = 0.0
    mtm_value: float = 0.0
    total_return: float = 0.0
    settled_return: float = 0.0
    mtm_return: float = 0.0
    drawdown: float = 0.0
    profit_factor: float | None = None
    win_rate: float = 0.0
    n_trades: int = 0
    n_signals: int = 0
    signal_distribution: dict = field(default_factory=lambda: {"BUY": 0, "SELL": 0, "FLAT": 0})
    mean_confidence: float = 0.0
    mean_prob_long: float = 0.0
    mean_prob_short: float = 0.0
    current_price: float | None = None
    last_signal_date: str | None = None
    monthly_pf: float | None = None
    position: dict | None = None
    current_sl_mult: float = 0.0
    current_tp_mult: float = 0.0
    trade_log: list = field(default_factory=list)
    feature_stability: dict = field(default_factory=dict)
    exit_reasons: dict = field(default_factory=dict)
    archetype_stats: dict = field(default_factory=dict)
    meta_inference: dict | None = None
    scale_out_active: bool = False
    remaining_fraction: float = 1.0
    scale_out_tiers: list | None = None
    psi_drift: dict = field(default_factory=dict)
    sharpe_ratio: float | None = None
    psr_gt_0: float | None = None
    psr_gt_1: float | None = None
    min_trl: int | None = None
    crs: float | None = None
    hhi: float | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "MetricsSnapshot":
        field_names = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in field_names}
        return cls(**kwargs)

    @classmethod
    def build(cls, engine) -> "MetricsSnapshot":
        if hasattr(engine, "_ensure_position_synced"):
            engine._ensure_position_synced()

        cv = engine.current_value if not pd.isna(engine.current_value) else engine.initial_capital
        mtm_val = engine.mtm_value
        pv = engine.peak_value if not pd.isna(engine.peak_value) else mtm_val
        dd = min(0, (mtm_val - pv) / pv) if pv > 0 else 0
        total_return = (cv - engine.initial_capital) / engine.initial_capital if engine.initial_capital > 0 else 0

        monthly_pfs = []
        if engine.trade_log:
            td = pd.DataFrame(engine.trade_log)
            td["month"] = pd.to_datetime(td["exit_date"]).dt.to_period("M")
            for m, g in td.groupby("month"):
                profits = g[g["pnl"] > 0]["pnl"].sum()
                losses = abs(g[g["pnl"] < 0]["pnl"].sum())
                monthly_pfs.append({"month": str(m), "pf": profits / losses if losses > 0 else float("inf")})
        monthly_pf = monthly_pfs[-1]["pf"] if monthly_pfs else None

        total_profits = sum(t["pnl"] for t in engine.trade_log if t["pnl"] > 0)
        total_losses = abs(sum(t["pnl"] for t in engine.trade_log if t["pnl"] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float("inf") if total_profits > 0 else 0)

        win_rate = len([t for t in engine.trade_log if t["pnl"] > 0]) / len(engine.trade_log) if engine.trade_log else 0
        sc = {"BUY": 0, "SELL": 0, "FLAT": 0}
        for p in engine.prob_history:
            sc[p["signal"]] = sc.get(p["signal"], 0) + 1
        mean_conf = np.mean([p["confidence"] for p in engine.prob_history]) if engine.prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if engine.pos_mgr.has_position():
            upnl = (
                engine.pos_mgr.position_pnl(engine.current_price)
                if engine.current_price is not None and not pd.isna(engine.current_price)
                else 0.0
            )
            pos_info = {
                "side": engine.pos_mgr.position.side,
                "entry": round(engine.pos_mgr.position.entry_price, 4),
                "sl": round(engine.pos_mgr.position.stop_loss, 4),
                "tp": round(engine.pos_mgr.position.take_profit, 4),
                "current_vol": round(engine.pos_mgr.position.vol, 6),
                "unrealized_pnl": round(upnl, 2),
                "sl_mult": engine.position.get("sl_mult") if engine.position else None,
                "tp_mult": engine.position.get("tp_mult") if engine.position else None,
            }

        mtm_return = (
            (mtm_val - engine.initial_capital) / engine.initial_capital * 100 if engine.initial_capital > 0 else 0
        )

        mean_pl = np.mean([p["prob_long"] for p in engine.prob_history]) if engine.prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p["prob_short"] for p in engine.prob_history]) if engine.prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        exit_reasons = {}
        if engine.trade_log:
            reasons = [t.get("reason", "unknown") for t in engine.trade_log]
            n = len(reasons)
            exit_reasons = {
                "tp_rate": round(reasons.count("TP") / n, 4),
                "sl_rate": round(reasons.count("SL") / n, 4),
                "trailing_sl_rate": round(reasons.count("TRAILING_SL") / n, 4),
                "breakeven_rate": round(reasons.count("BREAKEVEN") / n, 4),
                "flip_rate": round(reasons.count("FLIP") / n, 4),
                "expiry_rate": round(reasons.count("EXPIRY") / n, 4),
                "avg_r": round(np.mean([t.get("realized_r", 0) for t in engine.trade_log]), 4),
            }

        archetype_stats = {}
        if engine.trade_log:
            for t in engine.trade_log:
                arch = t.get("archetype_at_entry", "UNKNOWN")
                if arch not in archetype_stats:
                    archetype_stats[arch] = {"n": 0, "wins": 0, "total_r": 0.0, "sl": 0, "tp": 0}
                archetype_stats[arch]["n"] += 1
                if t.get("pnl", 0) > 0:
                    archetype_stats[arch]["wins"] += 1
                archetype_stats[arch]["total_r"] += t.get("realized_r", 0)
                if t.get("reason") == "SL":
                    archetype_stats[arch]["sl"] += 1
                elif t.get("reason") == "TP":
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

        state = engine.validity_sm.current_state.value if engine.validity_sm else "YELLOW"
        current_sl, current_tp, _ = compute_effective_multipliers(
            base_sl=engine.sl_mult,
            base_tp=engine.tp_mult,
            validity_state=state,
            regime_geometry=engine.regime_geometry,
            narrative_sl_mult=engine.governance._narrative_sl_mult,
            liquidity_sl_mult=engine.governance._liquidity_sl_mult,
            narrative_size_scalar=engine.governance._narrative_size_scalar,
            liquidity_size_scalar=engine.governance._liquidity_size_scalar,
        )

        stat_metrics: dict[str, float | int | None] = {
            "sharpe_ratio": None,
            "psr_gt_0": None,
            "psr_gt_1": None,
            "min_trl": None,
            "crs": None,
            "hhi": None,
        }
        if len(engine.trade_log) >= 5:
            r_vals = np.array([t.get("realized_r", 0) for t in engine.trade_log], dtype=float)
            r_trades = r_vals[r_vals != 0]
            sr = sharpe_ratio(r_vals)
            skew, ex_kurt = _moments(r_trades) if len(r_trades) > 2 else (0.0, 0.0)
            n_obs = len(r_vals)
            stat_metrics["sharpe_ratio"] = round(sr, 4)
            stat_metrics["psr_gt_0"] = round(probabilistic_sharpe_ratio(sr, n_obs, skew, ex_kurt, 0.0), 4)
            stat_metrics["psr_gt_1"] = round(probabilistic_sharpe_ratio(sr, n_obs, skew, ex_kurt, 1.0), 4)
            stat_metrics["min_trl"] = minimum_track_record_length(sr, skew, ex_kurt, 0.05)
            if len(r_trades) > 0:
                stat_metrics["hhi"] = round(herfindahl_index(r_trades), 4)
            probs_list = []
            outcomes_list = []
            for t in engine.trade_log:
                conf = t.get("pred_confidence") or t.get("conf_at_entry")
                r_trade = t.get("realized_r", 0)
                if conf is not None and conf > 0 and r_trade != 0:
                    probs_list.append(float(conf))
                    outcomes_list.append(1 if r_trade > 0 else 0)
            if len(set(outcomes_list)) > 1 and len(probs_list) >= 20:
                stat_metrics["crs"] = round(
                    confidence_reliability_score(np.array(probs_list), np.array(outcomes_list)), 4
                )

        meta_inference = None
        _meta_label_model = getattr(engine, "_meta_label_model", None)
        _last_meta_proba = getattr(engine, "_last_meta_proba", None)
        if _meta_label_model is not None and _last_meta_proba is not None:
            meta_inference = {
                "meta_confidence": round(_last_meta_proba, 4),
                "meta_decision": "ENTER" if _meta_label_model.should_enter(_last_meta_proba) else "BLOCK",
            }

        remaining_frac = engine.pos_mgr.get_remaining_fraction()
        scale_out_active = (
            engine.pos_mgr._scale_out_active
            if hasattr(engine.pos_mgr, "_scale_out_active") and engine.pos_mgr._scale_out_active
            else False
        )

        _scale_out_plan = getattr(engine, "_scale_out_plan", None)
        scale_out_tiers = None
        if _scale_out_plan is not None:
            scale_out_tiers = [
                {
                    "fraction": t.fraction,
                    "price": t.price,
                    "filled": t.filled,
                    "fill_price": t.fill_price,
                }
                for t in _scale_out_plan.tiers
            ]

        _last_stability = getattr(engine, "_last_stability", None)
        _last_psi_drift = getattr(engine, "_last_psi_drift", None)

        return cls(
            asset=engine.name,
            current_value=round(mtm_val, 2),
            settled_value=round(cv, 2),
            mtm_value=round(mtm_val, 2),
            total_return=round(mtm_return, 2),
            settled_return=round(total_return * 100, 2),
            mtm_return=round(mtm_return, 2),
            drawdown=round(dd * 100, 2),
            profit_factor=round(pf, 2) if math.isfinite(pf) else None,
            win_rate=round(win_rate * 100, 2),
            n_trades=len(engine.trade_log),
            n_signals=len(engine.prob_history),
            signal_distribution=sc,
            mean_confidence=round(float(mean_conf), 2),
            mean_prob_long=round(float(mean_pl), 2),
            mean_prob_short=round(float(mean_ps), 2),
            current_price=round(engine.current_price, 4) if engine.current_price else None,
            last_signal_date=str(engine.last_signal_date.date()) if engine.last_signal_date else None,
            monthly_pf=round(float(monthly_pf), 2) if monthly_pf else None,
            position=pos_info,
            current_sl_mult=round(current_sl, 4),
            current_tp_mult=round(current_tp, 4),
            trade_log=engine.trade_log[-10:],
            feature_stability={
                "jaccard_top_10": _last_stability.jaccard_top_10 if _last_stability else None,
                "spearman_rank_corr": _last_stability.spearman_rank_corr if _last_stability else None,
                "penalty": _last_stability.penalty if _last_stability else 0.0,
                "window_id": _last_stability.window_id if _last_stability else None,
            },
            exit_reasons=exit_reasons,
            archetype_stats=archetype_stats,
            meta_inference=meta_inference,
            scale_out_active=scale_out_active,
            remaining_fraction=round(remaining_frac, 4),
            scale_out_tiers=scale_out_tiers,
            psi_drift={
                "per_feature": [
                    {
                        "feature": e.feature,
                        "psi": e.psi,
                        "classification": e.classification,
                        "trend": e.trend,
                        "importance_score": e.importance_score,
                    }
                    for e in (_last_psi_drift.per_feature if _last_psi_drift else [])
                ],
                "worst_classification": _last_psi_drift.worst_classification if _last_psi_drift else "NO_DRIFT",
                "moderate_count": _last_psi_drift.moderate_count if _last_psi_drift else 0,
                "severe_count": _last_psi_drift.severe_count if _last_psi_drift else 0,
                "psi_ok": _last_psi_drift.psi_ok if _last_psi_drift else True,
                "penalty": _last_psi_drift.penalty if _last_psi_drift else 0.0,
            },
            sharpe_ratio=stat_metrics["sharpe_ratio"],
            psr_gt_0=stat_metrics["psr_gt_0"],
            psr_gt_1=stat_metrics["psr_gt_1"],
            min_trl=cast(int | None, stat_metrics["min_trl"]),
            crs=stat_metrics["crs"],
            hhi=stat_metrics["hhi"],
        )
