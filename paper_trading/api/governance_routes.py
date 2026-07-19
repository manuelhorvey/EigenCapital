import json
import os
from datetime import datetime

import pytz

from features.fxstreet_fetcher import confirm_pending_narrative, get_narrative_status
from paper_trading.api.common import (
    cache_set,
    get_server_store,
    json_dumps,
)
from paper_trading.governance.health import compute_all as _compute_health_all
from paper_trading.governance.health import get_latest as _get_health_latest
from paper_trading.governance.multipliers import compute_governance_multipliers
from paper_trading.governance.risk_registry import get_latest as _get_risk_latest
from paper_trading.ops.weekly_review import compute_weekly_review
from paper_trading.state_store import StateStore

ET = pytz.timezone("US/Eastern")


def handle_risk(path: str, query: dict, state_store: StateStore | None = None) -> str:
    data = json_dumps(_get_risk_latest(), indent=2)
    cache_set("/risk.json", data)
    return data


def handle_risk_asset(path: str, query: dict, state_store: StateStore | None = None) -> tuple[str, int]:
    asset = path[len("/risk/") : -len(".json")]
    signal = _get_risk_latest(asset)
    if signal is not None:
        return json_dumps(signal, indent=2), 200
    return json_dumps({"error": "Not found", "code": 404}), 404


def handle_health(path: str, query: dict, state_store: StateStore | None = None) -> str:
    data = json_dumps(_compute_health_all(), indent=2)
    cache_set("/health.json", data)
    return data


def handle_health_asset(path: str, query: dict, state_store: StateStore | None = None) -> tuple[str, int]:
    asset = path[len("/health/") : -len(".json")]
    signal = _get_health_latest(asset)
    if signal is not None:
        return json_dumps(signal, indent=2), 200
    return json_dumps({"error": f"No health score for {asset}", "asset": asset}), 404


def handle_governance(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    governance = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            validity = (asset.get("validity_state") or "YELLOW").upper()
            regime_sl, combined_sl, regime_size, combined_size, floor_active = compute_governance_multipliers(
                validity_state=validity,
                regime_geometry=asset.get("regime_geometry") or {},
                narrative_sl_mult=asset.get("narrative_sl_mult", 1.0),
                liquidity_sl_mult=asset.get("liquidity_sl_mult", 1.0),
                narrative_size_scalar=asset.get("narrative_size_scalar", 1.0),
                liquidity_size_scalar=asset.get("liquidity_size_scalar", 1.0),
            )
            metrics = asset.get("metrics") or {}
            governance[name] = {
                "regime_sl_mult": regime_sl,
                "regime_size_scalar": regime_size,
                "narrative_sl_mult": asset.get("narrative_sl_mult", 1.0),
                "narrative_size_scalar": asset.get("narrative_size_scalar", 1.0),
                "liquidity_sl_mult": asset.get("liquidity_sl_mult", 1.0),
                "liquidity_size_scalar": asset.get("liquidity_size_scalar", 1.0),
                "combined_sl_mult": round(combined_sl, 4),
                "combined_size_scalar": round(combined_size, 4),
                "floor_active": floor_active,
                "validity_state": validity,
                "narrative_regime": asset.get("narrative_regime"),
                "narrative_stale": asset.get("narrative_stale", False),
                "liquidity_regime": asset.get("liquidity_regime", "NORMAL"),
                "halted": asset.get("halt", {}).get("halted", False),
                "soft_warnings": asset.get("soft_warnings", []),
                "crs": metrics.get("crs"),
            }
    data = json_dumps(governance, indent=2)
    cache_set("/governance.json", data)
    return data


def handle_statistical_metrics(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    result: dict[str, dict] = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            metrics = asset.get("metrics") or {}
            result[name] = {
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "psr_gt_0": metrics.get("psr_gt_0"),
                "psr_gt_1": metrics.get("psr_gt_1"),
                "min_trl": metrics.get("min_trl"),
                "crs": metrics.get("crs"),
                "hhi": metrics.get("hhi"),
            }
    data = json_dumps(result, indent=2)
    cache_set("/statistical-metrics.json", data)
    return data


def handle_risk_parity(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    rp = getattr(snapshot, "risk_parity", None) if snapshot else None
    data = json_dumps(rp or {}, indent=2)
    cache_set("/risk-parity.json", data)
    return data


def handle_psi(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    psi_data = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            metrics = asset.get("metrics", {})
            psi = metrics.get("psi_drift", {})
            if psi and psi.get("per_feature"):
                psi_data[name] = {
                    "per_feature": psi["per_feature"],
                    "worst_classification": psi.get("worst_classification", "NO_DRIFT"),
                    "moderate_count": psi.get("moderate_count", 0),
                    "severe_count": psi.get("severe_count", 0),
                    "psi_ok": psi.get("psi_ok", True),
                    "penalty": psi.get("penalty", 0.0),
                }
    data = json_dumps(psi_data, indent=2)
    cache_set("/psi.json", data)
    return data


def handle_trade_outcomes(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    outcomes = store.read_trade_outcomes()
    if outcomes is None:
        outcomes = {
            "overall": {
                "tp_rate": 0.0,
                "sl_rate": 0.0,
                "signal_flip_rate": 0.0,
                "avg_r": 0.0,
                "win_rate": 0.0,
                "profit_factor": None,
            },
            "by_asset": [],
            "updated_at": "",
        }
    data = json_dumps(outcomes, indent=2)
    cache_set("/trade-outcomes.json", data)
    return data


def handle_narrative(path: str, query: dict, state_store: StateStore | None = None) -> str:
    status = get_narrative_status()
    data = json_dumps(status, indent=2)
    cache_set("/narrative.json", data)
    return data


def handle_liquidity(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    snapshot = store.load_snapshot()
    regimes = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            regimes[name] = {
                "regime": asset.get("liquidity_regime", "NORMAL"),
                "sl_mult": asset.get("liquidity_sl_mult", 1.0),
                "size_scalar": asset.get("liquidity_size_scalar", 1.0),
            }
    data = json_dumps(regimes, indent=2)
    cache_set("/liquidity.json", data)
    return data


def handle_narrative_confirm(body: bytes) -> tuple[str, int]:
    ok = confirm_pending_narrative()
    if ok:
        return json_dumps({"status": "confirmed", "message": "Narrative confirmed"}, indent=2), 200
    return (
        json_dumps({"status": "error", "message": "No pending narrative to confirm"}, indent=2),
        400,
    )


def handle_weekly_review(path: str, query: dict, state_store: StateStore | None = None) -> str:
    store = state_store or get_server_store()
    data = json_dumps(compute_weekly_review(store), indent=2)
    cache_set("/weekly-review.json", data)
    return data


def handle_weekly_review_acknowledge(body: bytes, state_store: StateStore | None = None) -> tuple[str, int]:
    store = state_store or get_server_store()
    now = datetime.now(tz=ET).isoformat()
    entry = {"acknowledged_at": now}
    rlp = store.review_log_path
    existing = []
    if os.path.exists(rlp):
        try:
            with open(rlp) as f:
                existing = json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            existing = []
    existing.append(entry)
    with open(rlp, "w") as f:
        json.dump(existing, f, indent=2)
    return json_dumps({"status": "ok", "acknowledged_at": now}, indent=2), 200
