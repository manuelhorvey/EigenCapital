import json
import logging
import os
from dataclasses import asdict
from datetime import datetime

import pytz

from paper_trading.api.common import (
    _STORE,
    CONFIDENCE_PATH,
    HEALTHCHECK_PATH,
    LOG_PATH,
    OPTIMIZATION_PATH,
    cache_get,
    cache_set,
    get_vol_baselines,
    json_dumps,
)
from paper_trading.config_manager import get_config
from paper_trading.metrics.exposition import global_registry
from paper_trading.ops.market_hours import is_market_closed
from paper_trading.portfolio_builder import build_paper_portfolio
from paper_trading.state_store import CONTRACT_VERSION

ET = pytz.timezone("US/Eastern")


def handle_state(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    cached = cache_get(path)
    if cached is not None:
        return cached
    snapshot = store.load_snapshot()
    if snapshot is not None:
        state = asdict(snapshot)
        status = state.setdefault("engine_status", {})
        status["market_closed"] = is_market_closed()
        if "last_update" not in status or status["last_update"] is None:
            status["last_update"] = state.get("timestamp", "")
        assets = state.get("assets") or {}
        portfolio = state.get("portfolio") or {}
        if isinstance(portfolio, dict) and isinstance(assets, dict):
            allocs = portfolio.setdefault("allocations", {})
            cfg = get_config()
            pf = build_paper_portfolio(cfg.halt)
            for name in assets:
                if name not in allocs and name in pf:
                    allocs[name] = pf[name]["alloc"]
        data = json_dumps(state)
    else:
        cfg = get_config()
        pf = build_paper_portfolio(cfg.halt)
        data = json_dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "sequence_id": 0,
                "schema_version": "1.0.0",
                "timestamp": datetime.now(tz=ET).isoformat(),
                "engine_status": {
                    "initialized": True,
                    "last_update": None,
                    "start_time": None,
                    "market_closed": is_market_closed(),
                },
                "portfolio": {
                    "total_value": 0,
                    "total_return": 0,
                    "days_running": 0,
                    "runtime_hours": 0,
                    "start_date": "",
                    "start_datetime": "",
                    "last_update": None,
                    "capital": cfg.capital,
                    "allocations": {n: spec["alloc"] for n, spec in pf.items()},
                    "deployment_cleared": True,
                    "open_positions": 0,
                    "closed_trades": 0,
                    "execution_state": "ACTIVE",
                    "average_validity_exposure": 1.0,
                },
                "assets": {},
                "halt_conditions": dict(cfg.halt),
            },
            indent=2,
        )
    cache_set("/state.json", data)
    return data


