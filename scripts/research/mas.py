import logging
import math

logger = logging.getLogger("eigencapital.mas")


def _safe(val, default=0.0):
    return val if val is not None else default


def _clip01(v):
    return max(0.0, min(1.0, v))


def _entropy(dist: dict) -> float:
    vals = [dist.get(k, 0) for k in ("short", "neutral", "long")]
    total = sum(vals)
    if total == 0:
        return 0.0
    probs = [v / total for v in vals]
    return -sum(p * math.log(p + 1e-12) for p in probs)


def hard_gates(
    signal_result: dict,
    portfolio_result: dict,
    model_result: dict,
    shadow_result: dict,
    forward_result: dict,
    drift_score: float | None = None,
) -> tuple[bool, list[str]]:
    failures = []

    agreement = _safe(signal_result.get("overall_agreement", 1.0))
    flip_rate = _safe(signal_result.get("flip_rate", 0.0))
    if agreement < 0.95:
        failures.append(f"Gate A: signal agreement {agreement:.4f} < 0.95")
    if "error" not in signal_result:
        pass

    bl = forward_result.get("baseline", {})
    nw = forward_result.get("new", {})
    bl_sharpe = _safe(bl.get("sharpe"))
    fw_sharpe = _safe(nw.get("sharpe"))
    if bl_sharpe != 0:
        ratio = (fw_sharpe - bl_sharpe) / abs(bl_sharpe) if abs(bl_sharpe) > 1e-9 else 0
        if ratio < -0.10:
            failures.append(f"Gate B: forward Sharpe {fw_sharpe:.4f} < baseline {bl_sharpe:.4f} - 10%")

    bl_dd = _safe(bl.get("max_drawdown"))
    fw_dd = _safe(nw.get("max_drawdown"))
    if bl_dd > 0 and fw_dd > bl_dd * 1.20:
        failures.append(f"Gate B: forward drawdown {fw_dd:.4f} > baseline {bl_dd:.4f} + 20%")

    if drift_score is not None and drift_score > 0.6:
        failures.append(f"Gate C: drift_score {drift_score:.4f} > 0.6")

    old_dist = _safe(shadow_result.get("class_distribution_shift", {}).get("old", {}))
    new_dist = _safe(shadow_result.get("class_distribution_shift", {}).get("new", {}))
    h_old = _entropy(old_dist)
    h_new = _entropy(new_dist)
    if h_old > 1e-9:
        ratio_h = h_new / h_old
        if ratio_h < 0.8 or ratio_h > 1.2:
            failures.append(f"Gate D: entropy ratio {ratio_h:.4f} outside [0.8, 1.2]")

    return len(failures) == 0, failures


def score_model(model_result: dict) -> float:
    if "error" in model_result:
        return 0.0

    old = model_result.get("old", {})
    new = model_result.get("new", {})

    old_auc = _safe(old.get("auc_macro"), 0.5)
    new_auc = _safe(new.get("auc_macro"), 0.5)
    auc_component = _clip01(new_auc - old_auc + 0.5)

    old_ll = _safe(old.get("logloss"), 1.0)
    new_ll = _safe(new.get("logloss"), 1.0)
    ll_norm = 1.0 - _clip01(new_ll / (old_ll + 1e-9))
    ll_component = _clip01(ll_norm * 0.5 + 0.5)

    old_dist = model_result.get("class_distribution", {}).get("old", {})
    new_dist = model_result.get("class_distribution", {}).get("new", {})
    stability = 1.0 - sum(abs(_safe(new_dist.get(k)) - _safe(old_dist.get(k))) for k in ("short", "neutral", "long")) / 2
    stability = _clip01(stability)

    return _clip01(
        0.3 * auc_component
        + 0.2 * ll_component
        + 0.2 * stability
        + 0.3 * stability
    )


