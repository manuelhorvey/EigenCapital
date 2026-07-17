import logging
from datetime import datetime

import pandas as pd
import pytz

logger = logging.getLogger("eigencapital.governance_service")

ET = pytz.timezone("US/Eastern")


class GovernanceService:
    @staticmethod
    def update_validity(
        *,
        name: str,
        halt: dict | None,
        check_halt_conditions,
        validity_sm,
        last_stability,
        last_psi_drift,
    ):
        halt = check_halt_conditions() if halt is None else halt
        score = 0.80
        if not halt["drawdown_ok"]:
            score -= 0.25
        if not halt["monthly_pf_ok"]:
            score -= 0.20
        if not halt["drought_ok"]:
            score -= 0.15
        if not halt["drift_ok"]:
            score -= 0.15
        if not halt.get("liquidity_ok", True):
            score -= 0.10

        if last_stability is not None:
            penalty = last_stability.penalty
            if penalty < 0:
                logger.info(
                    "%s stability penalty: %.3f (jaccard=%.3f, spearman=%.3f)",
                    name,
                    penalty,
                    last_stability.jaccard_top_10,
                    last_stability.spearman_rank_corr,
                )
                score += penalty

        if last_psi_drift is not None and last_psi_drift.penalty < 0:
            psi_p = last_psi_drift.penalty
            logger.info(
                "%s PSI drift penalty: %.3f (worst=%s, moderate=%d, severe=%d)",
                name,
                psi_p,
                last_psi_drift.worst_classification,
                last_psi_drift.moderate_count,
                last_psi_drift.severe_count,
            )
            score += psi_p

        score = max(0.0, min(1.0, score))
        result = validity_sm.transition(score, pd.Timestamp.now(tz=ET))
        result["feature_stability"] = {
            "jaccard_top_10": last_stability.jaccard_top_10 if last_stability else None,
            "spearman_rank_corr": last_stability.spearman_rank_corr if last_stability else None,
            "penalty_applied": last_stability.penalty if last_stability else 0.0,
        }
        result["psi_drift"] = {
            "worst_classification": last_psi_drift.worst_classification if last_psi_drift else "NO_DRIFT",
            "moderate_count": last_psi_drift.moderate_count if last_psi_drift else 0,
            "severe_count": last_psi_drift.severe_count if last_psi_drift else 0,
            "penalty_applied": last_psi_drift.penalty if last_psi_drift else 0.0,
        }
        return result

    @staticmethod
    def check_halt_conditions(
        *,
        get_metrics,
        name: str,
        halt_config: dict,
        last_signal_date,
        prob_history: list,
        governance,
        last_psi_drift,
    ):
        metrics = get_metrics()
        dd = metrics.get("drawdown", 0) / 100
        if pd.isna(dd):
            dd = 0
        hc = halt_config
        hard_reasons = []
        soft_warnings = []
        logger.debug(
            "%s halt check: dd=%.4f mpf=%s drought_date=%s prob_n=%d mean_conf=%.2f liq_halted=%s",
            name,
            dd,
            metrics.get("monthly_pf"),
            metrics.get("last_signal_date"),
            len(prob_history),
            metrics.get("mean_confidence", 0),
            governance._liquidity_halted,
        )
        if dd <= hc["drawdown"]:
            hard_reasons.append(f"DD {metrics['drawdown']:.1f}% <= {hc['drawdown'] * 100:.0f}%")
        mpf = metrics.get("monthly_pf")
        if mpf is not None and not pd.isna(mpf) and mpf < hc["monthly_pf"]:
            hard_reasons.append(f"PF {mpf:.2f} < {hc['monthly_pf']:.2f}")
        drought_ok = True
        drought_days = hc.get("signal_drought", 30)
        if last_signal_date is not None:
            days_since = (datetime.now(tz=ET).date() - pd.Timestamp(last_signal_date).date()).days
            if days_since > drought_days:
                hard_reasons.append(f"Signal drought: {days_since}d > {drought_days}d")
                drought_ok = False
        drift_ok = True
        prob_drift_min_samples = hc.get("prob_drift_min_samples", 10)
        if len(prob_history) >= prob_drift_min_samples:
            prob_drift_limit = hc.get("prob_drift", 0.25)
            mean_conf = metrics.get("mean_confidence", 0) / 100
            if pd.isna(mean_conf):
                mean_conf = 0

            # Compare mean confidence against actual win rate instead of a static 0.65.
            # The static comparison falsely flags directionally-skewed models (e.g.,
            # SELL_ONLY assets, NZDCAD with mean_conf~0.31) as drifting even when
            # confidence matches performance. Using win_rate as the anchor measures
            # whether the model's average signal confidence aligns with its accuracy.
            n_trades = metrics.get("n_trades", 0)
            if n_trades >= prob_drift_min_samples:
                win_rate = metrics.get("win_rate", 0) / 100
                if pd.isna(win_rate):
                    win_rate = 0
                drift = abs(mean_conf - win_rate)
                anchor_label = f"win_rate={win_rate:.3f}"
            else:
                # Not enough trades — fall back to static comparison
                expected_prob_conf = hc.get("expected_prob_conf", 0.65)
                drift = abs(mean_conf - expected_prob_conf)
                anchor_label = f"expected={expected_prob_conf:.2f}"

            logger.debug(
                "%s drift check: n=%d mean_conf=%.3f %s drift=%.3f limit=%.3f",
                name,
                len(prob_history),
                mean_conf,
                anchor_label,
                drift,
                prob_drift_limit,
            )
            if drift > prob_drift_limit:
                soft_warnings.append(f"Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}")
                drift_ok = False
                logger.info(
                    "%s confidence drift: drift=%.3f limit=%.2f (soft, penalty -0.15)",
                    name,
                    drift,
                    prob_drift_limit,
                )

        narrative_ok = True
        narr_warnings = governance.narrative_warnings()
        if narr_warnings:
            soft_warnings.extend(narr_warnings)

        liquidity_ok = True
        liq_warnings = governance.liquidity_warnings()
        if liq_warnings:
            if governance._liquidity_halted:
                hard_reasons.extend(liq_warnings)
                liquidity_ok = False
            else:
                soft_warnings.extend(liq_warnings)
                logger.info("%s liquidity soft: %s", name, "; ".join(liq_warnings))

        psi_ok = True
        if last_psi_drift is not None and not last_psi_drift.psi_ok:
            hard_reasons.append(
                f"PSI drift SEVERE on {last_psi_drift.severe_count} features "
                f"(worst={last_psi_drift.worst_classification})"
            )
            psi_ok = False

        halted = len(hard_reasons) > 0
        if halted:
            logger.info("%s halted: %s", name, "; ".join(hard_reasons))
        return {
            "halted": halted,
            "reasons": [*hard_reasons, *soft_warnings],
            "hard_reasons": hard_reasons,
            "soft_warnings": soft_warnings,
            "drawdown_ok": dd > hc["drawdown"],
            "monthly_pf_ok": mpf is None or pd.isna(mpf) or mpf >= hc["monthly_pf"],
            "drought_ok": drought_ok,
            "drift_ok": drift_ok,
            "narrative_ok": narrative_ok,
            "liquidity_ok": liquidity_ok,
            "psi_ok": psi_ok,
        }
