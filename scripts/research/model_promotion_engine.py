import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("quorrin.model_promotion")


def _safe(val, default=0.0):
    return val if val is not None else default


def evaluate_promotion(
    asset: str,
    mas_result: dict,
    forward_result: dict,
    model_result: dict,
    signal_result: dict,
    portfolio_result: dict,
    shadow_result: dict,
    trajectory: list[dict],
    drift_score: float | None = None,
    observe_only: bool = True,
) -> dict:
    conditions = {}
    failure_modes = []
    met_count = 0
    total = 4

    perf = _check_performance(forward_result, observe_only=observe_only)
    conditions["performance"] = perf
    if perf["met"]:
        met_count += 1
    else:
        failure_modes.extend(perf.get("failures", []))

    stab = _check_stability(mas_result, forward_result, drift_score)
    conditions["stability"] = stab
    if stab["met"]:
        met_count += 1
    else:
        failure_modes.extend(stab.get("failures", []))

    cons = _check_consistency(trajectory, mas_result)
    conditions["consistency"] = cons
    if cons["met"]:
        met_count += 1
    else:
        failure_modes.extend(cons.get("failures", []))

    safe = _check_safety(signal_result, forward_result, shadow_result, mas_result)
    conditions["safety"] = safe
    if safe["met"]:
        met_count += 1
    else:
        failure_modes.extend(safe.get("failures", []))

    if met_count == total:
        decision = "LIVE_CANDIDATE"
        confidence = round(met_count / total, 2)
    elif met_count >= total - 1:
        decision = "PAPER_TRADING_ONLY"
        confidence = round(met_count / total, 2)
    elif met_count >= total - 2:
        decision = "SHADOW_ONLY"
        confidence = round(met_count / total, 2)
    else:
        decision = "REJECT"
        confidence = round(met_count / total, 2)

    mas_val = _safe(mas_result.get("mas"))
    if mas_val >= 88 and decision != "LIVE_CANDIDATE":
        if "stability" not in [f for f in failure_modes]:
            decision = "LIVE_CANDIDATE"
            confidence = max(confidence, 0.85)

    if mas_val < 70 and decision != "REJECT":
        decision = "REJECT"
        confidence = min(confidence, 0.3)

    if not failure_modes:
        recommended = (
            "deploy_shadow_live_test_30d"
            if decision == "LIVE_CANDIDATE"
            else "deploy_paper_trading_60d"
            if decision == "PAPER_TRADING_ONLY"
            else "retain_shadow_monitoring"
            if decision == "SHADOW_ONLY"
            else "no_action_required"
        )
    else:
        recommended = "blocked_by_" + failure_modes[0].split(":")[0].strip().lower().replace(" ", "_")

    result = {
        "asset": asset,
        "timestamp": datetime.now().isoformat(),
        "decision": decision,
        "confidence": confidence,
        "conditions_met": f"{met_count}/{total}",
        "conditions": {
            k: {
                "met": v["met"],
                "details": {dk: dv for dk, dv in v.items() if dk not in ("met", "failures", "observed_failures")},
                "observed_failures": v.get("observed_failures", []),
            }
            for k, v in conditions.items()
        },
        "failure_modes": failure_modes[:5],
        "recommended_action": recommended,
    }

    result_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "sandbox",
    )
    fname = f"{asset}_promotion.json" if asset != "all" else "promotion_summary.json"
    with open(os.path.join(result_path, fname), "w") as f:
        json.dump(result, f, indent=2, default=str)

    # ── Accumulate observed statistical failures across runs ──
    obs = result.get("conditions", {}).get("performance", {}).get("observed_failures", [])
    if obs:
        obs_path = os.path.join(result_path, "observed_statistical_failures.jsonl")
        with open(obs_path, "a") as f:
            f.write(json.dumps({"asset": asset, "timestamp": result["timestamp"], "observed_failures": obs}, default=str) + "\n")

    return result