def score_signal(signal_result: dict) -> float:
    if "error" in signal_result:
        return 0.0

    agreement = _safe(signal_result.get("overall_agreement", 1.0))
    flip_rate = _safe(signal_result.get("flip_rate", 0.0))
    conf_shift = abs(_safe(signal_result.get("mean_confidence_shift", 0.0)))

    agreement_score = _clip01((agreement - 0.5) / 0.5)
    flip_score = _clip01(1.0 - flip_rate)
    conf_stability = _clip01(1.0 - conf_shift * 10)

    reg_agree = _safe(signal_result.get("regime_stratified_agreement", {}))
    reg_vals = [v for v in reg_agree.values() if v is not None]
    if reg_vals:
        reg_instability = 1.0 - (sum(reg_vals) / len(reg_vals))
    else:
        reg_instability = 0.0

    raw = 0.5 * agreement_score + 0.3 * flip_score + 0.2 * conf_stability - 0.1 * reg_instability
    return _clip01(raw)


def score_portfolio(portfolio_result: dict) -> float:
    if "error" in portfolio_result:
        return 0.0

    old = portfolio_result.get("old", {})
    new = portfolio_result.get("new", {})

    old_ret = _safe(old.get("total_return"))
    new_ret = _safe(new.get("total_return"))
    old_dd = _safe(old.get("max_drawdown"))
    new_dd = _safe(new.get("max_drawdown"))
    old_trades = _safe(old.get("total_trades"), 1)
    new_trades = _safe(new.get("total_trades"), 1)

    max_abs_ret = max(abs(old_ret), abs(new_ret), 0.01)
    sharpe_norm = _clip01((new_ret - old_ret) / max_abs_ret + 0.5)

    max_dd = max(old_dd, new_dd, 0.01)
    dd_norm = _clip01(1.0 - (new_dd - old_dd) / max_dd)

    old_eff = (old_ret + 1.0) / max(old_trades, 1)
    new_eff = (new_ret + 1.0) / max(new_trades, 1)
    trade_eff = _clip01(new_eff / (old_eff + 1e-9))

    pnl_consistency = _clip01(1.0 - abs(new_ret - old_ret) / (abs(old_ret) + 1e-9 + max_abs_ret))

    return _clip01(
        0.4 * sharpe_norm
        + 0.3 * dd_norm
        + 0.2 * trade_eff
        + 0.1 * pnl_consistency
    )


def score_shadow(shadow_result: dict) -> float:
    if "error" in shadow_result:
        return 0.0

    entropy_shift = abs(_safe(shadow_result.get("entropy_shift")))
    drift_model = _clip01(entropy_shift * 5)

    signal_agreement = _safe(shadow_result.get("signal_agreement", 1.0))
    drift_signal = _clip01(1.0 - signal_agreement)

    old_conf = _safe(shadow_result.get("mean_confidence_old", {}))
    new_conf = _safe(shadow_result.get("mean_confidence_new", {}))
    old_avg = (old_conf.get("short", 0) + old_conf.get("long", 0)) / 2
    new_avg = (new_conf.get("short", 0) + new_conf.get("long", 0)) / 2
    pnl_error = _clip01(abs(new_avg - old_avg) * 5)

    reg_stab = _safe(shadow_result.get("regime_stability", {}))
    reg_vals = [v for v in reg_stab.values() if v is not None]
    feature_stability = sum(reg_vals) / len(reg_vals) if reg_vals else 1.0

    reg_alignment = feature_stability

    return _clip01(
        0.25 * (1.0 - drift_model)
        + 0.2 * (1.0 - drift_signal)
        + 0.2 * (1.0 - pnl_error)
        + 0.2 * feature_stability
        + 0.15 * reg_alignment
    )


def score_forward(forward_result: dict) -> float:
    if "error" in forward_result:
        return 0.0

    baseline = forward_result.get("baseline", {})
    new = forward_result.get("new", {})

    bl_sharpe = _safe(baseline.get("sharpe"))
    fw_sharpe = _safe(new.get("sharpe"))
    max_s = max(abs(bl_sharpe), abs(fw_sharpe), 0.01)
    sharpe_fw = _clip01((fw_sharpe - bl_sharpe) / max_s + 0.5)

    bl_hit = _safe(baseline.get("hit_rate"))
    fw_hit = _safe(new.get("hit_rate"))
    hit_fw = _clip01(fw_hit / (bl_hit + 0.01)) if bl_hit > 0 else _clip01(fw_hit * 2)

    bl_stab = _safe(baseline.get("stability"), 1.0)
    fw_stab = _safe(new.get("stability"), 1.0)
    stability_fw = _clip01(fw_stab / (bl_stab + 1e-9))

    return _clip01(
        0.5 * sharpe_fw
        + 0.3 * hit_fw
        + 0.2 * stability_fw
    )


