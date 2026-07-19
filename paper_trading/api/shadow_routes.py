from datetime import datetime

import pytz

from paper_trading.api.common import (
    cache_set,
    get_server_store,
    json_dumps,
)
from paper_trading.state_store import StateStore

ET = pytz.timezone("US/Eastern")


def handle_shadow_trades_route(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    limit = max(1, min(int(query.get("limit", 50)), 500))
    offset = max(0, int(query.get("offset", 0)))
    alt_label = query.get("alt_label") or None
    records = store.read_shadow_trades(limit=limit, offset=offset, alt_label=alt_label)
    data = json_dumps(records, indent=2)
    cache_set("/shadow/trades.json", data)
    return data


def handle_shadow_summary(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = store.read_shadow_trades(limit=limit)
    if not records:
        return json_dumps({"overall": {"n": 0}}, indent=2)

    from shared.metrics.shadow import compute_shadow_divergence

    result = compute_shadow_divergence(records)
    result["updated_at"] = datetime.now(tz=ET).isoformat()
    data = json_dumps(result, indent=2)
    cache_set("/shadow/summary.json", data)
    return data


def handle_shadow_actions(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    data = json_dumps(actions or {}, indent=2)
    cache_set("/shadow-actions", data)
    return data


def handle_shadow_actions_asset(path: str, query: dict, state_store: StateStore | None = None) -> tuple[str, int]:
    store = state_store or get_server_store()
    asset = path[len("/shadow-actions/") : -len(".json")]
    snapshot = store.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    action = (actions or {}).get(asset)
    if action is not None:
        return json_dumps(action, indent=2), 200
    return json_dumps({"error": "Not found", "code": 404}), 404
