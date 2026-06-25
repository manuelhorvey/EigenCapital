import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import asdict
from datetime import UTC, datetime

from paper_trading.api.common import (
    _STORE,
    cache_get,
    cache_set,
    get_mt5_status,
    json_dumps,
)
from paper_trading.governance.health import compute_all as compute_health_all
from paper_trading.ops.market_hours import is_market_closed

logger = logging.getLogger("quantforge.bundle")

BUNDLE_VERSION = "1.0.0"
BUNDLE_CACHE_TTL = 5.0
LIVE_FETCH_TIMEOUT = 15.0  # compute_health_all iterates 19 assets with per-file I/O; 5s was too tight
_LIVE_CACHE_TTL = 5.0
_MAX_LIVE_AGE_SECONDS = 10.0  # beyond this, live source is stale regardless of cache

_LIVE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bundle-live")

# Each cached live entry: (data, wall_clock_expiry, fetch_timestamp, is_fallback)
_LIVE_CACHE: dict[str, tuple[dict, float, float, bool]] = {}


def _fetch_live(name: str, fetch_fn) -> dict:
    """Fetch a live sub-source with timeout + fallback to last known value.

    Returns dict with at minimum:
        { "fetch_time": "<iso>", "fetch_age_seconds": N, "is_fresh": bool }

    Never raises. MT5 timeout does not stall the bundle.
    """
    cached = _LIVE_CACHE.get(name)
    now = time.time()

    if cached is not None:
        _, expiry, _fetched_at, _was_fallback = cached
        if now < expiry and (now - _fetched_at) < _MAX_LIVE_AGE_SECONDS:
            return cached[0]

    fetch_start = time.time()
    try:
        future = _LIVE_EXECUTOR.submit(fetch_fn)
        result = future.result(timeout=LIVE_FETCH_TIMEOUT)
        result["fetch_time"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        result["fetch_age_seconds"] = 0.0
        result["is_fresh"] = True
        _LIVE_CACHE[name] = (result, time.time() + _LIVE_CACHE_TTL, fetch_start, False)
        return result
    except TimeoutError:
        logger.warning("bundle live source '%s' timed out after %.1fs", name, LIVE_FETCH_TIMEOUT)
    except Exception as exc:
        logger.warning("bundle live source '%s' failed: %s", name, exc)

    if cached is not None:
        data, _expiry, _fetched_at, _was_fallback = cached
        age = time.time() - _fetched_at
        data["fetch_time"] = datetime.fromtimestamp(_fetched_at, tz=UTC).isoformat().replace("+00:00", "Z")
        data["fetch_age_seconds"] = round(age, 1)
        data["is_fresh"] = age < _MAX_LIVE_AGE_SECONDS
        if age >= _MAX_LIVE_AGE_SECONDS:
            logger.warning("bundle live source '%s' fallback is stale (%.1fs old)", name, age)
        return data

    logger.warning("bundle live source '%s' has no cached fallback — returning empty", name)
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "fetch_time": now_iso,
        "fetch_age_seconds": 0.0,
        "is_fresh": False,
        "error": "no_data",
    }


def handle_state_bundle(path: str, query: dict) -> str:
    cached = cache_get("/state-bundle.json")
    if cached is not None:
        return cached

    snapshot_obj = _STORE.load_snapshot()
    now = datetime.now(UTC)
    server_time_iso = now.isoformat().replace("+00:00", "Z")
    engine_seq = snapshot_obj.sequence_id if snapshot_obj else 0

    if snapshot_obj is not None:
        snapshot = asdict(snapshot_obj)
    else:
        snapshot = {
            "contract_version": 0,
            "sequence_id": 0,
            "timestamp": "",
            "assets": {},
            "open_positions": {},
            "engine_status": {"initialized": False, "market_closed": is_market_closed()},
            "portfolio": {},
            "halt_conditions": {},
        }

    if "engine_status" in snapshot and isinstance(snapshot["engine_status"], dict):
        snapshot["engine_status"]["market_closed"] = is_market_closed()

    snapshot_timestamp = snapshot.get("timestamp", "")

    health_result = _fetch_live("health", compute_health_all)
    mt5_result = _fetch_live("mt5", get_mt5_status)

    # Determine bundle integrity status
    health_ok = health_result.get("is_fresh", False)
    mt5_ok = mt5_result.get("is_fresh", False)
    snapshot_ok = bool(snapshot_obj)

    if snapshot_ok and health_ok and mt5_ok:
        bundle_status = "ok"
    elif not snapshot_ok:
        bundle_status = "partial_failure"
    else:
        bundle_status = "degraded"

    # Temporal alignment: compute the wall-clock age of each sub-source
    live_times = []
    for source_name, source_result in [("health", health_result), ("mt5", mt5_result)]:
        ft = source_result.get("fetch_age_seconds", None)
        if ft is not None:
            live_times.append(ft)
    max_live_age = max(live_times) if live_times else None

    bundle = {
        "meta": {
            "version": BUNDLE_VERSION,
            "server_time": server_time_iso,
            "status": bundle_status,
            "snapshot_time": snapshot_timestamp,
            "snapshot_sequence_id": engine_seq,
            "max_live_age_seconds": max_live_age,
            "request_id": str(uuid.uuid4())[:8],
        },
        "snapshot": snapshot,
        "live": {
            "health": health_result,
            "mt5": mt5_result,
        },
    }

    data = json_dumps(bundle)

    # Cache key includes engine sequence to prevent cache poisoning after engine restart
    cache_key = f"/state-bundle.json?seq={engine_seq}"
    cache_set(cache_key, data, ttl=BUNDLE_CACHE_TTL)

    # Also store under standard key for backward compat
    cache_set("/state-bundle.json", data, ttl=BUNDLE_CACHE_TTL)

    return data
