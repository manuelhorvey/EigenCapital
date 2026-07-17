"""Model promotion engine — evaluates whether a model is ready for live deployment."""

import json
import os
from datetime import datetime, timezone

import numpy as np

PROMOTION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sandbox")


def _check_performance(forward_result):
    """Check forward test performance conditions.

    Required: sharpe >= 80% of baseline, drawdown <= 150% of baseline, hit rate not degraded.
    """
    if "error" in forward_result:
        return {"met": False, "forward_sharpe": 0.0, "failures": ["Performance: forward test error"]}

    baseline = forward_result.get("baseline", {})
    new = forward_result.get("new", {})

    b_sharpe = baseline.get("sharpe", 0.0)
    n_sharpe = new.get("sharpe", 0.0)
    b_dd = baseline.get("max_drawdown", 0.0)
    n_dd = new.get("max_drawdown", 0.0)
    b_hit = baseline.get("hit_rate", 0.0)
    n_hit = new.get("hit_rate", 0.0)

    failures = []
    met = True

    if b_sharpe > 0 and n_sharpe < b_sharpe * 0.8:
        failures.append(f"Sharpe {n_sharpe:.3f} < 80% of baseline {b_sharpe:.3f}")
        met = False
    if b_dd > 0 and n_dd > b_dd * 1.5:
        failures.append(f"drawdown {n_dd:.3f} > 150% of baseline {b_dd:.3f}")
        met = False
    if b_hit > 0 and n_hit < b_hit * 0.8:
        failures.append(f"Hit rate {n_hit:.3f} degraded from baseline {b_hit:.3f}")
        met = False

    return {"met": met, "forward_sharpe": n_sharpe, "failures": failures}


def _check_stability(mas_result, *args, drift_score=None):
    """Check stability conditions: stress score >= 0.5, drift < 0.7."""
    sub_scores = mas_result.get("sub_scores", {})
    stress = sub_scores.get("stress", 0.0)
    failures = []
    met = True

    if stress < 0.5:
        failures.append(f"M_stress {stress:.3f} < 0.5")
        met = False
    if drift_score is not None and drift_score >= 0.7:
        failures.append(f"drift score {drift_score:.3f} >= 0.7")
        met = False

    return {"met": met, "failures": failures}


def _check_consistency(trajectory, mas_result):
    """Check trajectory consistency: slope not too negative, variance not too high, MAS >= 70."""
    if len(trajectory) < 2:
        return {"met": True, "mas_slope": None, "failures": []}

    mas_values = [t["mas"] for t in trajectory]
    current_mas = mas_result.get("mas", mas_values[-1])
    failures = []
    met = True

    # Compute slope via linear regression
    x = np.arange(len(mas_values))
    slope = np.polyfit(x, mas_values, 1)[0] if len(mas_values) >= 2 else 0.0

    # Check slope trend (negative slope indicates degradation)
    if len(mas_values) >= 3 and slope < -2.0:
        failures.append(f"MAS slope {slope:.3f} < -2.0 (degrading)")
        met = False

    # Check variance
    if len(mas_values) >= 5:
        std = float(np.std(mas_values, ddof=1))
        if std > 8.0:
            failures.append(f"MAS std {std:.3f} > 8.0 (high variance)")
            met = False

    # Check current MAS >= 70
    if current_mas < 70:
        failures.append(f"MAS {current_mas:.1f} < 70")
        met = False

    return {"met": met, "mas_slope": float(slope) if len(mas_values) >= 2 else None, "failures": failures}


def _check_safety(signal_result, forward_result, shadow_result, mas_result):
    """Check safety conditions: signal agreement, hit rate, entropy shift, regime stability."""
    failures = []
    met = True

    # Signal agreement >= 0.95
    agreement = signal_result.get("overall_agreement", 0.0)
    if agreement < 0.95:
        failures.append(f"Signal agreement {agreement:.3f} < 0.95")
        met = False

    # Hit rate >= 0.25
    new = forward_result.get("new", {})
    hit_rate = new.get("hit_rate", 0.0)
    if hit_rate < 0.25:
        failures.append(f"hit rate {hit_rate:.3f} < 0.25")
        met = False

    # Entropy shift <= 0.15
    entropy_shift = shadow_result.get("entropy_shift", 1.0)
    if entropy_shift is not None and entropy_shift > 0.15:
        failures.append(f"entropy shift {entropy_shift:.3f} > 0.15")
        met = False

    # Regime stability (all regimes >= 0.7)
    regime_stability = shadow_result.get("regime_stability", {})
    if regime_stability:
        min_stability = min(regime_stability.values())
        if min_stability < 0.7:
            failures.append(f"regime stability min {min_stability:.3f} < 0.7")
            met = False
    else:
        failures.append("Regime stability empty")
        met = False

    return {"met": met, "failures": failures}


def evaluate_promotion(
    asset,
    mas_result,
    forward_result,
    model_result,
    signal_result,
    portfolio_result,
    shadow_result,
    trajectory,
    drift_score=None,
):
    """Evaluate whether a model should be promoted to live trading.

    Runs four checks (performance, stability, consistency, safety) and
    determines a promotion decision based on MAS score and met-count:

        - LIVE_CANDIDATE: MAS >= 88 and all 4 checks pass.
        - PAPER_TRADING_ONLY: MAS >= 70 and at least 3 checks pass.
        - SHADOW_ONLY: MAS >= 50 and all 4 checks pass.
        - REJECT: Otherwise.

    Results are written to ``{PROMOTION_DIR}/{asset}_promotion.json``.

    Args:
        asset: Asset name.
        mas_result: Result dict from ``compute_mas``.
        forward_result: Forward test result dict.
        model_result: Result from ``compare_models``.
        signal_result: Result from ``compare_signals``.
        portfolio_result: Result from ``compare_portfolio``.
        shadow_result: Result from ``compare_shadow_intel``.
        trajectory: List of historical MAS trajectory entries.
        drift_score: Optional drift score for stability check.

    Returns:
        dict with keys: asset, mas, confidence, checks (dict of 4 check
        results), met_count, total_checks, decision, recommended_action,
        timestamp.
    """
    checks = {
        "performance": _check_performance(forward_result),
        "stability": _check_stability(mas_result, drift_score),
        "consistency": _check_consistency(trajectory, mas_result),
        "safety": _check_safety(signal_result, forward_result, shadow_result, mas_result),
    }

    met_count = sum(1 for c in checks.values() if c["met"])
    total = len(checks)

    mas = mas_result.get("mas", 0.0)
    conf = mas / 100.0

    # Decision logic
    if mas >= 88.0 and met_count >= total:
        decision = "LIVE_CANDIDATE"
        recommended_action = "deploy_shadow_live_test_30d"
    elif mas >= 70.0 and met_count >= total - 1:
        decision = "PAPER_TRADING_ONLY"
        recommended_action = "schedule_review_7d"
    elif mas >= 50.0 and met_count >= total:
        decision = "SHADOW_ONLY"
        recommended_action = "schedule_review_14d"
    else:
        decision = "REJECT"
        recommended_action = "blocked_by_multiple_failures" if met_count < total - 2 else "blocked_by_low_mas"

    result = {
        "asset": asset,
        "mas": mas,
        "confidence": round(conf, 4),
        "checks": checks,
        "met_count": met_count,
        "total_checks": total,
        "decision": decision,
        "recommended_action": recommended_action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Write to file
    os.makedirs(PROMOTION_DIR, exist_ok=True)
    fpath = os.path.join(PROMOTION_DIR, f"{asset}_promotion.json")
    with open(fpath, "w") as f:
        json.dump(result, f, indent=2)

    return result
