"""State bundle — fast snapshot + async live source refresh.

Architecture
------------
The bundle combines three data sources:
  1. Engine snapshot  (fast, disk-backed, <10ms)
  2. Health scores    (slow, 19 assets × file I/O, up to 15s)
  3. MT5 status       (fast, in-memory, <1ms)

Source 1 is always loaded synchronously.
Sources 2-3 are NEVER fetched synchronously. They are:
  - Returned from _LIVE_CACHE if fresh (≤5s old)
  - Returned from _LIVE_CACHE as stale fallback if available
  - Returned as a placeholder if no cache exists
  - Refreshed in the background for the NEXT poll

This guarantees the bundle response is always fast (<10ms for
snapshot load) and never blocks on slow computations.

Failure resilience
------------------
- Timeout/error results ARE cached (with is_fresh=False) so the
  expensive computation is not repeated on every poll.
- _LIVE_CACHE has a threading.Lock for thread-safe access.
- Background refresh failures are logged and the error is cached.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from paper_trading.api.common import (
    _STORE,
    cache_get,
    cache_set,
    get_mt5_status,
    json_dumps,
)
from paper_trading.governance.health import compute_all as compute_health_all
from paper_trading.ops.market_hours import is_market_closed

UTC = timezone.utc

logger = logging.getLogger("quorrin.bundle")

BUNDLE_VERSION = "1.0.0"
BUNDLE_CACHE_TTL = 5.0
LIVE_FETCH_TIMEOUT = 15.0  # compute_health_all: 19 assets × file I/O; 5s was too tight
_LIVE_CACHE_TTL = 5.0
_MAX_LIVE_AGE_SECONDS = 10.0  # beyond this, live source is stale regardless of cache

_LIVE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bundle-live")
_LIVE_CACHE_LOCK = threading.Lock()

# Each cached live entry: (data, wall_clock_expiry, fetch_timestamp, is_fallback)
_LIVE_CACHE: dict[str, tuple[dict, float, float, bool]] = {}
_LIVE_REFRESH_IN_FLIGHT: dict[str, bool] = {}

# ── Background refresh ─────────────────────────────────────────────────────


def _background_refresh(name: str, fetch_fn: Callable[[], Any]) -> None:
    """Fetch a live source asynchronously and cache the result.

    Called by _live_get() via the ThreadPool when cache is stale.
    Never raises — all exceptions are caught and cached as errors.
    On success, the result is cached with is_fresh=True and a 5s TTL.
    On failure, the result is cached with is_fresh=False so the
    expensive computation is not retried on the next poll.

    Releases the in-flight guard in a finally block so concurrent
    polls during the refresh window don't submit duplicate work.
    """
    try:
        result = fetch_fn()
        now = time.time()
        result["fetch_time"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        result["fetch_age_seconds"] = 0.0
        result["is_fresh"] = True
        with _LIVE_CACHE_LOCK:
            _LIVE_CACHE[name] = (result, now + _LIVE_CACHE_TTL, now, False)
    except Exception as exc:
        logger.warning("bundle bg refresh '%s' failed: %s", name, exc)
        # Cache the failure so the next N polls don't re-attempt.
        now = time.time()
        placeholder = {
            "fetch_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "fetch_age_seconds": 0.0,
            "is_fresh": False,
            "status": "error",
            "error": str(exc),
        }
        with _LIVE_CACHE_LOCK:
            _LIVE_CACHE[name] = (placeholder, now + _LIVE_CACHE_TTL, now, True)
    finally:
        with _LIVE_CACHE_LOCK:
            _LIVE_REFRESH_IN_FLIGHT.pop(name, None)


def _live_get(name: str, fetch_fn: Callable[[], Any]) -> dict:
    """Return live data from cache or placeholder — NEVER blocks.

    Priority:
      1. Fresh cache (TTL + max age both satisfied) → return immediately
      2. Stale cache (TTL expired but within max age) → return, trigger bg refresh
      3. No cache → return placeholder, trigger bg refresh

    Uses ``_LIVE_REFRESH_IN_FLIGHT`` to prevent duplicate background
    refreshes when the dashboard polls faster than the refresh completes.

    The background refresh runs in the ThreadPool and populates
    _LIVE_CACHE for subsequent calls.  Since the first request
    returns a placeholder, the dashboard shows data immediately
    (with degraded health) and the health data arrives on the
    next poll cycle.
    """
    now = time.time()

    # ── 1. Fresh cache hit ────────────────────────────────────────────
    with _LIVE_CACHE_LOCK:
        cached = _LIVE_CACHE.get(name)
    if cached is not None:
        _, expiry, fetched_at, _was_fallback = cached
        if now < expiry and (now - fetched_at) < _MAX_LIVE_AGE_SECONDS:
            return cached[0]

    # ── 2. Trigger background refresh (non-blocking) with dedup ──────
    with _LIVE_CACHE_LOCK:
        if not _LIVE_REFRESH_IN_FLIGHT.get(name):
            _LIVE_REFRESH_IN_FLIGHT[name] = True
            _LIVE_EXECUTOR.submit(_background_refresh, name, fetch_fn)

    # ── 3. Return stale cache if available ────────────────────────────
    if cached is not None:
        data, _expiry, fetched_at, _was_fallback = cached
        age = now - fetched_at
        data["fetch_time"] = datetime.fromtimestamp(fetched_at, tz=UTC).isoformat().replace("+00:00", "Z")
        data["fetch_age_seconds"] = round(age, 1)
        data["is_fresh"] = age < _MAX_LIVE_AGE_SECONDS
        if age >= _MAX_LIVE_AGE_SECONDS:
            logger.warning("bundle live source '%s' fallback is stale (%.1fs old)", name, age)
        return data

    # ── 4. No cache at all — return placeholder ───────────────────────
    logger.warning("bundle live source '%s' has no cached data — returning placeholder", name)
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "fetch_time": now_iso,
        "fetch_age_seconds": 0.0,
        "is_fresh": False,
        "status": "pending",
    }


# ── Bundle handler ─────────────────────────────────────────────────────────


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

    # ── Live sources fetched via fast cache — NEVER blocks ────────────
    health_result = _live_get("health", compute_health_all)
    mt5_result = _live_get("mt5", get_mt5_status)

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

    bundle: dict[str, Any] = {
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
