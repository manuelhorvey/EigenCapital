"""DecisionTrace — frozen record of the decision pipeline's reasoning.

Captures the gate-by-gate trace, thresholds applied, final action,
sizing, and order details.  This is the **output** side of the
decision boundary — what the pipeline decided and why.

Distinct from ``decision_pipeline.DecisionContext`` (a mutable
pipeline-internal struct).  ``DecisionTrace`` is an immutable
provenance artifact assembled after the pipeline completes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionTrace:
    final_signal: str          # "BUY" | "SELL" | "FLAT" | "HOLD"
    gates_trace: dict[str, bool] = field(default_factory=dict)
    gates_blocked: list[str] = field(default_factory=list)
    n_gates_passed: int = 0
    n_gates_blocked: int = 0
    position_size: float = 0.0
    kelly_multiplier: float | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    entry_price: float | None = None
    entry_action: str = ""    # "ENTER" | "DEFER" | "SKIP" | "HOLD"
    entry_deferred: bool = False
    defer_reason: str = ""
    regime_transition_suppressed: bool = False
    sell_only_filtered: bool = False
    spread_gate_blocked: bool = False
    session_gate_blocked: bool = False
    vix_gate_blocked: bool = False
    confidence_gate_blocked: bool = False
    conviction_gate_blocked: bool = False
    hysteresis_blocked: bool = False
    adx_gate_blocked: bool = False
    bar_jump_suppressed: bool = False
    risk_off_suppressed: bool = False
    profit_lock_held: bool = False
    stacking_layer_added: bool = False
    stacking_reason: str = ""
    flip_occurred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_signal": self.final_signal,
            "gates_trace": self.gates_trace,
            "gates_blocked": self.gates_blocked,
            "n_gates_passed": self.n_gates_passed,
            "n_gates_blocked": self.n_gates_blocked,
            "position_size": self.position_size,
            "kelly_multiplier": self.kelly_multiplier,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "entry_price": self.entry_price,
            "entry_action": self.entry_action,
            "entry_deferred": self.entry_deferred,
            "defer_reason": self.defer_reason,
            "regime_transition_suppressed": self.regime_transition_suppressed,
            "sell_only_filtered": self.sell_only_filtered,
            "spread_gate_blocked": self.spread_gate_blocked,
            "session_gate_blocked": self.session_gate_blocked,
            "vix_gate_blocked": self.vix_gate_blocked,
            "confidence_gate_blocked": self.confidence_gate_blocked,
            "conviction_gate_blocked": self.conviction_gate_blocked,
            "hysteresis_blocked": self.hysteresis_blocked,
            "adx_gate_blocked": self.adx_gate_blocked,
            "bar_jump_suppressed": self.bar_jump_suppressed,
            "risk_off_suppressed": self.risk_off_suppressed,
            "profit_lock_held": self.profit_lock_held,
            "stacking_layer_added": self.stacking_layer_added,
            "stacking_reason": self.stacking_reason,
            "flip_occurred": self.flip_occurred,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionTrace:
        return cls(**data)