def _check_performance(forward_result: dict, observe_only: bool = True) -> dict:
    if "error" in forward_result:
        return {"met": False, "detail": "forward_test_failed", "failures": ["Performance: forward test error"]}
    bl = forward_result.get("baseline", {})
    nw = forward_result.get("new", {})
    bl_sharpe = _safe(bl.get("sharpe"))
    fw_sharpe = _safe(nw.get("sharpe"))
    bl_dd = _safe(bl.get("max_drawdown"))
    fw_dd = _safe(nw.get("max_drawdown"))
    bl_hit = _safe(bl.get("hit_rate"))
    fw_hit = _safe(nw.get("hit_rate"))

    failures = []
    sharpe_ok = fw_sharpe >= bl_sharpe - 0.05
    if not sharpe_ok:
        failures.append(f"Performance: forward Sharpe {fw_sharpe:.4f} < baseline {bl_sharpe:.4f} - 0.05")
    dd_ok = fw_dd <= bl_dd * 1.15 if bl_dd > 0 else fw_dd <= 0.1
    if not dd_ok:
        failures.append(f"Performance: forward drawdown {fw_dd:.4f} > baseline {bl_dd:.4f} * 1.15")
    hit_ok = fw_hit >= max(0.25, bl_hit - 0.10)
    if not hit_ok:
        failures.append(f"Performance: hit rate {fw_hit:.4f} too low (baseline={bl_hit:.4f})")

    # ── Statistical significance sub-checks (observe-only by default) ──
    fw_psr = _safe(nw.get("psr_gt_0"))
    fw_min_trl = _safe(nw.get("min_trl"))
    fw_n_obs = _safe(nw.get("n_obs"))
    fw_crs = _safe(nw.get("crs"))

    observed_failures: list[str] = []
    psr_ok = True
    if fw_psr > 0 and fw_psr < 0.95:
        msg = f"Performance: PSR(>0) {fw_psr:.4f} < 0.95"
        if observe_only:
            logger.warning("OBSERVE [statistical]: %s — would block if gate were active", msg)
            observed_failures.append(msg)
        else:
            psr_ok = False
            failures.append(msg)

    min_trl_ok = True
    if fw_min_trl > 0 and fw_n_obs > 0 and fw_n_obs < fw_min_trl:
        msg = f"Performance: trades {int(fw_n_obs)} < MinTRL {int(fw_min_trl)}"
        if observe_only:
            logger.warning("OBSERVE [statistical]: %s — would block if gate were active", msg)
            observed_failures.append(msg)
        else:
            min_trl_ok = False
            failures.append(msg)

    crs_ok = True
    if fw_crs > 0 and fw_crs < 0.70:
        msg = f"Performance: CRS {fw_crs:.4f} < 0.70"
        if observe_only:
            logger.warning("OBSERVE [statistical]: %s — would block if gate were active", msg)
            observed_failures.append(msg)
        else:
            crs_ok = False
            failures.append(msg)

    met = len(failures) == 0
    return {
        "met": met,
        "forward_sharpe": fw_sharpe,
        "baseline_sharpe": bl_sharpe,
        "forward_drawdown": fw_dd,
        "baseline_drawdown": bl_dd,
        "forward_hit_rate": fw_hit,
        "psr_gt_0": fw_psr if fw_psr > 0 else None,
        "min_trl": int(fw_min_trl) if fw_min_trl > 0 else None,
        "n_obs": int(fw_n_obs) if fw_n_obs > 0 else None,
        "crs": fw_crs if fw_crs > 0 else None,
        "statistical_ok": psr_ok and min_trl_ok and crs_ok,
        "observe_only": observe_only,
        "observed_failures": observed_failures,
        "failures": failures,
    }


def _check_stability(mas_result: dict, forward_result: dict, drift_score: float | None = None) -> dict:
    failures = []
    m_stress = _safe(mas_result.get("sub_scores", {}).get("stress"))
    stress_ok = m_stress >= 0.60
    if not stress_ok:
        failures.append(f"Stability: M_stress {m_stress:.4f} < 0.60")
    if drift_score is not None and drift_score > 0.6:
        failures.append(f"Stability: drift_score {drift_score:.4f} > 0.6")
    return {
        "met": len(failures) == 0,
        "m_stress": m_stress,
        "drift_score": drift_score,
        "failures": failures,
    }


def _check_consistency(trajectory: list[dict], mas_result: dict) -> dict:
    failures = []
    mas_slope = None
    mas_std = None
    if len(trajectory) >= 2:
        recent = trajectory[-min(5, len(trajectory)) :]
        mas_vals = [e["mas"] for e in recent]
        if len(mas_vals) >= 2:
            mas_slope = round((mas_vals[-1] - mas_vals[0]) / max(len(mas_vals) - 1, 1), 4)
            mas_std = round(float(__import__("numpy").std(mas_vals)), 4)
            if mas_slope < -1.0:
                failures.append(f"Consistency: MAS slope {mas_slope:.4f} < -1.0 (degrading)")
            if mas_std > 3.0:
                failures.append(f"Consistency: MAS std {mas_std:.4f} > 3.0 (high variance)")
    mas_val = _safe(mas_result.get("mas"))
    if mas_val < 70:
        failures.append(f"Consistency: MAS {mas_val:.2f} < 70 (below research threshold)")
    return {
        "met": len(failures) == 0,
        "mas_slope": mas_slope,
        "mas_std": mas_std,
        "latest_mas": mas_val,
        "failures": failures,
    }


def _check_safety(signal_result: dict, forward_result: dict, shadow_result: dict, mas_result: dict) -> dict:
    failures = []
    agreement = _safe(signal_result.get("overall_agreement", 1.0))
    if agreement < 0.95:
        failures.append(f"Safety: signal agreement {agreement:.4f} < 0.95")
    entropy_shift = abs(_safe(shadow_result.get("entropy_shift")))
    if entropy_shift > 0.10:
        failures.append(f"Safety: entropy shift {entropy_shift:.4f} > 0.10")
    regime_stab = _safe(shadow_result.get("regime_stability", {}))
    min_reg_stab = min(regime_stab.values()) if regime_stab else 0.0
    if min_reg_stab < 0.70:
        failures.append(f"Safety: min regime stability {min_reg_stab:.4f} < 0.70")
    fw_hit = _safe(forward_result.get("new", {}).get("hit_rate"))
    if fw_hit < 0.20:
        failures.append(f"Safety: forward hit rate {fw_hit:.4f} < 0.20")
    return {
        "met": len(failures) == 0,
        "signal_agreement": agreement,
        "entropy_shift": entropy_shift,
        "min_regime_stability": min_reg_stab,
        "forward_hit_rate": fw_hit,
        "failures": failures,
    }
