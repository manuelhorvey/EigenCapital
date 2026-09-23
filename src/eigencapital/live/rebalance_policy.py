"""R4 Rebalance-Policy live layer — persistence, ledger, and env selection.

The policy engine itself (types, decision logic, experiment matrix) lives in
:mod:`eigencapital.core.rebalance` and is re-exported here so existing live
callers keep a single import path. Research code must import from ``core``
directly (S6 security boundary: research must not import live).

Persistence (restart safety): `load_policy_state` / `save_policy_state`
restore the day/week anchors and the last decision so a restarted process
cannot double-trade the same day/week. Policy state lives in its own file,
`rebalance_policy_state.json` — `runtime_state.json` (frozen risk recovery
state) is never written by this module.

Ledger: research decisions append to
`reports/r4_loop/rebalance_policy_decisions.jsonl` (Section 29 schema). This
is a NEW isolated file — canonical R4 ledgers (decisions.jsonl,
order_intents.jsonl, risk_gate_audit.jsonl, shadow_decisions.jsonl) are never
written by the policy layer (the same guard set the shadow recorder enforces).

No config-file changes: policy selection is via the ``R4_REBALANCE_POLICY``
environment variable (or explicit constructor), because adding fields to
EigenCapitalConfig would change the frozen config fingerprint and fail-closed
block live trading (FingerprintVerifier + T=0 snapshot).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

from eigencapital.core.rebalance import (
    CANONICAL_MIN_WEIGHT,
    REBALANCE_POLICY_VERSION,
    THRESHOLD_CANDIDATES,
    DecisionAction,
    DecisionReason,
    PolicyConfig,
    PolicyState,
    PolicyType,
    RebalanceDecision,
    RebalanceEvents,
    RebalancePolicy,
    build_policy,
    classify_symbol_event,
    compute_target_hash,
    compute_turnover,
    evaluate_all_policies,
    evaluate_symbol_band,
    experiment_matrix,
)

__all__ = [
    "CANONICAL_MIN_WEIGHT",
    "LEDGER_FILE",
    "PROTECTED_R4_EVIDENCE_FILES",
    "REBALANCE_POLICY_VERSION",
    "STATE_FILE",
    "THRESHOLD_CANDIDATES",
    "DecisionAction",
    "DecisionReason",
    "PolicyConfig",
    "PolicyState",
    "PolicyType",
    "RebalanceDecision",
    "RebalanceEvents",
    "RebalancePolicy",
    "RebalancePolicyLedger",
    "build_policy",
    "classify_symbol_event",
    "compute_target_hash",
    "compute_turnover",
    "evaluate_all_policies",
    "evaluate_symbol_band",
    "experiment_matrix",
    "load_policy_state",
    "policy_from_env",
    "save_policy_state",
]

LEDGER_FILE = "rebalance_policy_decisions.jsonl"
STATE_FILE = "rebalance_policy_state.json"

# Files owned by frozen R4 evidence — the policy layer must never write them.
PROTECTED_R4_EVIDENCE_FILES = {
    "decisions.jsonl",
    "order_intents.jsonl",
    "risk_gate_audit.jsonl",
    "shadow_decisions.jsonl",
}


def policy_from_env(env: Mapping[str, str] | None = None) -> RebalancePolicy:
    """Build the selected policy from environment variables (no config-file
    changes — the frozen config fingerprint must not move).

    Variables:
        R4_REBALANCE_POLICY      CANONICAL|DAILY|WEEKLY|THRESHOLD|HYBRID
                                 (default CANONICAL — frozen behavior)
        R4_REB_THRESHOLD         float, band width (THRESHOLD/HYBRID)
        R4_REB_WEEKDAY           int 0..6 (WEEKLY anchor weekday, default 0)
        R4_REB_HOUR_UTC          int 0..23 (WEEKLY anchor hour, default 0)
    """
    env = os.environ if env is None else env
    raw = str(env.get("R4_REBALANCE_POLICY", PolicyType.CANONICAL.value)).strip().upper()
    try:
        ptype = PolicyType(raw)
    except ValueError as e:
        raise ValueError(f"R4_REBALANCE_POLICY={raw!r} is not one of {[p.value for p in PolicyType]}") from e

    def _float_env(name: str, default: float) -> float:
        v = env.get(name)
        return float(v) if v not in (None, "") else default

    def _int_env(name: str, default: int) -> int:
        v = env.get(name)
        return int(v) if v not in (None, "") else default

    config = PolicyConfig(
        policy_type=ptype,
        threshold=_float_env("R4_REB_THRESHOLD", 0.01),
        weekly_anchor_weekday=_int_env("R4_REB_WEEKDAY", 0),
        weekly_anchor_hour_utc=_int_env("R4_REB_HOUR_UTC", 0),
    )
    return build_policy(config)


# ── Persistence + ledger (Sections 23/29) ─────────────────────────────


def save_policy_state(audit_dir: str | Path, state: PolicyState) -> None:
    """Atomic-write policy state (crash-safe, same pattern as runtime_state)."""
    path = Path(audit_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state.to_dict())
    payload["saved_at"] = datetime.now(UTC).isoformat()
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_policy_state(audit_dir: str | Path, policy: RebalancePolicy) -> PolicyState:
    """Restore persisted state into `policy` (restart safety).

    Restores the period anchors (last_rebalance_day/week) so a restarted
    process cannot double-trade the same day/week, plus the shared Section-23
    fields. A state file written by a DIFFERENT policy type does not restore
    period anchors (they are not meaningful for this policy), but the shared
    fields (last_target_hash, last_decision, last_signal_timestamp) are
    always surfaced.
    """
    path = Path(audit_dir) / STATE_FILE
    if not path.exists():
        return policy.state
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return policy.state
    saved = PolicyState.from_dict(data)
    policy.state.last_target_hash = saved.last_target_hash
    policy.state.last_decision = saved.last_decision
    policy.state.last_decision_reason = saved.last_decision_reason
    policy.state.last_signal_timestamp = saved.last_signal_timestamp
    if saved.policy_type is policy.config.policy_type:
        policy.state.last_rebalance_timestamp = saved.last_rebalance_timestamp
        policy.state.last_rebalance_day = saved.last_rebalance_day
        policy.state.last_rebalance_week = saved.last_rebalance_week
        policy.state.last_regime_on = saved.last_regime_on
    return policy.state


class RebalancePolicyLedger:
    """Append-only JSONL ledger of policy decisions (Section 29).

    Isolated research namespace: refuses to write any protected canonical R4
    evidence file, exactly like the shadow recorder. One row per cycle per
    policy evaluation.
    """

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / LEDGER_FILE

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        cycle_id: str,
        decision: RebalanceDecision,
        target_weights: Mapping[str, float],
        current_weights: Mapping[str, float],
        target_hash: str,
        current_position_hash: str = "",
        signal_date: str = "",
        risk_state: str = "",
        regime: str = "",
        estimated_cost: float | None = None,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "signal_date": signal_date,
            "cycle_id": cycle_id,
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "policy_type": decision.policy_type.value,
            "target_hash": target_hash,
            "current_position_hash": current_position_hash,
            "decision": decision.action.value,
            "reason": decision.reason.value,
            "target_weights": {k: round(float(v), 6) for k, v in sorted(target_weights.items())},
            "current_weights": {k: round(float(v), 6) for k, v in sorted(current_weights.items())},
            "max_weight_deviation": round(decision.max_weight_deviation, 6),
            "gross_turnover": round(decision.gross_turnover_if_traded, 6),
            "estimated_cost": estimated_cost,
            "risk_state": risk_state,
            "regime": regime,
            "tradable_symbols": list(decision.tradable_symbols),
            "banded_symbols": list(decision.banded_symbols),
            "signal_age_days": decision.signal_age_days,
        }
        if self._path.name in PROTECTED_R4_EVIDENCE_FILES:  # defensive guard
            raise PermissionError(f"refusing to write policy evidence to protected R4 file: {self._path.name}")
        with open(self._path, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        return row

    def read(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows
