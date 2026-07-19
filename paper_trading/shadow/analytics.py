import logging
from collections import Counter

import numpy as np

from paper_trading.shadow.feedback import read_feedback
from paper_trading.shadow.learning import compile_shadow_learning

logger = logging.getLogger("eigencapital.shadow.analytics")

PAPER_PORTFOLIO = [
    "GC",
    "USDCHF",
    "USDCAD",
    "ES",
    "NQ",
    "GBPCAD",
    # "GBPNZD",  # removed 2026-06-20 — tp/sl ratio 0.33
    "NZDCAD",
    "^DJI",
    "NZDUSD",
    "GBPAUD",
    "NZDCHF",
    "CADCHF",
    "AUDUSD",
    "EURCHF",
    "EURCAD",
    "EURNZD",
    "GBPCHF",
]


def build_asset_learning_profile(asset: str, months: int = 3) -> dict | None:
    try:
        events = read_feedback(asset, months=months)
        if not events:
            return None

        n = len(events)
        agreement_scores = []
        instability_scores = []
        risk_alignment_scores = []
        action_counter: Counter = Counter()
        drift_sensitivities = []

        for e in events:
            d = e.get("derived", {})
            agreement_scores.append(d.get("agreement_score", 0.0))
            instability_scores.append(d.get("instability_index", 0.0))
            risk_alignment_scores.append(d.get("risk_alignment", 0.0))

            inputs = e.get("inputs", {})
            action = inputs.get("shadow_action", {})
            action_counter[action.get("action_type", "NONE")] += 1

            drift = inputs.get("drift", {})
            avg_drift = sum(drift.values()) / max(len(drift), 1)
            drift_sensitivities.append(avg_drift)

        avg_agreement = sum(agreement_scores) / n
        avg_instability = sum(instability_scores) / n
        avg_risk_alignment = sum(risk_alignment_scores) / n
        drift_sensitivity = sum(drift_sensitivities) / n

        action_utilization = {k: round(v / n, 4) for k, v in sorted(action_counter.items())}

        risk_overreaction_count = sum(1 for e in events if e.get("derived", {}).get("risk_alignment", 1.0) < 0.5)
        risk_overreaction_rate = risk_overreaction_count / n

        return {
            "asset": asset,
            "event_count": n,
            "avg_agreement": round(avg_agreement, 4),
            "avg_instability": round(avg_instability, 4),
            "avg_risk_alignment": round(avg_risk_alignment, 4),
            "drift_sensitivity": round(drift_sensitivity, 4),
            "risk_overreaction_rate": round(risk_overreaction_rate, 4),
            "shadow_action_utilization": action_utilization,
        }
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to build learning profile for %s: %s: %s", asset, type(e).__name__, e)
        return None


def compare_assets(months: int = 3) -> dict:
    try:
        profiles = []
        for asset in PAPER_PORTFOLIO:
            profile = build_asset_learning_profile(asset, months=months)
            if profile is not None:
                profiles.append(profile)

        profiles.sort(key=lambda p: p.get("avg_instability", 0.0))

        return {
            "month_range": f"last_{months}_months",
            "stability_ranking": [
                {
                    "asset": p["asset"],
                    "stability_score": round(1.0 - p["avg_instability"], 4),
                    "drift_sensitivity": p["drift_sensitivity"],
                    "risk_responsiveness": p["avg_risk_alignment"],
                }
                for p in profiles
            ],
            "profiles": profiles,
        }
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to compare assets: %s: %s", type(e).__name__, e)
        return {"stability_ranking": [], "profiles": []}


def compare_learning_profiles() -> dict:
    try:
        rankings = []
        for asset in PAPER_PORTFOLIO:
            compiled = compile_shadow_learning(asset)
            profile = compiled.get("learning_profile", {})
            insights = compiled.get("shadow_insights", {})
            if compiled.get("event_count", 0) == 0:
                continue
            rankings.append(
                {
                    "asset": asset,
                    "stability": profile.get("behavioral_stability", 0.0),
                    "drift_resilience": profile.get("drift_resilience", 0.0),
                    "risk_sensitivity": profile.get("risk_sensitivity", 0.0),
                    "execution_fragility": insights.get("execution_fragility_score", 0.0),
                    "dominant_failure_mode": insights.get("dominant_failure_mode", "unknown"),
                }
            )

        rankings.sort(key=lambda r: r["stability"], reverse=True)
        return {"rankings": rankings}
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to compare learning profiles: %s: %s", type(e).__name__, e)
        return {"rankings": []}


def detect_systemic_patterns() -> dict:
    try:
        all_patterns: Counter = Counter()
        fragility_scores = []
        risk_signatures = []

        for asset in PAPER_PORTFOLIO:
            compiled = compile_shadow_learning(asset)
            for p in compiled.get("latent_patterns", []):
                all_patterns[p] += 1
            fragility_scores.append(compiled.get("shadow_insights", {}).get("execution_fragility_score", 0.0))
            profile = compiled.get("learning_profile", {})
            risk_signatures.append(1.0 - profile.get("behavioral_stability", 0.0))

        global_patterns = [p for p, count in all_patterns.most_common() if count >= len(PAPER_PORTFOLIO) * 0.3]

        if not global_patterns and all_patterns:
            top = all_patterns.most_common(1)
            if top:
                global_patterns = [top[0][0]]

        sys_risk = float(np.mean(risk_signatures)) if risk_signatures else 0.0

        return {
            "global_patterns": global_patterns,
            "system_risk_signature": round(sys_risk, 4),
            "pattern_frequency": dict(all_patterns.most_common(5)),
        }
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to detect systemic patterns: %s: %s", type(e).__name__, e)
        return {"global_patterns": [], "system_risk_signature": 0.0, "pattern_frequency": {}}
