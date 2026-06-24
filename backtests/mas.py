"""Model Assessment Score (MAS) — composite model evaluation framework."""

import math

import numpy as np

# Default weights for MAS computation
DEFAULT_WEIGHTS = {
    "model": 0.20,
    "signal": 0.20,
    "portfolio": 0.20,
    "shadow": 0.15,
    "forward": 0.15,
    "stress": 0.10,
}

# Decision thresholds
ACCEPT_THRESHOLD = 85.0
SHADOW_THRESHOLD = 70.0
RESEARCH_THRESHOLD = 50.0
DEPLOY_CANDIDATE_MAX = 88.0


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _safe(value, default=0.0):
    """Return value if not None, else default."""
    return value if value is not None else default


def _clip01(value):
    """Clip value to [0, 1]."""
    return max(0.0, min(1.0, value))


def _entropy(distribution):
    """Compute entropy from a dict of class counts."""
    total = sum(distribution.values())
    if total == 0:
        return 0.0
    h = 0.0
    for v in distribution.values():
        if v > 0:
            p = v / total
            h -= p * math.log(p + 1e-12)
    return h


# ──────────────────────────────────────────────
# Scoring functions
# ──────────────────────────────────────────────


def score_model(result):
    """Score model comparison result (0-1).

    Evaluates the new model's AUC score, AUC improvement over baseline,
    and logloss improvement. Weighted: AUC (40%), AUC delta (40%),
    logloss improvement (20%).

    Args:
        result: dict from ``compare_models`` with "old" and "new" keys
            containing "auc_macro" and "logloss" sub-keys.

    Returns:
        Float score in [0, 1]. Returns 0.0 if the result contains an error.
    """
    if "error" in result:
        return 0.0
    old = result.get("old", {})
    new = result.get("new", {})
    old_auc = _safe(old.get("auc_macro", 0.5), 0.5)
    new_auc = _safe(new.get("auc_macro", 0.5), 0.5)
    old_logloss = _safe(old.get("logloss", 1.0), 1.0)
    new_logloss = _safe(new.get("logloss", 1.0), 1.0)

    # How good is the new model's AUC
    auc_score = _clip01((new_auc - 0.15) * 1.8)
    # How much did it improve
    auc_delta = _clip01((new_auc - old_auc) * 3.0 + 0.2)
    # Logloss improvement
    ll_score = _clip01(1.0 - new_logloss / old_logloss) if old_logloss > 0 else 0.5

    return _clip01(auc_score * 0.4 + auc_delta * 0.4 + ll_score * 0.2)


def score_signal(result):
    """Score signal comparison result (0-1).

    Evaluates signal agreement, flip rate, confidence stability, and
    regime-stratified agreement. Weighted: agreement (30%), flip rate (25%),
    confidence shift (20%), regime agreement (25%).

    Args:
        result: dict from ``compare_signals`` with "overall_agreement",
            "flip_rate", "mean_confidence_shift", "regime_stratified_agreement".

    Returns:
        Float score in [0, 1]. Returns 0.0 if the result contains an error.
    """
    if "error" in result:
        return 0.0
    agreement = _safe(result.get("overall_agreement", 0.5), 0.5)
    flip_rate = _safe(result.get("flip_rate", 0.5), 0.5)
    conf_shift = abs(_safe(result.get("mean_confidence_shift", 0.0), 0.0))
    regime_agreement = result.get("regime_stratified_agreement", {})

    agreement_score = _clip01(agreement)
    flip_score = _clip01(1.0 - flip_rate)
    conf_score = _clip01(1.0 - conf_shift)

    regime_score = 1.0
    if regime_agreement:
        regime_score = float(np.mean(list(regime_agreement.values())))

    return _clip01(agreement_score * 0.3 + flip_score * 0.25 + conf_score * 0.2 + regime_score * 0.25)


def score_portfolio(result):
    """Score portfolio comparison result (0-1).

    Evaluates new portfolio return, return improvement over baseline,
    and drawdown. Weighted: return level (30%), return delta (40%),
    drawdown (30%).

    Args:
        result: dict from ``compare_portfolio`` with "old" and "new"
            containing "total_return" and "max_drawdown".

    Returns:
        Float score in [0, 1]. Returns 0.0 if the result contains an error.
    """
    if "error" in result:
        return 0.0
    old = result.get("old", {})
    new = result.get("new", {})
    old_return = _safe(old.get("total_return", 0.0), 0.0)
    new_return = _safe(new.get("total_return", 0.0), 0.0)
    old_dd = _safe(old.get("max_drawdown", 0.2), 0.2)
    new_dd = _safe(new.get("max_drawdown", 0.2), 0.2)

    return_score = _clip01(new_return * 5.0 + 0.5)
    improvement = new_return - old_return
    delta_score = _clip01(improvement * 15.0 + 0.6)
    dd_score = _clip01(1.0 - new_dd + max(old_dd - new_dd, 0.0) * 2.0)

    return _clip01(return_score * 0.3 + delta_score * 0.4 + dd_score * 0.3)