def handle_trades(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    limit = max(1, min(int(query.get("limit", 10)), 200))
    offset = max(0, int(query.get("offset", 0)))
    trades = store.read_trades(limit + offset)

    seen: set[tuple] = set()
    deduped: list[dict] = []

    for t in trades:
        key = (
            t.get("asset"),
            t.get("entry_date"),
            t.get("exit_date"),
            t.get("reason"),
            round(t.get("entry", 0), 4),
            round(t.get("exit", 0), 4),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    if len(deduped) < limit + offset:
        snapshot = store.load_snapshot()
        if snapshot and snapshot.assets:
            for aname, adata in snapshot.assets.items():
                for t in (adata.get("metrics") or {}).get("trade_log") or []:
                    exit_date = t.get("exit_date")
                    if exit_date is None:
                        continue
                    key = (
                        t.get("asset"),
                        t.get("entry_date"),
                        exit_date,
                        t.get("reason"),
                        round(t.get("entry", 0), 4),
                        round(t.get("exit", 0), 4),
                    )
                    if key not in seen:
                        seen.add(key)
                        deduped.append(t)
            deduped.sort(key=lambda x: x.get("exit_date", ""), reverse=True)

    data = json_dumps(deduped[offset : offset + limit])
    cache_set(path, data)
    return data


def handle_equity_history(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    history = store.read_equity_history()
    data = json_dumps(history)
    cache_set("/equity_history.json", data)
    return data


def handle_confidence(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    cached = cache_get(path)
    if cached is not None:
        return cached
    snapshot = store.load_snapshot()
    if snapshot and snapshot.assets:
        live = {}
        for name, asset in snapshot.assets.items():
            sig = asset.get("last_signal") or {}
            conf = sig.get("confidence", 0)
            if conf <= 1:
                conf = conf * 100
            bucket_low = min(int(conf // 10) * 10, 90)
            bucket = f"{bucket_low}-{bucket_low + 10}"
            live.setdefault(name, {})
            live[name][bucket] = live[name].get(bucket, 0) + 1
        historical = []
        try:
            if os.path.exists(CONFIDENCE_PATH):
                import pandas as pd

                df = pd.read_parquet(CONFIDENCE_PATH)
                historical = json.loads(df.to_json(orient="records", default_handler=str))
        except Exception:
            pass
        data = json_dumps({"live": live, "historical": historical}, indent=2)
    else:
        data = json_dumps({"live": {}, "historical": []})
    cache_set("/confidence.json", data)
    return data


def handle_volatility(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    snapshot = store.load_snapshot()
    regimes = []
    vol_baselines = get_vol_baselines()
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            training_vol = vol_baselines.get(name)
            metrics = asset.get("metrics") or {}
            pos = metrics.get("position") or {}
            current_vol = pos.get("current_vol") if pos else None
            if training_vol is not None and current_vol is not None:
                ratio = current_vol / training_vol
                if 0.80 <= ratio <= 1.20:
                    status = "green"
                elif (0.70 <= ratio < 0.80) or (1.20 < ratio <= 1.30):
                    status = "amber"
                else:
                    status = "red"
                regimes.append(
                    {
                        "asset": name,
                        "training_vol": training_vol,
                        "current_vol": current_vol,
                        "ratio": round(ratio, 4),
                        "status": status,
                    }
                )
    data = json_dumps(regimes, indent=2)
    cache_set("/volatility.json", data)
    return data


def handle_logs(path: str, query: dict, state_store=None) -> str:
    try:
        with open(LOG_PATH) as f:
            lines = f.readlines()
        boundary = None
        for i in range(len(lines) - 1, -1, -1):
            if "Server stopped." in lines[i]:
                boundary = i + 1
                break
        tail = "".join(lines[boundary:][-200:]) if boundary is not None else "".join(lines[-200:])
        return tail
    except FileNotFoundError:
        return "[no log file yet]"


def handle_ping(path: str, query: dict, state_store=None) -> str:
    return json_dumps({"status": "ok"}, indent=2)


def handle_engine_health(path: str, query: dict, state_store=None) -> str:
    store = state_store or _STORE
    import time
    from pathlib import Path

    state_path = Path(store.state_path) if hasattr(store, "state_path") else None
    state_file_age = -1
    state_exists = False
    status = "ok"

    if state_path and state_path.exists():
        state_exists = True
        state_file_age = time.time() - state_path.stat().st_mtime
        if state_file_age > 120:
            status = "stale"
    else:
        status = "no_state"

    snapshot = store.load_snapshot()
    seq = snapshot.sequence_id if snapshot else None

    return json_dumps(
        {
            "status": status,
            "server_time": datetime.now(ET).isoformat(),
            "state_exists": state_exists,
            "state_file_age_s": round(state_file_age, 1),
            "state_sequence_id": seq,
            "engine_alive": status == "ok" and state_file_age < 120,
        },
        indent=2,
    )


def handle_optimization(path: str, query: dict, state_store=None) -> str:
    """Serve drift detector optimization output from data/live/optimization.json."""
    try:
        with open(OPTIMIZATION_PATH) as f:
            data = f.read()
        cache_set("/optimization.json", data)
        return data
    except FileNotFoundError:
        return json_dumps({"error": "not_found", "message": "No optimization data available yet"}, indent=2)
    except json.JSONDecodeError:
        return json_dumps({"error": "invalid_json", "message": "optimization.json is corrupt"}, indent=2)


def handle_healthcheck(path: str, query: dict, state_store=None) -> str:
    """Serve model health monitor report from data/logs/healthcheck/latest.json."""
    try:
        with open(HEALTHCHECK_PATH) as f:
            data = f.read()
        cache_set("/healthcheck.json", data)
        return data
    except FileNotFoundError:
        return json_dumps({"error": "not_found", "message": "No health check data available yet"}, indent=2)
    except json.JSONDecodeError:
        return json_dumps({"error": "invalid_json", "message": "healthcheck/latest.json is corrupt"}, indent=2)


def handle_metrics(path: str, query: dict, state_store=None) -> str:
    return global_registry().render()


def handle_log_error(body: bytes, state_store=None) -> tuple[str, int]:
    """POST handler — logs client-side errors sent from the dashboard."""
    try:
        import json as _json

        payload = _json.loads(body.decode("utf-8"))
        error = payload.get("error", "unknown")
        stack = payload.get("stack", "")
        name = payload.get("name", "Error")
        logger = logging.getLogger("eigencapital.dashboard_error")
        logger.warning("FE error [%s]: %s\n%s", name, error, stack)
        return json_dumps({"status": "ok"}), 200
    except Exception as exc:
        logger.debug("Failed to log client error: %s", exc)
        return json_dumps({"status": "error"}), 500


def handle_clear_cache(path: str, query: dict, state_store=None) -> str:
    """Clear all in-memory caches after a reset.

    POST handler: clears the API response cache (common.clear_cache)
    and the live data cache (bundle.clear_live_cache) so the next
    request returns fresh data instead of stale cached responses.
    """
    from paper_trading.api.bundle import clear_live_cache
    from paper_trading.api.common import clear_cache

    clear_cache()
    clear_live_cache()

    return json_dumps({"status": "ok", "message": "Server caches cleared"}, indent=2)
