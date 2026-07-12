import json
import os

from paper_trading.api.common import (
    _STORE,
    cache_set,
    get_mt5_status,
    json_dumps,
)


def handle_asset_detail(path: str, query: dict, state_store=None) -> tuple[str, int]:
    store = state_store or _STORE
    asset_name = path[len("/asset/") : -len(".json")]
    snapshot = store.load_snapshot()
    if not snapshot or not snapshot.assets or asset_name not in snapshot.assets:
        return json_dumps({"error": "Not found", "code": 404}), 404

    asset = snapshot.assets[asset_name]
    metrics = asset.get("metrics") or {}

    _model_name = asset_name.lstrip("^")
    model_path = f"paper_trading/models/{_model_name}_model.json"
    feature_importance: list[dict] = []
    if os.path.exists(model_path):
        try:
            with open(model_path) as f:
                model_data = json.load(f)
            learner = model_data.get("learner", {})
            features_info = learner.get("feature_names", [])
            feat_types = learner.get("feature_types", [])
            importance: dict[str, float] = {}
            for tree in learner.get("gradient_booster", {}).get("model", {}).get("trees", []):
                loss_changes = tree.get("loss_changes", [])
                for si, node in enumerate(tree.get("split_indices", [])):
                    if node < len(features_info):
                        fname = features_info[node]
                        gain = loss_changes[si] if si < len(loss_changes) else 0.0
                        importance[fname] = importance.get(fname, 0.0) + max(gain, 0.0)
            total = sum(importance.values()) or 1.0
            feature_importance = [
                {
                    "feature": f,
                    "importance": round(v / total, 6),
                    "type": feat_types[i] if i < len(feat_types) else "float",
                }
                for i, (f, v) in enumerate(sorted(importance.items(), key=lambda x: -x[1]))
            ]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, OSError):
            feature_importance = [{"error": "Model parse error"}]

    trade_log = metrics.get("trade_log") or []
    trades = []
    for t in trade_log:
        entry = t.get("entry", 0)
        exit_px = t.get("exit", 0)
        mae = t.get("mae")
        mfe = t.get("mfe")
        if mae is None and entry and exit_px:
            direction = 1 if t.get("side") == "long" else -1
            mae = min(0, (exit_px - entry) / entry * 100 * direction)
            mfe = max(0, (exit_px - entry) / entry * 100 * direction)
        trades.append(
            {
                "side": t.get("side"),
                "entry": entry,
                "exit": exit_px,
                "return": t.get("return"),
                "reason": t.get("reason"),
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("exit_date"),
                "mae": round(mae, 4) if mae is not None else None,
                "mfe": round(mfe, 4) if mfe is not None else None,
            }
        )

    data = json_dumps(
        {
            "asset": asset_name,
            "feature_importance": feature_importance,
            "trades": trades,
            "final_signal": asset.get("final_signal"),
            "sell_only": asset.get("sell_only", False),
            "tripwire_active": asset.get("tripwire_active", False),
            "last_signal": asset.get("last_signal"),
            "metrics": {
                "total_return": metrics.get("total_return"),
                "drawdown": metrics.get("drawdown"),
                "win_rate": metrics.get("win_rate"),
                "profit_factor": metrics.get("profit_factor"),
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "n_trades": metrics.get("n_trades"),
                "mean_confidence": metrics.get("mean_confidence"),
            },
        }
    )

    return data, 200


def handle_wal_asset(path: str, query: dict, state_store=None) -> tuple[str, int]:
    asset_name = path[len("/wal/") : -len(".json")]
    wal_path = os.path.join("data", "live", "wal", "engine.jsonl")
    if not os.path.exists(wal_path):
        return json_dumps({"error": "No WAL file found"}), 404

    max_events = int(query.get("max", "100"))
    events: list[dict] = []
    try:
        with open(wal_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                payload = ev.get("payload", {})
                if payload.get("asset") == asset_name:
                    event_type = ev.get("event_type", "")
                    if event_type in {"features_snapshot", "inference_output", "decision_output"}:
                        events.append(
                            {
                                "sequence": ev.get("sequence"),
                                "timestamp": ev.get("timestamp"),
                                "event_type": event_type,
                                "payload": payload,
                            }
                        )
    except (json.JSONDecodeError, OSError):
        return json_dumps({"error": "Internal error", "code": 500}), 500

    if not events:
        return json_dumps({"events": []}), 200

    events.sort(key=lambda e: e["sequence"], reverse=True)
    events = events[:max_events]
    return json_dumps({"events": events, "total": len(events), "asset": asset_name}), 200


def handle_mt5_status(path: str, query: dict, state_store=None) -> str:
    data = json_dumps(get_mt5_status(state_store=state_store), indent=2)
    cache_set("/mt5/status.json", data)
    return data