def score_shadow(result):
    """Score shadow intel comparison result (0-1)."""
    if "error" in result:
        return 0.0
    entropy_shift = abs(_safe(result.get("entropy_shift", 0.0), 0.0))
    signal_agreement = _safe(result.get("signal_agreement", 0.5), 0.5)
    regime_stability = result.get("regime_stability", {})

    entropy_score = _clip01(1.0 - entropy_shift)
    agreement_score = _clip01(signal_agreement)

    stability_score = 1.0
    if regime_stability:
        stability_score = float(np.mean(list(regime_stability.values())))

    return _clip01(entropy_score * 0.3 + agreement_score * 0.3 + stability_score * 0.4)


def score_forward(result):
    """Score forward test comparison result (0-1).

    Evaluates forward test Sharpe, Sharpe improvement, hit rate, and
    stability. Weighted: Sharpe delta (30%), Sharpe level (30%),
    hit rate (20%), stability (20%).

    Args:
        result: dict from forward test with "baseline" and "new"
            containing "sharpe", "hit_rate", "stability".

    Returns:
        Float score in [0, 1]. Returns 0.0 if the result contains an error.
    """
    if "error" in result:
        return 0.0
    baseline = result.get("baseline", {})
    new = result.get("new", {})
    b_sharpe = _safe(baseline.get("sharpe", 0.0), 0.0)
    n_sharpe = _safe(new.get("sharpe", 0.0), 0.0)
    b_hit = _safe(baseline.get("hit_rate", 0.0), 0.0)
    n_hit = _safe(new.get("hit_rate", 0.0), 0.0)
    n_stab = _safe(new.get("stability", 0.0), 0.0)

    # Direct sharpe score
    sharpe_score = _clip01(n_sharpe * 0.5 + 0.5)
    # Improvement
    sharpe_delta = _clip01((n_sharpe - b_sharpe) * 3.0 + 0.5)
    hit_score = _clip01(n_hit * 2.0)
    if b_hit == 0.0 and n_hit > 0:
        hit_score = _clip01(0.5 + n_hit)
    stab_score = _clip01(n_stab * 0.8 + 0.2)

    return _clip01(sharpe_delta * 0.3 + sharpe_score * 0.3 + hit_score * 0.2 + stab_score * 0.2)


def score_stress(result):
    """Score stress test result (0-1). 0.5 = equal performance.

    Compares Sharpe by regime between baseline and new model. The score
    is the mean regime-level delta (new - baseline) mapped through
    ``clip01(delta * 0.7 + 0.5)``.

    Args:
        result: dict with "baseline_regime" and "new_regime" keys,
            each mapping regime name to {"sharpe": ..., "max_drawdown": ...}.

    Returns:
        Float score in [0, 1]. Returns 0.0 on error, 0.5 if no regimes.
    """
    if "error" in result:
        return 0.0
    baseline_regime = result.get("baseline_regime", {})
    new_regime = result.get("new_regime", {})

    all_regimes = set(baseline_regime.keys()) | set(new_regime.keys())
    if not all_regimes:
        return 0.5

    scores = []
    for regime in all_regimes:
        b = baseline_regime.get(regime, {"sharpe": 0.5, "max_drawdown": 0.2})
        n = new_regime.get(regime, {"sharpe": 0.5, "max_drawdown": 0.2})
        b_sharpe = _safe(b.get("sharpe", 0.5), 0.5)
        n_sharpe = _safe(n.get("sharpe", 0.5), 0.5)
        # Score based on sharpe delta from baseline; 0.5 = identical performance
        delta = n_sharpe - b_sharpe
        regime_score = _clip01(delta * 0.7 + 0.5)
        scores.append(regime_score)

    return float(np.mean(scores)) if scores else 0.5


# ──────────────────────────────────────────────
# Hard gates
# ──────────────────────────────────────────────


