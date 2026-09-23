"""Core rebalance-policy engine — shared by research and live.

Extracted from :mod:`eigencapital.live.rebalance_policy` so that research
code can import the policy engine without crossing the research/live
boundary (S6 security boundary). Persistence (state files, JSONL ledger),
environment selection, and protected-file guards remain in
:mod:`eigencapital.live.rebalance_policy`.

R4 Rebalance-Policy abstraction — WHEN to act on an already-computed target.

The frozen R4 signal is UNTOUCHED: this module only decides whether a
cycle's already-computed R4 target portfolio should be acted upon. It never
generates weights, never alters sizing, and never bypasses risk gates or
execution safety.

Three clocks are kept separate:
    Signal clock      — when R4 computes its target (unchanged, canonical D1)
    Intervention clock— when the portfolio may be modified (THIS module)
    Risk clock        — hard risk gates, evaluated every cycle upstream
                        (UNCHANGED; a slow policy never delays a risk gate)

Policies
--------
CANONICAL  Current production behavior: act whenever the order plan is
           non-empty. This is the frozen baseline and the loop's DEFAULT —
           choosing it reproduces pre-research behavior exactly.
DAILY      At most one intervention per calendar trading day (UTC). The loop
           keeps waking hourly for monitoring/risk; only the first eligible
           decision per day may trade.
WEEKLY     Intervention only at a deterministic weekly anchor (configurable
           weekday + UTC time). Emergency events (risk-mandated reduction,
           reconciliation correction) still act immediately — those are
           upstream hard controls, not this policy's authority.
THRESHOLD  Per-symbol no-trade band on |target_weight − current_weight|.
           Discrete events (new entry, full exit, reversal, removal) always
           trade; the band applies only to same-direction adjustments.
HYBRID     Threshold band + explicit event override (exit signal, removal,
           regime transition, risk-mandated reduction, reconciliation
           correction). Reuses ONLY canonical event definitions already
           produced upstream — it invents no new risk events.

Threshold semantics (explicit, tested):
    deviation  > threshold → TRADE   (strictly outside the band)
    deviation <= threshold → HOLD    (inside the band, including the exact
                                      boundary — the boundary belongs to the
                                      no-trade side so micro-adjustments do
                                      not chase rounding noise)
    target != 0, current == 0 → TRADE (new entry — never banded)
    target == 0, current != 0 → TRADE (full exit — never banded)
    target sign != current sign (both nonzero) → TRADE (reversal)
    A banded (held) position produces no order for that symbol and is
    recorded with reason NO_MATERIAL_CHANGE — never silently dropped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Mapping

REBALANCE_POLICY_VERSION = "1.0"

# Canonical R4 weights below this are treated as "no target" by the frozen
# order generator (generate_orders uses abs(w) > 0.005). Reused verbatim so
# policy semantics align with the canonical pipeline.
CANONICAL_MIN_WEIGHT = 0.005


class PolicyType(str, Enum):
    """Studied rebalance policies. CANONICAL is the frozen baseline."""

    CANONICAL = "CANONICAL"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    THRESHOLD = "THRESHOLD"
    HYBRID = "HYBRID"


class DecisionAction(str, Enum):
    TRADE = "TRADE"
    HOLD = "HOLD"


class DecisionReason(str, Enum):
    """Why the intervention clock said TRADE or HOLD.

    Reasons referencing risk/reconciliation/regime events re-use canonical
    event definitions produced upstream (RiskEnforcer gates, Reconciliation
    engine, R4 regime diagnostics) — no new risk events are defined here.
    """

    DAILY_SCHEDULE = "DAILY_SCHEDULE"
    WEEKLY_SCHEDULE = "WEEKLY_SCHEDULE"
    WEIGHT_DRIFT = "WEIGHT_DRIFT"
    NEW_SIGNAL = "NEW_SIGNAL"
    EXIT_SIGNAL = "EXIT_SIGNAL"
    RISK_EVENT = "RISK_EVENT"
    REGIME_EVENT = "REGIME_EVENT"
    RECONCILIATION_EVENT = "RECONCILIATION_EVENT"
    SYMBOL_REMOVED = "SYMBOL_REMOVED"
    NO_MATERIAL_CHANGE = "NO_MATERIAL_CHANGE"
    COOLDOWN = "COOLDOWN"
    ALREADY_TRADED_PERIOD = "ALREADY_TRADED_PERIOD"
    OUTSIDE_ANCHOR_WINDOW = "OUTSIDE_ANCHOR_WINDOW"


@dataclass(frozen=True)
class RebalanceEvents:
    """Canonical upstream events for the current cycle (Sections 8/9).

    All flags are derived upstream and passed in verbatim. The policy layer
    never derives risk events itself — it only consumes the canonical ones.
    """

    risk_mandated_reduction: bool = False  # a risk gate demands position reduction
    reconciliation_correction: bool = False  # reconciliation demands correction
    execution_or_catastrophic_event: bool = False  # execution-safety escalation
    regime_transition: bool = False  # R4 regime state changed vs last cycle


@dataclass(frozen=True)
class PolicyConfig:
    """Explicit policy parameters (Section 6: nothing hardcoded in the loop).

    The weekly anchor defaults mirror the frozen config's documented
    ``rebalance_frequency = "weekly"`` intent (that config key exists but is
    NOT enforced by the live loop; the anchor here is research-only and
    explicitly configurable). Nothing here changes production behavior
    unless the operator selects a non-CANONICAL policy.
    """

    policy_type: PolicyType = PolicyType.CANONICAL
    threshold: float = 0.01  # no-trade band width for THRESHOLD/HYBRID
    weekly_anchor_weekday: int = 0  # 0=Monday (UTC)
    weekly_anchor_hour_utc: int = 0  # hour of day at the weekly anchor
    weekly_anchor_minute_utc: int = 0
    policy_version: str = REBALANCE_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.threshold < 0:
            raise ValueError(f"threshold must be >= 0, got {self.threshold}")
        if not 0 <= self.weekly_anchor_weekday <= 6:
            raise ValueError(f"weekly_anchor_weekday must be 0..6, got {self.weekly_anchor_weekday}")
        if not 0 <= self.weekly_anchor_hour_utc <= 23:
            raise ValueError(f"weekly_anchor_hour_utc must be 0..23, got {self.weekly_anchor_hour_utc}")
        if not 0 <= self.weekly_anchor_minute_utc <= 59:
            raise ValueError(f"weekly_anchor_minute_utc must be 0..59, got {self.weekly_anchor_minute_utc}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_type": self.policy_type.value,
            "threshold": self.threshold,
            "weekly_anchor_weekday": self.weekly_anchor_weekday,
            "weekly_anchor_hour_utc": self.weekly_anchor_hour_utc,
            "weekly_anchor_minute_utc": self.weekly_anchor_minute_utc,
            "policy_version": self.policy_version,
        }

    @property
    def policy_id(self) -> str:
        """Stable experiment-matrix id, e.g. R4-REB-T010 / R4-REB-HYBRID-T010."""
        p = self.policy_type
        if p is PolicyType.THRESHOLD:
            return f"R4-REB-T{round(self.threshold * 1000):03d}"
        if p is PolicyType.HYBRID:
            return f"R4-REB-HYBRID-T{round(self.threshold * 1000):03d}"
        return f"R4-REB-{p.value}"


@dataclass(frozen=True)
class RebalanceDecision:
    """Outcome of one policy evaluation — always fully explained."""

    action: DecisionAction
    reason: DecisionReason
    policy_type: PolicyType
    policy_id: str
    policy_version: str
    max_weight_deviation: float = 0.0
    gross_turnover_if_traded: float = 0.0  # Σ|target_w − current_w| / 2 (weight space)
    signal_age_days: int | None = None
    last_rebalance_timestamp: str | None = None
    tradable_symbols: List[str] = field(default_factory=list)  # band-permitted symbols
    banded_symbols: List[str] = field(default_factory=list)  # symbols held by the band
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_trade(self) -> bool:
        return self.action is DecisionAction.TRADE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason.value,
            "policy_type": self.policy_type.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "max_weight_deviation": round(self.max_weight_deviation, 6),
            "gross_turnover_if_traded": round(self.gross_turnover_if_traded, 6),
            "signal_age_days": self.signal_age_days,
            "last_rebalance_timestamp": self.last_rebalance_timestamp,
            "tradable_symbols": list(self.tradable_symbols),
            "banded_symbols": list(self.banded_symbols),
            "details": dict(self.details),
        }


@dataclass
class PolicyState:
    """Persisted policy state — survives restart (Section 23)."""

    policy_type: PolicyType = PolicyType.CANONICAL
    last_rebalance_timestamp: str | None = None
    last_signal_timestamp: str | None = None
    last_target_hash: str = ""
    last_decision: str = ""
    last_decision_reason: str = ""
    last_rebalance_day: str = ""  # ISO date of last DAILY intervention (UTC)
    last_rebalance_week: str = ""  # ISO year-week of last WEEKLY intervention
    last_regime_on: bool | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_type": self.policy_type.value,
            "policy_version": REBALANCE_POLICY_VERSION,
            "last_rebalance_timestamp": self.last_rebalance_timestamp,
            "last_signal_timestamp": self.last_signal_timestamp,
            "last_target_hash": self.last_target_hash,
            "last_decision": self.last_decision,
            "last_decision_reason": self.last_decision_reason,
            "last_rebalance_day": self.last_rebalance_day,
            "last_rebalance_week": self.last_rebalance_week,
            "last_regime_on": self.last_regime_on,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PolicyState:
        try:
            pt = PolicyType(d.get("policy_type", PolicyType.CANONICAL.value))
        except ValueError:
            pt = PolicyType.CANONICAL
        return cls(
            policy_type=pt,
            last_rebalance_timestamp=d.get("last_rebalance_timestamp"),
            last_signal_timestamp=d.get("last_signal_timestamp"),
            last_target_hash=str(d.get("last_target_hash", "")),
            last_decision=str(d.get("last_decision", "")),
            last_decision_reason=str(d.get("last_decision_reason", "")),
            last_rebalance_day=str(d.get("last_rebalance_day", "")),
            last_rebalance_week=str(d.get("last_rebalance_week", "")),
            last_regime_on=d.get("last_regime_on"),
        )


def compute_target_hash(target_weights: Mapping[str, float]) -> str:
    """Deterministic hash of the target portfolio (sorted, 6-dp quantized)."""
    canonical = json.dumps(
        {sym: round(float(w), 6) for sym, w in sorted(target_weights.items())},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compute_turnover(target_weights: Mapping[str, float], current_weights: Mapping[str, float]) -> float:
    """Gross traded notional in weight space: Σ|target_w − current_w|.

    Weight space is the canonical comparison space: the R4 signal is defined
    in weights, and the shadow tracker's documented convention is
    notional_proxy = |w| · equity (no contract-size assumptions at the policy
    layer). One unit of turnover = 100% of equity traded once; every unit
    traded pays ``cost_bps`` once (per-side costing, matching the project's
    documented 10 bps per side convention in scripts/audit/reconstruct.py
    C7). This is the ONLY turnover formula in the policy layer — no
    competing definition.
    """
    symbols = set(target_weights) | set(current_weights)
    return sum(abs(float(target_weights.get(s, 0.0)) - float(current_weights.get(s, 0.0))) for s in symbols)


def classify_symbol_event(
    target_weight: float,
    current_weight: float,
    threshold: float = 0.01,
) -> str:
    """Classify the per-symbol intervention event for a threshold policy.

    Returns one of:
        "new_entry"        current flat (|w| <= min), target active
        "full_exit"        target flat (|w| <= min), current active
        "reversal"         sign flip between target and current
        "adjustment_out"   same sign, deviation strictly > threshold → trade
        "adjustment_in"    same sign, deviation <= threshold → banded hold
        "no_target"        target and current both inactive

    Discrete events (new_entry / full_exit / reversal) are NEVER banded: a
    +5% → 0 target is an exit signal, not a 1pp drift. The exact boundary
    (deviation == threshold) belongs to the no-trade side ("adjustment_in").
    """
    t, c = float(target_weight), float(current_weight)
    t_active = abs(t) > CANONICAL_MIN_WEIGHT
    c_active = abs(c) > CANONICAL_MIN_WEIGHT
    if not t_active and not c_active:
        return "no_target"
    if t_active and not c_active:
        return "new_entry"
    if not t_active and c_active:
        return "full_exit"
    if (t > 0) != (c > 0):
        return "reversal"
    deviation = abs(t - c)
    return "adjustment_out" if deviation > threshold else "adjustment_in"


def evaluate_symbol_band(
    target_weights: Mapping[str, float],
    current_weights: Mapping[str, float],
    threshold: float,
) -> tuple[List[str], List[str], float]:
    """Apply the per-symbol no-trade band. Returns (tradable, banded, max_dev).

    Symbols whose event is discrete (new entry, full exit, reversal) are
    always tradable. Same-direction adjustments trade only when their
    deviation is strictly outside the band (deviation > threshold; the exact
    boundary holds).
    """
    tradable: List[str] = []
    banded: List[str] = []
    max_dev = 0.0
    symbols = set(target_weights) | set(current_weights)
    for sym in sorted(symbols):
        t = float(target_weights.get(sym, 0.0))
        c = float(current_weights.get(sym, 0.0))
        event = classify_symbol_event(t, c, threshold)
        deviation = abs(t - c)
        max_dev = max(max_dev, deviation)
        if event == "no_target":
            continue
        if event == "adjustment_in":
            banded.append(sym)
        else:
            tradable.append(sym)
    return tradable, banded, max_dev


class RebalancePolicy:
    """Base policy: decide whether the cycle's target may be acted upon.

    The decision consumes only information available at the decision
    timestamp (Section 15): current/target weights, the signal timestamp,
    the current time, canonical events, and persisted state. No future
    targets, no future knowledge.
    """

    def __init__(self, config: PolicyConfig) -> None:
        self._config = config
        self.state = PolicyState(policy_type=config.policy_type)

    @property
    def config(self) -> PolicyConfig:
        return self._config

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        raise NotImplementedError

    # ── shared helpers ────────────────────────────────────────────────

    def _base_decision(
        self,
        action: DecisionAction,
        reason: DecisionReason,
        target_weights: Mapping[str, float],
        current_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        tradable: List[str] | None = None,
        banded: List[str] | None = None,
        extra_details: Dict[str, Any] | None = None,
    ) -> RebalanceDecision:
        # tradable=None means UNRESTRICTED permission (cadence policies:
        # CANONICAL/DAILY/WEEKLY trade the whole order plan). For a TRADE
        # decision the permitted set is then every symbol active on either
        # side — so downstream filtering (loop order plan, replay booking)
        # treats the decision as "all symbols may trade". Band-based policies
        # always pass an explicit tradable list.
        if tradable is None:
            if action is DecisionAction.TRADE:
                tradable_list = sorted(
                    s
                    for s in set(target_weights) | set(current_weights)
                    if abs(float(target_weights.get(s, 0.0))) > CANONICAL_MIN_WEIGHT
                    or abs(float(current_weights.get(s, 0.0))) > CANONICAL_MIN_WEIGHT
                )
            else:
                tradable_list = []
        else:
            tradable_list = list(tradable)
        banded_list = list(banded) if banded is not None else []
        dev = 0.0
        for sym in set(target_weights) | set(current_weights):
            dev = max(dev, abs(float(target_weights.get(sym, 0.0)) - float(current_weights.get(sym, 0.0))))
        signal_age: int | None = None
        if signal_timestamp is not None:
            try:
                sig = signal_timestamp if signal_timestamp.tzinfo else signal_timestamp.replace(tzinfo=UTC)
                signal_age = max(0, int((now - sig).total_seconds() // 86400))
            except (TypeError, ValueError, OSError):
                signal_age = None
        details: Dict[str, Any] = {}
        if extra_details:
            details.update(extra_details)
        # gross_turnover_if_traded: only symbols actually permitted to trade
        # contribute (banded symbols are carried, not traded, and pay nothing).
        if tradable is not None:
            turnover_if_traded = sum(
                abs(float(target_weights.get(s, 0.0)) - float(current_weights.get(s, 0.0))) for s in tradable_list
            )
        else:
            turnover_if_traded = compute_turnover(target_weights, current_weights)
        return RebalanceDecision(
            action=action,
            reason=reason,
            policy_type=self._config.policy_type,
            policy_id=self._config.policy_id,
            policy_version=self._config.policy_version,
            max_weight_deviation=dev,
            gross_turnover_if_traded=turnover_if_traded,
            signal_age_days=signal_age,
            last_rebalance_timestamp=self.state.last_rebalance_timestamp,
            tradable_symbols=tradable_list,
            banded_symbols=banded_list,
            details=details,
        )

    def record_trade(self, now: datetime, decision: RebalanceDecision) -> None:
        """Update persisted state after an intervention (TRADE)."""
        self.state.last_rebalance_timestamp = now.isoformat()
        self.state.last_rebalance_day = now.astimezone(UTC).date().isoformat()
        self.state.last_rebalance_week = _iso_week_key(now.astimezone(UTC))
        self.state.last_decision = decision.action.value
        self.state.last_decision_reason = decision.reason.value

    def record_hold(self, decision: RebalanceDecision) -> None:
        self.state.last_decision = decision.action.value
        self.state.last_decision_reason = decision.reason.value

    def record_target(self, target_hash: str, signal_ts: datetime | None) -> None:
        self.state.last_target_hash = target_hash
        if signal_ts is not None:
            self.state.last_signal_timestamp = signal_ts.isoformat()

    def record_regime(self, regime_on: bool | None) -> None:
        self.state.last_regime_on = regime_on


class CanonicalPolicy(RebalancePolicy):
    """Frozen baseline: trade whenever the cycle produced an order plan.

    The loop already decides "no orders → ALIGNED"; CANONICAL simply never
    vetoes. Selecting this policy reproduces pre-research behavior exactly.
    """

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        if len(target_weights) == 0:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.NO_MATERIAL_CHANGE,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
            )
        return self._base_decision(
            DecisionAction.TRADE,
            DecisionReason.NEW_SIGNAL,
            target_weights,
            current_weights,
            signal_timestamp,
            now,
        )


class DailyPolicy(RebalancePolicy):
    """At most one intervention per UTC calendar day (Section 5).

    The hourly loop keeps waking for monitoring and risk; only the first
    decision of a day may trade. Repeated evaluations the same day HOLD with
    reason ALREADY_TRADED_PERIOD (idempotent across restarts via
    state.last_rebalance_day).
    """

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        today = now.astimezone(UTC).date().isoformat()
        if self.state.last_rebalance_day == today:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.ALREADY_TRADED_PERIOD,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                extra_details={"last_rebalance_day": self.state.last_rebalance_day},
            )
        if len(target_weights) == 0:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.NO_MATERIAL_CHANGE,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
            )
        return self._base_decision(
            DecisionAction.TRADE,
            DecisionReason.DAILY_SCHEDULE,
            target_weights,
            current_weights,
            signal_timestamp,
            now,
        )


class WeeklyPolicy(RebalancePolicy):
    """Deterministic weekly anchor (Section 6).

    Trades only when `now` falls on/after the current week's anchor and this
    week's intervention has not happened yet. Timezone is explicit: UTC.
    Emergency canonical events (risk-mandated reduction, reconciliation
    correction, execution escalation) act immediately regardless of the
    anchor — those are hard upstream controls, not portfolio scheduling.
    Regime transitions and exits are handled by the frozen R4 regime gate
    upstream (regime OFF → no trades at all); the weekly policy only governs
    ordinary target-tracking interventions.
    """

    def _anchor_reached(self, now_utc: datetime) -> bool:
        """True when `now` is at/after THIS ISO week's anchor instant.

        The anchor is deterministic: Monday of the current ISO week plus
        ``weekly_anchor_weekday`` days at the configured UTC time. Before the
        anchor (within the same ISO week) the policy holds; after it, the
        week's single intervention may happen (once, enforced by the
        week-key guard).
        """
        iso = now_utc.isocalendar()
        week_monday = datetime.fromisocalendar(iso[0], iso[1], 1)
        anchor_date = week_monday + timedelta(days=self._config.weekly_anchor_weekday)
        anchor_dt = datetime(
            anchor_date.year,
            anchor_date.month,
            anchor_date.day,
            self._config.weekly_anchor_hour_utc,
            self._config.weekly_anchor_minute_utc,
            tzinfo=UTC,
        )
        return now_utc >= anchor_dt

    def _emergency(self, events: RebalanceEvents) -> DecisionReason | None:
        if events.risk_mandated_reduction or events.execution_or_catastrophic_event:
            return DecisionReason.RISK_EVENT
        if events.reconciliation_correction:
            return DecisionReason.RECONCILIATION_EVENT
        return None

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        events = events or RebalanceEvents()
        now_utc = now.astimezone(UTC)
        week_key = _iso_week_key(now_utc)

        emergency = self._emergency(events)
        if emergency is not None and self.state.last_rebalance_week != week_key:
            return self._base_decision(
                DecisionAction.TRADE,
                emergency,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                extra_details={"emergency_event": emergency.value},
            )

        if self.state.last_rebalance_week == week_key:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.ALREADY_TRADED_PERIOD,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                extra_details={"week_key": week_key},
            )
        if not self._anchor_reached(now_utc):
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.OUTSIDE_ANCHOR_WINDOW,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                extra_details={
                    "anchor": (
                        f"wd{self._config.weekly_anchor_weekday} "
                        f"{self._config.weekly_anchor_hour_utc:02d}:{self._config.weekly_anchor_minute_utc:02d} UTC"
                    )
                },
            )
        if len(target_weights) == 0:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.NO_MATERIAL_CHANGE,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
            )
        return self._base_decision(
            DecisionAction.TRADE,
            DecisionReason.WEEKLY_SCHEDULE,
            target_weights,
            current_weights,
            signal_timestamp,
            now,
        )


class ThresholdPolicy(RebalancePolicy):
    """Per-symbol no-trade band (Section 7).

    Band applies ONLY to same-direction adjustments. New entries (0 → +5%),
    full exits (+5% → 0), reversals (+5% → −5%), and removals always trade.
    The exact boundary deviation == threshold is a HOLD (boundary belongs to
    the no-trade side; deviation must STRICTLY exceed the threshold to trade).

    The emergency override (risk/reconciliation/execution events) is honored:
    a hard control demanding action outranks the band. The band itself never
    blocks an exit event — exits are not classified as adjustments.
    """

    def __init__(self, config: PolicyConfig, allow_emergency_override: bool = True) -> None:
        super().__init__(config)
        self._allow_emergency_override = allow_emergency_override

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        events = events or RebalanceEvents()
        tradable, banded, max_dev = evaluate_symbol_band(target_weights, current_weights, self._config.threshold)

        if self._allow_emergency_override and (
            events.risk_mandated_reduction or events.reconciliation_correction or events.execution_or_catastrophic_event
        ):
            reason = (
                DecisionReason.RISK_EVENT
                if (events.risk_mandated_reduction or events.execution_or_catastrophic_event)
                else DecisionReason.RECONCILIATION_EVENT
            )
            return self._base_decision(
                DecisionAction.TRADE,
                reason,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                tradable=tradable,
                banded=banded,
                extra_details={"emergency_override": True, "threshold": self._config.threshold},
            )

        if not tradable:
            return self._base_decision(
                DecisionAction.HOLD,
                DecisionReason.NO_MATERIAL_CHANGE,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                tradable=[],
                banded=banded,
                extra_details={"threshold": self._config.threshold, "max_deviation": round(max_dev, 6)},
            )
        # Explainability: name the dominant reason any tradable symbol exists.
        # Exits outrank entries (risk-reducing), entries outrank drift.
        reason = DecisionReason.WEIGHT_DRIFT
        events_by_sym = {
            sym: classify_symbol_event(
                float(target_weights.get(sym, 0.0)), float(current_weights.get(sym, 0.0)), self._config.threshold
            )
            for sym in tradable
        }
        if any(e == "full_exit" for e in events_by_sym.values()):
            reason = DecisionReason.EXIT_SIGNAL
        elif any(e == "new_entry" for e in events_by_sym.values()):
            reason = DecisionReason.NEW_SIGNAL
        exit_syms = sorted(s for s, e in events_by_sym.items() if e == "full_exit")
        entry_syms = sorted(s for s, e in events_by_sym.items() if e == "new_entry")
        reversal_syms = sorted(s for s, e in events_by_sym.items() if e == "reversal")
        return self._base_decision(
            DecisionAction.TRADE,
            reason,
            target_weights,
            current_weights,
            signal_timestamp,
            now,
            tradable=tradable,
            banded=banded,
            extra_details={
                "threshold": self._config.threshold,
                "max_deviation": round(max_dev, 6),
                "exit_symbols": exit_syms or None,
                "new_entry_symbols": entry_syms or None,
                "reversal_symbols": reversal_syms or None,
            },
        )


class HybridPolicy(RebalancePolicy):
    """Threshold band + explicit canonical-event override (Section 8).

    NORMAL: threshold/no-trade band (identical semantics to ThresholdPolicy).
    EVENTS: canonical R4 exit signals and universe removals (a held symbol's
    target went flat) act immediately; risk/reconciliation/execution events
    always act immediately; canonical regime transitions act immediately.
    No new event classes are invented — the caller passes only canonical
    upstream events, so the hybrid policy cannot become a backdoor for
    discretionary trading.
    """

    def __init__(self, config: PolicyConfig) -> None:
        super().__init__(config)
        self._threshold = ThresholdPolicy(config, allow_emergency_override=True)

    def should_rebalance(
        self,
        *,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        signal_timestamp: datetime | None,
        now: datetime,
        events: RebalanceEvents | None = None,
    ) -> RebalanceDecision:
        events = events or RebalanceEvents()

        # 1. Hard events always act (risk / reconciliation / execution).
        if events.risk_mandated_reduction or events.reconciliation_correction or events.execution_or_catastrophic_event:
            decision = self._threshold.should_rebalance(
                current_weights=current_weights,
                target_weights=target_weights,
                signal_timestamp=signal_timestamp,
                now=now,
                events=events,
            )
            if decision.should_trade:
                return decision

        # 2. Canonical portfolio events: exits / universe removals — a held
        #    symbol whose target went flat is exactly the "full_exit" class.
        exits = [
            s
            for s in set(current_weights) | set(target_weights)
            if classify_symbol_event(
                float(target_weights.get(s, 0.0)), float(current_weights.get(s, 0.0)), self._config.threshold
            )
            == "full_exit"
        ]
        if exits:
            tradable, banded, max_dev = evaluate_symbol_band(target_weights, current_weights, self._config.threshold)
            return self._base_decision(
                DecisionAction.TRADE,
                DecisionReason.EXIT_SIGNAL,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                tradable=tradable,
                banded=banded,
                extra_details={"exit_symbols": sorted(exits), "threshold": self._config.threshold},
            )

        # 3. Regime transition (canonical R4 regime state flip).
        if events.regime_transition:
            tradable, banded, max_dev = evaluate_symbol_band(target_weights, current_weights, self._config.threshold)
            return self._base_decision(
                DecisionAction.TRADE,
                DecisionReason.REGIME_EVENT,
                target_weights,
                current_weights,
                signal_timestamp,
                now,
                tradable=tradable,
                banded=banded,
                extra_details={"regime_transition": True, "threshold": self._config.threshold},
            )

        # 4. Otherwise: plain threshold band.
        return self._threshold.should_rebalance(
            current_weights=current_weights,
            target_weights=target_weights,
            signal_timestamp=signal_timestamp,
            now=now,
            events=events,
        )


def _iso_week_key(dt_utc: datetime) -> str:
    iso = dt_utc.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def build_policy(config: PolicyConfig) -> RebalancePolicy:
    """Instantiate the concrete policy for a config."""
    policies = {
        PolicyType.CANONICAL: CanonicalPolicy,
        PolicyType.DAILY: DailyPolicy,
        PolicyType.WEEKLY: WeeklyPolicy,
        PolicyType.THRESHOLD: ThresholdPolicy,
        PolicyType.HYBRID: HybridPolicy,
    }
    return policies[config.policy_type](config)


# Experiment matrix (Section 13): pre-registered candidates — these are
# research configurations, NOT tuning targets. The matrix is deliberately
# fixed before the evaluation period.
THRESHOLD_CANDIDATES: tuple = (0.005, 0.010, 0.020, 0.050)


def experiment_matrix() -> List[PolicyConfig]:
    """The pre-registered policy matrix (R4-REB-* ids)."""
    configs = [
        PolicyConfig(policy_type=PolicyType.CANONICAL),
        PolicyConfig(policy_type=PolicyType.DAILY),
        PolicyConfig(policy_type=PolicyType.WEEKLY),
    ]
    configs += [PolicyConfig(policy_type=PolicyType.THRESHOLD, threshold=t) for t in THRESHOLD_CANDIDATES]
    configs += [PolicyConfig(policy_type=PolicyType.HYBRID, threshold=t) for t in (0.010,)]
    return configs


def evaluate_all_policies(
    *,
    target_weights: Mapping[str, float],
    current_weights: Mapping[str, float],
    signal_timestamp: datetime | None,
    now: datetime,
    events: RebalanceEvents | None = None,
) -> List[RebalanceDecision]:
    """Shadow comparison helper (Section 28): evaluate every matrix policy.

    Returns one decision per pre-registered policy. No orders are submitted
    and no live state is mutated — evaluation happens on throwaway instances.
    """
    decisions: List[RebalanceDecision] = []
    for config in experiment_matrix():
        policy = build_policy(config)
        decisions.append(
            policy.should_rebalance(
                current_weights=current_weights,
                target_weights=target_weights,
                signal_timestamp=signal_timestamp,
                now=now,
                events=events,
            )
        )
    return decisions
