"""CounterfactualEngine — replay decisions under modified conditions.

M4 of the Decision Provenance Layer: given a captured DecisionProvenance,
apply a what-if modification to one context and re-derive the decision trace
to answer "what if gate X had passed?" or "what if the model had predicted
differently?"

Usage::

    engine = CounterfactualEngine()
    original = store.get_by_decision_id("...")
    cf = engine.gate_override(original, "spread_gate_blocked", False)
    store.store(cf)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from eigencapital.domain.provenance import DecisionID, DecisionProvenance, DecisionTrace

# Known gate fields on DecisionTrace whose names end with _blocked
_GATE_BLOCKED_FIELDS = frozenset({
    "spread_gate_blocked", "session_gate_blocked", "confidence_gate_blocked",
    "conviction_gate_blocked", "hysteresis_blocked", "vix_gate_blocked",
    "adx_gate_blocked",
})


@dataclass(frozen=True)
class CounterfactualDelta:
    """Describes what changed between the original and counterfactual record.

    Stored alongside the counterfactual provenance for traceability.
    """

    modification_type: str  # "gate_override" | "probability_override" | "signal_override"
    field: str
    original_value: Any
    new_value: Any
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "modification_type": self.modification_type,
            "field": self.field,
            "original_value": self.original_value,
            "new_value": self.new_value,
            "description": self.description,
        }


class CounterfactualEngine:
    """Apply counterfactual modifications to a DecisionProvenance.

    Every method returns a new ``DecisionProvenance`` with ``decision_type``
    set to ``"COUNTERFACTUAL"`` and the same ``lineage_id`` as the original.
    The original record is never modified.
    """

    def _base(self, original: DecisionProvenance) -> DecisionProvenance:
        """Clone a provenance, resetting decision_id and decision_type."""
        d = original.to_dict()
        d["decision_id"] = DecisionID.generate(lineage_id=original.decision_id.lineage_id).to_dict()
        d["decision_type"] = "COUNTERFACTUAL"
        return DecisionProvenance.from_dict(d)

    # ── Gate overrides ───────────────────────────────────────────────

    def gate_override(
        self,
        original: DecisionProvenance,
        gate_name: str,
        passed: bool,
    ) -> tuple[DecisionProvenance, CounterfactualDelta]:
        """Override a single gate outcome.

        Args:
            original: The captured provenance record.
            gate_name: The gate field name (e.g. ``"spread_gate_blocked"``).
            passed: ``True`` = gate passed (not blocked), ``False`` = gate blocked.

        Returns:
            (counterfactual_provenance, delta) tuple.
        """
        cf = self._base(original)
        old_trace = original.decision or DecisionTrace(final_signal="UNKNOWN")
        trace_dict = old_trace.to_dict()

        original_gate_value = trace_dict.get(gate_name, None)
        trace_dict[gate_name] = not passed if gate_name.endswith("_blocked") else passed

        _gate_keys = _GATE_BLOCKED_FIELDS & trace_dict.keys()
        trace_dict["n_gates_passed"] = sum(1 for k in _gate_keys if trace_dict[k] is False)
        trace_dict["n_gates_blocked"] = sum(1 for k in _gate_keys if trace_dict[k] is True)
        def _strip_gate(k: str) -> str:
            return k.replace("_gate_blocked", "").replace("_blocked", "")

        gates_blocked = [_strip_gate(k) for k in _gate_keys if trace_dict[k] is True]
        trace_dict["gates_blocked"] = gates_blocked
        trace_dict["gates_trace"] = {
            _strip_gate(k): not (trace_dict[k] if k in trace_dict else False)
            for k in _gate_keys
        }

        cf_dict = cf.to_dict()
        cf_dict["decision"] = trace_dict
        cf = DecisionProvenance.from_dict(cf_dict)

        delta = CounterfactualDelta(
            modification_type="gate_override",
            field=gate_name,
            original_value=original_gate_value,
            new_value=not original_gate_value if isinstance(original_gate_value, bool) else None,
            description=f"Gate '{gate_name}' overridden to {'pass' if not str(gate_name).endswith('_blocked') == (not passed) else 'block'}",
        )
        return cf, delta

    # ── Probability overrides ────────────────────────────────────────

    def probability_override(
        self,
        original: DecisionProvenance,
        prob_long: float,
        prob_short: float,
        prob_neutral: float,
    ) -> tuple[DecisionProvenance, CounterfactualDelta]:
        """Override model probabilities.

        Re-derives the signal from the new probabilities.
        """
        cf = self._base(original)
        mdl = cf.model
        md = mdl.to_dict() if mdl else {}
        md["prob_long"] = prob_long
        md["prob_short"] = prob_short
        md["prob_neutral"] = prob_neutral
        cf_dict = cf.to_dict()
        cf_dict["model"] = md

        new_signal = guess_signal_from_probs(prob_long, prob_short, prob_neutral)
        dt = cf.decision
        td = dt.to_dict() if dt else {}
        td["final_signal"] = new_signal
        cf_dict["decision"] = td
        cf = DecisionProvenance.from_dict(cf_dict)

        delta = CounterfactualDelta(
            modification_type="probability_override",
            field="model.probabilities",
            original_value={
                "prob_long": original.model.prob_long if original.model else None,
                "prob_short": original.model.prob_short if original.model else None,
                "prob_neutral": original.model.prob_neutral if original.model else None,
            },
            new_value={"prob_long": prob_long, "prob_short": prob_short, "prob_neutral": prob_neutral},
            description=f"Signal changed to {new_signal}",
        )
        return cf, delta

    # ── Signal override ──────────────────────────────────────────────

    def signal_override(
        self,
        original: DecisionProvenance,
        new_signal: str,
    ) -> tuple[DecisionProvenance, CounterfactualDelta]:
        """Force the final signal to a specific value."""
        cf = self._base(original)
        dt = original.decision
        td = dt.to_dict() if dt else {}
        original_signal = td.get("final_signal", "UNKNOWN")
        td["final_signal"] = new_signal
        cf_dict = cf.to_dict()
        cf_dict["decision"] = td
        cf = DecisionProvenance.from_dict(cf_dict)

        delta = CounterfactualDelta(
            modification_type="signal_override",
            field="decision.final_signal",
            original_value=original_signal,
            new_value=new_signal,
            description=f"Signal overridden from {original_signal} to {new_signal}",
        )
        return cf, delta

    # ── SL/TP overrides ──────────────────────────────────────────────

    def sltp_override(
        self,
        original: DecisionProvenance,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> tuple[DecisionProvenance, CounterfactualDelta]:
        """Override stop-loss and/or take-profit prices."""
        cf = self._base(original)
        dt = original.decision
        td = dt.to_dict() if dt else {}
        original_sl = td.get("stop_loss_price")
        original_tp = td.get("take_profit_price")
        if stop_loss is not None:
            td["stop_loss_price"] = stop_loss
        if take_profit is not None:
            td["take_profit_price"] = take_profit
        cf_dict = cf.to_dict()
        cf_dict["decision"] = td
        cf = DecisionProvenance.from_dict(cf_dict)

        delta = CounterfactualDelta(
            modification_type="sltp_override",
            field="decision.stop_loss_price,decision.take_profit_price",
            original_value={"sl": original_sl, "tp": original_tp},
            new_value={"sl": stop_loss, "tp": take_profit},
            description=f"SL: {original_sl} -> {stop_loss}, TP: {original_tp} -> {take_profit}",
        )
        return cf, delta


def guess_signal_from_probs(prob_long: float, prob_short: float, prob_neutral: float) -> str:
    """Derive the most likely signal from raw probabilities."""
    if prob_long > prob_short and prob_long > prob_neutral:
        return "BUY"
    elif prob_short > prob_long and prob_short > prob_neutral:
        return "SELL"
    else:
        return "HOLD"