def score_stress(forward_result: dict) -> float:
    if "error" in forward_result:
        return 0.0

    bl_reg = forward_result.get("baseline_regime", {})
    nw_reg = forward_result.get("new_regime", {})

    regime_scores = []
    for r in ["low_vol", "high_vol", "transition"]:
        bl_r = bl_reg.get(r, {})
        nw_r = nw_reg.get(r, {})
        d_sharpe = _safe(nw_r.get("sharpe")) - _safe(bl_r.get("sharpe"))
        d_sharpe = max(-1.0, min(1.0, d_sharpe))
        d_dd = _safe(nw_r.get("max_drawdown")) - _safe(bl_r.get("max_drawdown"))
        d_dd = max(-1.0, min(1.0, d_dd))
        regime_scores.append(d_sharpe - d_dd)

    mean_regime = sum(regime_scores) / len(regime_scores) if regime_scores else 0.0
    return _clip01(0.5 + mean_regime / 4.0)


def compute_mas(
    model_result: dict,
    signal_result: dict,
    portfolio_result: dict,
    shadow_result: dict,
    forward_result: dict,
    drift_score: float | None = None,
    baseline_mas: float | None = None,
    weights: dict | None = None,
) -> dict:
    if weights is None:
        weights = {"model": 0.22, "signal": 0.18, "portfolio": 0.20, "shadow": 0.12, "forward": 0.15, "stress": 0.13}

    gates_passed, gate_failures = hard_gates(
        signal_result, portfolio_result, model_result,
        shadow_result, forward_result, drift_score,
    )

    if not gates_passed:
        return {
            "mas": 0.0,
            "delta_mas": -_safe(baseline_mas),
            "decision": "REJECT",
            "gates_passed": False,
            "gate_failures": gate_failures,
            "sub_scores": {},
            "weights": weights,
        }

    m_model = score_model(model_result)
    m_signal = score_signal(signal_result)
    m_portfolio = score_portfolio(portfolio_result)
    m_shadow = score_shadow(shadow_result)
    m_forward = score_forward(forward_result)
    m_stress = score_stress(forward_result)

    mas = 100.0 * (
        weights["model"] * m_model
        + weights["signal"] * m_signal
        + weights["portfolio"] * m_portfolio
        + weights["shadow"] * m_shadow
        + weights["forward"] * m_forward
        + weights["stress"] * m_stress
    )

    if baseline_mas is not None:
        delta_mas = mas - baseline_mas
    else:
        delta_mas = 0.0

    if mas >= 88 and m_stress > 0.6:
        decision = "ACCEPT"
    elif mas >= 85 and m_stress > 0.6:
        decision = "DEPLOY_CANDIDATE"
    elif mas >= 85 and delta_mas > 2.0 and m_stress > 0.6:
        decision = "ACCEPT"
    elif mas >= 85 and m_stress <= 0.6:
        decision = "PROMOTE_ONLY"
    elif mas >= 70:
        decision = "SHADOW_ONLY"
    elif mas >= 50:
        decision = "RESEARCH"
    else:
        decision = "REJECT"

    return {
        "mas": round(mas, 2),
        "delta_mas": round(delta_mas, 2),
        "decision": decision,
        "gates_passed": True,
        "gate_failures": [],
        "sub_scores": {
            "model": round(m_model, 4),
            "signal": round(m_signal, 4),
            "portfolio": round(m_portfolio, 4),
            "shadow": round(m_shadow, 4),
            "forward": round(m_forward, 4),
            "stress": round(m_stress, 4),
        },
        "weights": weights,
    }