def hard_gates(
    signal_result,
    portfolio_result,
    model_result,
    shadow_result,
    forward_result,
    drift_score=None,
):
    """Check hard gates that must all pass for MAS to be valid.

    Gates:
        A — Signal agreement >= 0.95, flip rate <= 0.10.
        B — Forward Sharpe >= 80% of baseline, drawdown <= 150%.
        C — Drift score < 0.7 (if provided).
        D — Shadow class-distribution entropy ratio in [0.8, 1.2].

    Args:
        signal_result: Result dict from ``compare_signals``.
        portfolio_result: Result dict from ``compare_portfolio``.
        model_result: Result dict from ``compare_models``.
        shadow_result: Result dict from ``compare_shadow_intel``.
        forward_result: Result dict with "baseline" and "new" sub-dicts.
        drift_score: Optional float drift score to check against Gate C.

    Returns:
        Tuple of (passed: bool, failures: list of str).
    """
    failures = []

    # Gate A: Signal agreement >= 0.95, flip_rate <= 0.10
    agreement = signal_result.get("overall_agreement", 0)
    flip_rate = signal_result.get("flip_rate", 1)
    if agreement < 0.95:
        failures.append(f"Gate A: signal agreement {agreement:.3f} < 0.95")
    if flip_rate > 0.10:
        failures.append(f"Gate A: flip rate {flip_rate:.3f} > 0.10")

    # Gate B: Forward test Sharpe >= 80% of baseline, drawdown <= 150% of baseline
    fwd_baseline = forward_result.get("baseline", {})
    fwd_new = forward_result.get("new", {})
    b_sharpe = fwd_baseline.get("sharpe", 0)
    n_sharpe = fwd_new.get("sharpe", 0)
    b_dd = fwd_baseline.get("max_drawdown", 0)
    n_dd = fwd_new.get("max_drawdown", 0)

    if b_sharpe > 0 and n_sharpe < b_sharpe * 0.8:
        failures.append(f"Gate B: new sharpe {n_sharpe:.3f} < 80% of baseline {b_sharpe:.3f}")
    if b_dd > 0 and n_dd > b_dd * 1.5:
        failures.append(f"Gate B: new drawdown {n_dd:.3f} > 150% of baseline {b_dd:.3f}")

    # Gate C: Drift score < 0.7
    if drift_score is not None and drift_score >= 0.7:
        failures.append(f"Gate C: drift score {drift_score:.3f} >= 0.7")

    # Gate D: Shadow class distribution entropy ratio within [0.8, 1.2]
    shadow_cds = shadow_result.get("class_distribution_shift", {})
    old_dist = shadow_cds.get("old", {})
    new_dist = shadow_cds.get("new", {})
    if old_dist and new_dist:
        old_entropy = _entropy(old_dist)
        new_entropy = _entropy(new_dist)
        if old_entropy > 0:
            ratio = new_entropy / old_entropy
            if ratio < 0.8 or ratio > 1.2:
                failures.append(f"Gate D: entropy ratio {ratio:.3f} outside [0.8, 1.2]")

    return len(failures) == 0, failures


# ──────────────────────────────────────────────
# MAS computation
# ──────────────────────────────────────────────


def compute_mas(
    model_result,
    signal_result,
    portfolio_result,
    shadow_result,
    forward_result,
    baseline_mas=None,
    weights=None,
):
    """Compute Model Assessment Score (0-100).

    Combines six sub-scores (model, signal, portfolio, shadow, forward,
    stress) via configurable weights. After scoring, hard gates are
    checked — if any gate fails, MAS is set to 0.0 and the decision
    is "REJECT". Otherwise the final MAS score determines the decision
    tier: DEPLOY_CANDIDATE (>= 85 and < 88 with stress > 0.6), ACCEPT (>= 85 otherwise),
    SHADOW_ONLY (>= 70), RESEARCH (>= 50), or REJECT (< 50).

    Args:
        model_result: Result from ``compare_models``.
        signal_result: Result from ``compare_signals``.
        portfolio_result: Result from ``compare_portfolio``.
        shadow_result: Result from ``compare_shadow_intel``.
        forward_result: Forward test result dict.
        baseline_mas: Optional prior MAS for delta computation.
        weights: Optional dict of {component: weight}. Defaults to
            ``DEFAULT_WEIGHTS``.

    Returns:
        dict with keys: mas, delta_mas, decision, gates_passed,
        sub_scores, weights, and optional gate_failures.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    s_model = score_model(model_result)
    s_signal = score_signal(signal_result)
    s_portfolio = score_portfolio(portfolio_result)
    s_shadow = score_shadow(shadow_result)
    s_forward = score_forward(forward_result)
    s_stress = score_stress(forward_result)

    sub_scores = {
        "model": s_model,
        "signal": s_signal,
        "portfolio": s_portfolio,
        "shadow": s_shadow,
        "forward": s_forward,
        "stress": s_stress,
    }

    mas = (
        weights["model"] * s_model
        + weights["signal"] * s_signal
        + weights["portfolio"] * s_portfolio
        + weights["shadow"] * s_shadow
        + weights["forward"] * s_forward
        + weights["stress"] * s_stress
    ) * 100.0

    # Check gates
    gates_passed, gate_failures = hard_gates(
        signal_result=signal_result,
        portfolio_result=portfolio_result,
        model_result=model_result,
        shadow_result=shadow_result,
        forward_result=forward_result,
    )

    if not gates_passed:
        return {
            "mas": 0.0,
            "delta_mas": round(-(baseline_mas or 0.0), 2),
            "decision": "REJECT",
            "gates_passed": False,
            "sub_scores": sub_scores,
            "weights": weights,
            **({"gate_failures": gate_failures} if gate_failures else {}),
        }

    # Decision based on MAS
    if mas >= ACCEPT_THRESHOLD:
        decision = "DEPLOY_CANDIDATE" if mas < DEPLOY_CANDIDATE_MAX and s_stress > 0.6 else "ACCEPT"
    elif mas >= SHADOW_THRESHOLD:
        decision = "SHADOW_ONLY"
    elif mas >= RESEARCH_THRESHOLD:
        decision = "RESEARCH"
    else:
        decision = "REJECT"

    delta = round(mas - (baseline_mas or mas), 2)

    return {
        "mas": round(mas, 2),
        "delta_mas": delta,
        "decision": decision,
        "gates_passed": True,
        "sub_scores": sub_scores,
        "weights": weights,
    }
