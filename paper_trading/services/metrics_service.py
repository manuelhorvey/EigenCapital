import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from paper_trading.governance.multipliers import compute_effective_multipliers

logger = logging.getLogger("quantforge.metrics_service")

ET = pytz.timezone("US/Eastern")


class MetricsService:
    @staticmethod
    def decision_to_dict(decision, *, pos_mgr, model, name):
        pos = pos_mgr.position if pos_mgr else None
        macro_weight = None
        macro_head = getattr(model, "macro_head", None) if model else None
        if macro_head is not None:
            macro_weight = round(float(getattr(macro_head, "current_weight", 0.45)), 4)

        return {
            "asset": name,
            "signal": decision.signal,
            "confidence": decision.confidence,
            "archetype": decision.archetype,
            "macro_weight": macro_weight,
            "close_price": decision.close_price,
            "date": decision.timestamp,
            "label": decision.label,
            "position": (
                {
                    "side": pos.side if pos else None,
                    "entry": round(pos.entry_price, 4) if pos else None,
                    "sl": round(pos.stop_loss, 4) if pos else None,
                    "tp": round(pos.take_profit, 4) if pos else None,
                    "current_pnl": (round(pos_mgr.position_pnl(decision.close_price), 4) if pos else None),
                }
                if pos
                else None
            ),
        }

    @staticmethod
    def log_confidence_buckets(*, name, prob_history, state_store):
        bucket = {"asset": name, "date": str(datetime.now(tz=ET).date())}
        for p in prob_history[-20:]:
            conf = p["confidence"]
            lo = min(int(conf / 10) * 10, 90)
            hi = min(int(conf / 10 + 1) * 10, 100)
            bucket.setdefault(f"count_{lo}_{hi}", 0)
            bucket[f"count_{lo}_{hi}"] += 1
        bucket["mean_conf"] = np.mean([p["confidence"] for p in prob_history[-20:]]) if prob_history else 0
        bucket["n_signals"] = min(20, len(prob_history))
        if state_store is not None:
            state_store.append_confidence_bucket(bucket)

    @staticmethod
    def get_metrics(
        *,
        name,
        ensure_position_synced=None,
        pos_mgr,
        current_value,
        peak_value,
        initial_capital,
        model,
        trade_log,
        prob_history,
        last_signal_date,
        validity_sm,
        sl_mult,
        tp_mult,
        regime_geometry,
        governance,
        current_price,
        position,
        _meta_label_model,
        _last_meta_proba,
        _scale_out_plan,
        _last_stability,
        _last_psi_drift,
        mtm_value,
    ):
        if ensure_position_synced:
            ensure_position_synced()
        cv = current_value if not pd.isna(current_value) else initial_capital
        mtm_val = mtm_value
        pv = peak_value if not pd.isna(peak_value) else mtm_val
        dd = min(0, (mtm_val - pv) / pv) if pv > 0 else 0
        total_return = (cv - initial_capital) / initial_capital if initial_capital > 0 else 0

        monthly_pfs = []
        if trade_log:
            td = pd.DataFrame(trade_log)
            td["month"] = pd.to_datetime(td["exit_date"]).dt.to_period("M")
            for m, g in td.groupby("month"):
                profits = g[g["pnl"] > 0]["pnl"].sum()
                losses = abs(g[g["pnl"] < 0]["pnl"].sum())
                monthly_pfs.append({"month": str(m), "pf": profits / losses if losses > 0 else float("inf")})
        monthly_pf = monthly_pfs[-1]["pf"] if monthly_pfs else None

        total_profits = sum(t["pnl"] for t in trade_log if t["pnl"] > 0)
        total_losses = abs(sum(t["pnl"] for t in trade_log if t["pnl"] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float("inf") if total_profits > 0 else 0)

        win_rate = len([t for t in trade_log if t["pnl"] > 0]) / len(trade_log) if trade_log else 0
        sc = {"BUY": 0, "SELL": 0, "FLAT": 0}
        for p in prob_history:
            sc[p["signal"]] = sc.get(p["signal"], 0) + 1
        mean_conf = np.mean([p["confidence"] for p in prob_history]) if prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if pos_mgr.has_position():
            upnl = (
                pos_mgr.position_pnl(current_price) if current_price is not None and not pd.isna(current_price) else 0.0
            )
            pos_info = {
                "side": pos_mgr.position.side,
                "entry": round(pos_mgr.position.entry_price, 4),
                "sl": round(pos_mgr.position.stop_loss, 4),
                "tp": round(pos_mgr.position.take_profit, 4),
                "current_vol": round(pos_mgr.position.vol, 6),
                "unrealized_pnl": round(upnl, 2),
                "sl_mult": position.get("sl_mult") if position else None,
                "tp_mult": position.get("tp_mult") if position else None,
            }

        mtm_val = mtm_value
        mtm_return = (mtm_val - initial_capital) / initial_capital * 100 if initial_capital > 0 else 0

        mean_pl = np.mean([p["prob_long"] for p in prob_history]) if prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p["prob_short"] for p in prob_history]) if prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        exit_reasons = {}
        if trade_log:
            reasons = [t.get("reason", "unknown") for t in trade_log]
            n = len(reasons)
            exit_reasons = {
                "tp_rate": round(reasons.count("tp") / n, 4),
                "sl_rate": round(reasons.count("sl") / n, 4),
                "signal_flip_rate": round(reasons.count("signal_flip") / n, 4),
                "avg_r": round(np.mean([t.get("realized_r", 0) for t in trade_log]), 4),
            }

        archetype_stats = {}
        if trade_log:
            for t in trade_log:
                arch = t.get("archetype_at_entry", "UNKNOWN")
                if arch not in archetype_stats:
                    archetype_stats[arch] = {"n": 0, "wins": 0, "total_r": 0.0, "sl": 0, "tp": 0}
                archetype_stats[arch]["n"] += 1
                if t.get("pnl", 0) > 0:
                    archetype_stats[arch]["wins"] += 1
                archetype_stats[arch]["total_r"] += t.get("realized_r", 0)
                if t.get("reason") == "sl":
                    archetype_stats[arch]["sl"] += 1
                elif t.get("reason") == "tp":
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

        state = validity_sm.current_state.value if validity_sm else "YELLOW"
        current_sl, current_tp, _ = compute_effective_multipliers(
            base_sl=sl_mult,
            base_tp=tp_mult,
            validity_state=state,
            regime_geometry=regime_geometry,
            narrative_sl_mult=governance._narrative_sl_mult,
            liquidity_sl_mult=governance._liquidity_sl_mult,
            narrative_size_scalar=governance._narrative_size_scalar,
            liquidity_size_scalar=governance._liquidity_size_scalar,
        )

        meta_inference = None
        if _meta_label_model is not None and _last_meta_proba is not None:
            meta_inference = {
                "meta_confidence": round(_last_meta_proba, 4),
                "meta_decision": "ENTER" if _meta_label_model.should_enter(_last_meta_proba) else "BLOCK",
            }

        remaining_frac = pos_mgr.get_remaining_fraction()
        scale_out_active = (
            pos_mgr._scale_out_active if hasattr(pos_mgr, "_scale_out_active") and pos_mgr._scale_out_active else False
        )

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

        _psi = _last_psi_drift
        return {
            "asset": name,
            "current_value": round(mtm_val, 2),
            "settled_value": round(current_value, 2),
            "mtm_value": round(mtm_val, 2),
            "total_return": round(mtm_return, 2),
            "settled_return": round(total_return * 100, 2),
            "mtm_return": round(mtm_return, 2),
            "drawdown": round(dd * 100, 2),
            "profit_factor": round(pf, 2),
            "win_rate": round(win_rate * 100, 2),
            "n_trades": len(trade_log),
            "n_signals": len(prob_history),
            "signal_distribution": sc,
            "mean_confidence": round(float(mean_conf), 2),
            "mean_prob_long": round(float(mean_pl), 2),
            "mean_prob_short": round(float(mean_ps), 2),
            "current_price": round(current_price, 4) if current_price else None,
            "last_signal_date": str(last_signal_date.date()) if last_signal_date else None,
            "monthly_pf": round(float(monthly_pf), 2) if monthly_pf else None,
            "position": pos_info,
            "current_sl_mult": round(current_sl, 4),
            "current_tp_mult": round(current_tp, 4),
            "trade_log": trade_log[-10:],
            "feature_stability": {
                "jaccard_top_10": _last_stability.jaccard_top_10 if _last_stability else None,
                "spearman_rank_corr": _last_stability.spearman_rank_corr if _last_stability else None,
                "penalty": _last_stability.penalty if _last_stability else 0.0,
                "window_id": _last_stability.window_id if _last_stability else None,
            },
            "exit_reasons": exit_reasons,
            "archetype_stats": archetype_stats,
            "meta_inference": meta_inference,
            "scale_out_active": scale_out_active,
            "remaining_fraction": round(remaining_frac, 4),
            "scale_out_tiers": scale_out_tiers,
            "psi_drift": {
                "per_feature": [
                    {
                        "feature": e.feature,
                        "psi": e.psi,
                        "classification": e.classification,
                        "trend": e.trend,
                        "importance_score": e.importance_score,
                    }
                    for e in (_psi.per_feature if _psi else [])
                ],
                "worst_classification": _psi.worst_classification if _psi else "NO_DRIFT",
                "moderate_count": _psi.moderate_count if _psi else 0,
                "severe_count": _psi.severe_count if _psi else 0,
                "psi_ok": _psi.psi_ok if _psi else True,
                "penalty": _psi.penalty if _psi else 0.0,
            },
        }
