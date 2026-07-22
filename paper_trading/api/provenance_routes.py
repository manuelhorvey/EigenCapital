"""Provenance API routes — expose Decision Provenance Layer via REST."""

from __future__ import annotations

import json as _json
import logging

from eigencapital.domain.provenance.counterfactual import CounterfactualEngine
from paper_trading.api.common import get_provenance_store, json_dumps
from paper_trading.state_store import StateStore

logger = logging.getLogger("eigencapital.api.provenance")


def handle_provenance(path: str, query: dict, state_store: StateStore | None = None) -> str:
    """Return recent provenance decisions.

    Query params:
        asset    — filter by asset (optional)
        limit    — max records (default 50)
        cycle_id — filter by cycle

    Returns a JSON array of provenance records (latest first).
    """
    store = get_provenance_store()
    if store is None:
        return json_dumps({"error": "Provenance store not available", "records": []})

    asset = query.get("asset") or None
    limit = int(query.get("limit", 50))
    cycle_id = int(query.get("cycle_id")) if query.get("cycle_id") else None
    raw = query.get("raw", "").lower() in ("1", "true", "yes")

    records = store.query(asset=asset, cycle_id=cycle_id, limit=limit)

    if raw:
        data = [r.to_dict() for r in records]
    else:
        data = []
        for r in records:
            entry = {
                "decision_id": r.decision_id.decision_id,
                "cycle_id": r.cycle_id,
                "asset": r.asset,
                "decision_timestamp": r.decision_timestamp,
                "decision_type": r.decision_type,
                "signal": r.decision.final_signal if r.decision else None,
                "position_size": r.decision.position_size if r.decision else None,
                "confidence": r.model.calibrated_confidence if r.model else None,
                "prob_long": r.model.prob_long if r.model else None,
                "prob_short": r.model.prob_short if r.model else None,
                "total_equity": r.runtime.total_equity if r.runtime else None,
                "drawdown_pct": r.runtime.drawdown_pct if r.runtime else None,
                "halt_ratio": r.runtime.halt_ratio if r.runtime else None,
                "config_hash": r.config_hash[:12] if r.config_hash else None,
                "n_features": r.features.n_features if r.features else 0,
                "feature_hash": r.features.feature_hash if r.features else None,
                "model_hash": r.model.model_hash if r.model else None,
                "portfolio_context": {
                    "gross_exposure": r.portfolio.gross_exposure if r.portfolio else None,
                    "net_exposure": r.portfolio.net_exposure if r.portfolio else None,
                    "open_positions": r.portfolio.open_position_count if r.portfolio else None,
                    "pek_budget_utilization": r.portfolio.pek_budget_utilization if r.portfolio else None,
                },
                "execution_context": {
                    "emergency_halt": r.runtime.emergency_halt if r.runtime else False,
                    "circuit_breaker_tripped": r.runtime.circuit_breaker_tripped if r.runtime else False,
                    "pek_budget_utilization": r.runtime.pek_budget_utilization if r.runtime else 1.0,
                    "position_concentration_skew": r.runtime.position_concentration_skew if r.runtime else 0.0,
                },
            }
            data.append(entry)

    return json_dumps({"records": data, "count": len(data)})


def handle_provenance_detail(path: str, query: dict, state_store: StateStore | None = None) -> str:
    """Return a single provenance record by decision_id.

    The decision_id is extracted from the URL path::
        /provenance/<uuid>.json
    """
    store = get_provenance_store()
    if store is None:
        return json_dumps({"error": "Provenance store not available"})

    decision_id = path.rsplit("/", 1)[-1].replace(".json", "")
    record = store.get_by_decision_id(decision_id)
    if record is None:
        return json_dumps({"error": "Decision not found", "decision_id": decision_id})

    return json_dumps({"record": record.to_dict()})


def handle_provenance_stats(path: str, query: dict, state_store: StateStore | None = None) -> str:
    """Return summary statistics across all provenance records."""
    store = get_provenance_store()
    if store is None:
        return json_dumps({"error": "Provenance store not available"})

    total = store.count()
    if total == 0:
        return json_dumps({"total": 0})

    latest = store.query(limit=1)
    latest_record = latest[0] if latest else None

    signal_counts: dict[str, int] = {}
    asset_set: set[str] = set()
    for r in store.query(limit=min(total, 5000)):
        signal_counts[r.decision.final_signal if r.decision else "—"] = (
            signal_counts.get(r.decision.final_signal if r.decision else "—", 0) + 1
        )
        asset_set.add(r.asset)

    return json_dumps({
        "total": total,
        "unique_assets": len(asset_set),
        "assets": sorted(asset_set),
        "signals": signal_counts,
        "latest_cycle_id": latest_record.cycle_id if latest_record else None,
        "latest_timestamp": latest_record.decision_timestamp if latest_record else None,
    })


def handle_counterfactual(body: bytes, state_store: StateStore | None = None) -> tuple[str, int]:
    """Run a counterfactual override on a captured decision.

    POST body (JSON):
        decision_id   — UUID of the original DecisionProvenance
        override_type — "gate", "probability", "signal", "sltp"
        field         — gate name (for gate override) or signal value (for signal override)
        value         — bool (gate), float (probability), str (signal), or dict (sltp)
    """
    store = get_provenance_store()
    if store is None:
        return json_dumps({"error": "Provenance store not available"}), 503

    try:
        payload = _json.loads(body.decode("utf-8"))
    except (_json.JSONDecodeError, UnicodeDecodeError):
        return json_dumps({"error": "Invalid JSON body"}), 400

    decision_id = payload.get("decision_id")
    if not decision_id:
        return json_dumps({"error": "decision_id is required"}), 400

    original = store.get_by_decision_id(str(decision_id))
    if original is None:
        return json_dumps({"error": "Decision not found", "decision_id": decision_id}), 404

    override_type = payload.get("override_type", "gate")
    engine = CounterfactualEngine()

    try:
        if override_type == "gate":
            gate_name = str(payload.get("field", ""))
            passed = bool(payload.get("value", True))
            cf, delta = engine.gate_override(original, gate_name, passed)
        elif override_type == "probability":
            probs = payload.get("value", {})
            cf, delta = engine.probability_override(
                original,
                prob_long=float(probs.get("prob_long", 0.0)),
                prob_short=float(probs.get("prob_short", 0.0)),
                prob_neutral=float(probs.get("prob_neutral", 0.0)),
            )
        elif override_type == "signal":
            new_signal = str(payload.get("field", ""))
            cf, delta = engine.signal_override(original, new_signal)
        elif override_type == "sltp":
            sltp = payload.get("value", {})
            cf, delta = engine.sltp_override(
                original,
                stop_loss=float(sltp["sl"]) if "sl" in sltp else None,
                take_profit=float(sltp["tp"]) if "tp" in sltp else None,
            )
        else:
            return json_dumps({"error": f"Unknown override_type: {override_type}"}), 400
    except (ValueError, TypeError, KeyError) as e:
        return json_dumps({"error": str(e)}), 400

    store.store(cf)
    result = cf.to_dict()
    result["_delta"] = delta.to_dict()
    return json_dumps({"counterfactual": result}), 200
