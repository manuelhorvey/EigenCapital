"""RiskRegistry — thread-safe per-instance risk state container.

Extracts the global dict/lock pattern from risk.py into an
instantiable class so that tests, replay, and multi-engine
setups can each hold their own isolated risk state.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

from eigencapital.domain.time import utc_now_iso
from paper_trading.governance.drift import get_shadow_intelligence

logger = logging.getLogger("eigencapital.risk_registry")

SELL_WIN_RATE_WINDOW = 20
TRIPWIRE_THRESHOLD = 0.65

WEIGHTS = {
    "model_drift": 0.25,
    "signal_drift": 0.20,
    "pnl_drift": 0.25,
    "feature_stability": 0.15,
    "regime_consistency": 0.15,
}

FLAG_THRESHOLD = 0.3

SL_HIT_RATE_WINDOW = 20
SL_HIT_RATE_ALERT = 0.40
SL_HIT_RATE_CRITICAL = 0.55


class RiskRegistry:
    """Per-instance risk state with thread-safe access.

    Each instance carries its own cache, SL hit-rate tracker, and
    SELL tripwire state — fully isolated from other instances.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._MAX_CACHE_SIZE = 500

        self._sl_hit_rates: dict[str, deque] = {}
        self._sl_hit_rate_lock = threading.Lock()

        self._sell_win_rates: dict[str, deque] = {}
        self._sell_win_rate_lock = threading.Lock()
        self._tripwire_last_state: dict[str, bool] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all cached state."""
        with self._lock:
            self._cache.clear()
        with self._sl_hit_rate_lock:
            self._sl_hit_rates.clear()
        with self._sell_win_rate_lock:
            self._sell_win_rates.clear()
        self._tripwire_last_state.clear()

    # ── SL hit rate tracking ─────────────────────────────────────────────

    def record_trade_outcome(self, asset: str, reason: str) -> None:
        """Record a trade exit reason for SL hit rate tracking."""
        with self._sl_hit_rate_lock:
            if asset not in self._sl_hit_rates:
                self._sl_hit_rates[asset] = deque(maxlen=SL_HIT_RATE_WINDOW)
            self._sl_hit_rates[asset].append(1 if reason.upper() == "SL" else 0)

    def get_sl_hit_rate(self, asset: str) -> float | None:
        """Return the SL hit rate over the last N trades."""
        with self._sl_hit_rate_lock:
            dq = self._sl_hit_rates.get(asset)
            if dq is None or len(dq) < 5:
                return None
            return sum(dq) / len(dq)

    def get_sl_hit_rate_all(self) -> dict[str, float]:
        """Return SL hit rate for all tracked assets."""
        with self._sl_hit_rate_lock:
            return {a: sum(dq) / len(dq) for a, dq in self._sl_hit_rates.items() if len(dq) >= 5}

    # ── SELL tripwire ────────────────────────────────────────────────────

    def record_sell_side_outcome(self, asset: str, reason: str, side: str) -> None:
        if side != "short":
            return
        # Force-close reasons (PEK budget overrun, circuit breaker, manual)
        # are treated as SL losses for tripwire tracking — a position closed
        # by the system's risk controls is a losing exit by definition.
        loss_reasons = frozenset(
            {
                "SL",
                "PEK_BUDGET_OVERRUN",
                "CIRCUIT_BREAKER",
                "DRAWDOWN_CIRCUIT_BREAKER",
                "MANUAL",
            }
        )
        tp_reasons = frozenset({"TP"})
        reason_upper = reason.upper()
        if reason_upper not in tp_reasons and reason_upper not in loss_reasons:
            return
        # Normalize to TP (win) or SL (loss) for deque and win-rate computation
        normalized_reason = "TP" if reason_upper in tp_reasons else "SL"

        with self._sell_win_rate_lock:
            if asset not in self._sell_win_rates:
                self._sell_win_rates[asset] = deque(maxlen=SELL_WIN_RATE_WINDOW)
            self._sell_win_rates[asset].append(1 if normalized_reason == "TP" else 0)

            dq = self._sell_win_rates[asset]
            n = len(dq)
            win_rate = sum(dq) / n if n >= 5 else None

        if win_rate is not None and win_rate < TRIPWIRE_THRESHOLD:
            prev = self._tripwire_last_state.get(asset, False)
            if not prev:
                logger.warning(
                    "SELL tripwire TRIPPED for %s: win_rate=%.1f%% (%d trades, threshold=%.0f%%). "
                    "Re-investigate: model may have flipped or calibration shifted.",
                    asset,
                    win_rate * 100,
                    n,
                    TRIPWIRE_THRESHOLD * 100,
                )
            self._tripwire_last_state[asset] = True
        else:
            if self._tripwire_last_state.get(asset, False):
                logger.info(
                    "SELL tripwire CLEARED for %s: win_rate=%.1f%%",
                    asset,
                    win_rate * 100 if win_rate is not None else 0,
                )
            self._tripwire_last_state[asset] = False

    def get_sell_win_rate(self, asset: str) -> float | None:
        """Return SELL win rate over the last N trades, or None if <5 trades."""
        with self._sell_win_rate_lock:
            dq = self._sell_win_rates.get(asset)
            if dq is None or len(dq) < 5:
                return None
            return sum(dq) / len(dq)

    def get_sell_tripwire_state(self, asset: str, sell_only: bool = False) -> dict:
        win_rate = self.get_sell_win_rate(asset)
        tripped = sell_only and win_rate is not None and win_rate < TRIPWIRE_THRESHOLD
        return {"win_rate": win_rate, "tripped": tripped}

    # ── Risk evaluation ──────────────────────────────────────────────────

    def evaluate(self, asset: str) -> dict:
        try:
            intelligence = get_shadow_intelligence(asset)
            drift_scores = intelligence.get("drift_scores", {})
            details = intelligence.get("details", {})

            risk_score = sum(drift_scores.get(k, 0.0) * v for k, v in WEIGHTS.items())

            sl_rate = self.get_sl_hit_rate(asset)
            if sl_rate is not None:
                if sl_rate > SL_HIT_RATE_CRITICAL:
                    risk_score += 0.30
                    details["sl_hit_rate_risk"] = "CRITICAL"
                elif sl_rate > SL_HIT_RATE_ALERT:
                    risk_score += 0.15
                    details["sl_hit_rate_risk"] = "ELEVATED"
                details["sl_hit_rate"] = round(sl_rate, 4)
                details["sl_hit_rate_window"] = SL_HIT_RATE_WINDOW

            sell_wr = self.get_sell_win_rate(asset)
            if sell_wr is not None and sell_wr < TRIPWIRE_THRESHOLD:
                risk_score += 0.25
                details["sell_tripwire_risk"] = "TRIPPED"
                details["sell_win_rate"] = round(sell_wr, 4)

            if risk_score < 0.3:
                risk_level = "LOW"
            elif risk_score < 0.6:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"

            exposure_multiplier = max(0.0, 1.0 - risk_score)

            risk_flags = []
            for key, threshold in [
                ("model_drift", FLAG_THRESHOLD),
                ("signal_drift", FLAG_THRESHOLD),
                ("pnl_drift", FLAG_THRESHOLD),
                ("feature_stability", FLAG_THRESHOLD),
                ("regime_consistency", FLAG_THRESHOLD),
            ]:
                if drift_scores.get(key, 0.0) > threshold:
                    flag_map = {
                        "model_drift": "MODEL_DRIFT",
                        "signal_drift": "SIGNAL_INSTABILITY",
                        "pnl_drift": "PNL_DEGRADATION",
                        "feature_stability": "FEATURE_UNSTABLE",
                        "regime_consistency": "REGIME_SHIFT",
                    }
                    risk_flags.append(flag_map[key])

            if sl_rate is not None:
                if sl_rate > SL_HIT_RATE_CRITICAL:
                    risk_flags.append("EXCESSIVE_SL_HITS")
                elif sl_rate > SL_HIT_RATE_ALERT:
                    risk_flags.append("ELEVATED_SL_HITS")

            if sell_wr is not None and sell_wr < TRIPWIRE_THRESHOLD:
                risk_flags.append("SELL_TRIPWIRE")

            recommended_action = self._recommend(risk_level, risk_flags)
            explanations = self._generate_explanations(drift_scores, risk_flags, sl_rate, sell_wr)

            signal = {
                "asset": asset,
                "timestamp": utc_now_iso(),
                "risk_level": risk_level,
                "risk_score": round(risk_score, 4),
                "confidence": round(1.0 - risk_score, 4),
                "exposure_multiplier": round(exposure_multiplier, 4),
                "risk_flags": risk_flags,
                "recommended_action": recommended_action,
                "explanations": explanations,
                "component_scores": {k: round(drift_scores.get(k, 0.0), 4) for k in WEIGHTS},
                "drift_details": details,
            }

            with self._lock:
                self._cache[asset] = signal
                if len(self._cache) > self._MAX_CACHE_SIZE:
                    self._cache.clear()
                    logger.warning(
                        "risk cache exceeded %d entries — clearing",
                        self._MAX_CACHE_SIZE,
                    )

            return signal
        except Exception:
            logger.exception("risk_registry.evaluate(%s) failed — returning fallback signal", asset)
            try:
                from paper_trading.alerting.manager import Severity, global_alert_manager

                global_alert_manager().alert(
                    severity=Severity.CRITICAL,
                    title=f"Risk governor failed for {asset}",
                    message="Risk evaluation crashed — returning HIGH risk, PAUSE action",
                    asset=asset,
                )
            except Exception:
                logger.exception("risk_registry.evaluate(%s) — AlertManager dispatch also failed", asset)
            return self._fallback_signal(asset)

    def get_latest(self, asset: str | None = None):
        with self._lock:
            if asset:
                return self._cache.get(asset)
            return dict(self._cache)

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _recommend(risk_level: str, risk_flags: list) -> str:
        if "EXCESSIVE_SL_HITS" in risk_flags:
            return "PAUSE"
        if "SELL_TRIPWIRE" in risk_flags:
            return "PAUSE"
        if risk_level == "HIGH":
            return "PAUSE"
        elif risk_level == "MEDIUM":
            return "REDUCE_RISK"
        elif risk_flags:
            return "MONITOR"
        return "NORMAL"

    @staticmethod
    def _generate_explanations(
        drift_scores: dict,
        risk_flags: list,
        sl_rate: float | None = None,
        sell_wr: float | None = None,
    ) -> list:
        templates = {
            "MODEL_DRIFT": "Model probability distribution deviates significantly from baseline (KL {score:.2f})",
            "SIGNAL_INSTABILITY": "Signal flip rate increased beyond historical percentile (mismatch rate {score:.2f})",
            "PNL_DEGRADATION": "PnL divergence exceeds expected baseline variance (MAE {score:.2f})",
            "FEATURE_UNSTABLE": "Feature stability declining, Jaccard similarity dropping (stability {score:.2f})",
            "REGIME_SHIFT": (
                "Regime classification mismatch increasing vs historical distribution (consistency {score:.2f})"
            ),
            "ELEVATED_SL_HITS": "SL hit rate elevated ({score:.1%}) — consider wider stops or lower sizing",
            "EXCESSIVE_SL_HITS": "SL hit rate critical ({score:.1%}) — halting, stops too tight or model broken",
            "SELL_TRIPWIRE": (
                "SELL win rate below threshold ({score:.1%}) — possible calibration shift or directional inversion"
            ),
        }
        key_map = {
            "MODEL_DRIFT": "model_drift",
            "SIGNAL_INSTABILITY": "signal_drift",
            "PNL_DEGRADATION": "pnl_drift",
            "FEATURE_UNSTABLE": "feature_stability",
            "REGIME_SHIFT": "regime_consistency",
            "SELL_TRIPWIRE": "sell_win_rate",
        }
        explanations = []
        for flag in risk_flags:
            key = key_map.get(flag)
            score = drift_scores.get(key, 0.0) if key else 0.0
            if flag in ("ELEVATED_SL_HITS", "EXCESSIVE_SL_HITS"):
                score = sl_rate or 0.0
            if flag == "SELL_TRIPWIRE":
                score = sell_wr or 0.0
            template = templates.get(flag, "")
            if template:
                explanations.append(template.format(score=score))
        if not explanations:
            explanations.append("No significant drift detected — risk within normal bounds")
        return explanations

    @staticmethod
    def _fallback_signal(asset: str) -> dict:
        return {
            "asset": asset,
            "timestamp": utc_now_iso(),
            "risk_level": "HIGH",
            "risk_score": 1.0,
            "confidence": 0.0,
            "exposure_multiplier": 0.0,
            "risk_flags": ["RISK_GOVERNOR_FAILURE"],
            "recommended_action": "PAUSE",
            "explanations": ["Risk governance unavailable — defaulting to HIGH risk, halting asset"],
            "component_scores": {},
            "drift_details": {},
        }


# ── Module-level convenience ─────────────────────────────────────────────

_default_registry = RiskRegistry()

reset = _default_registry.reset
record_trade_outcome = _default_registry.record_trade_outcome
get_sl_hit_rate = _default_registry.get_sl_hit_rate
get_sl_hit_rate_all = _default_registry.get_sl_hit_rate_all
record_sell_side_outcome = _default_registry.record_sell_side_outcome
get_sell_win_rate = _default_registry.get_sell_win_rate
get_sell_tripwire_state = _default_registry.get_sell_tripwire_state
evaluate = _default_registry.evaluate
get_latest = _default_registry.get_latest
