from __future__ import annotations

import errno
import gzip
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from paper_trading.state_store import StateStore


class _StrictJSONEncoder(json.JSONEncoder):
    """Fails loud on non-serializable types instead of silently converting via default=str."""

    def default(self, o):
        raise TypeError(
            f"Object of type {type(o).__name__} is not JSON serializable: {o!r}. "
            "Fix the type or add an explicit serializer."
        )


def json_dumps(obj, **kwargs) -> str:
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(obj, cls=_StrictJSONEncoder, **kwargs)


_MT5_STATUS_DEFAULT = {"connected": False, "status": "UNKNOWN", "last_heartbeat": None, "account": None}


def get_mt5_status(state_store=None) -> dict:
    """Return MT5 connection status from the latest engine snapshot.

    Replaces the old ``_mt5_status`` global variable.  The engine now
    embeds MT5 status in each ``state.json`` snapshot under the ``mt5``
    key, so this reads it from there.  If no snapshot is available,
    returns a disconnected default.

    When ``state_store`` is provided (e.g., from the injected server
    state store), it is used instead of the ``_STORE`` global singleton.
    """
    store = state_store or get_server_store()
    try:
        snapshot = store.load_snapshot()
        if snapshot is not None and hasattr(snapshot, "mt5"):
            mt5 = snapshot.mt5
            if isinstance(mt5, dict):
                return mt5
    except (OSError, AttributeError, ValueError):
        pass
    return dict(_MT5_STATUS_DEFAULT)


def _get_state_meta(state_store=None) -> tuple[str, int]:
    """Return (state_timestamp, sequence_id) from latest snapshot.

    When ``state_store`` is provided (e.g., from the injected server
    state store), it is used instead of the ``_STORE`` global singleton.
    """
    from paper_trading.state_store import EngineSnapshot

    store = state_store or get_server_store()
    snapshot: EngineSnapshot | None = store.load_snapshot()
    if snapshot is not None:
        return snapshot.timestamp, snapshot.sequence_id
    return "", 0


def _with_state_meta(data, state_store=None) -> dict:
    """Wrap response data in a standard envelope with state metadata.

    Returns {"data": <original>, "state_timestamp": "...", "sequence_id": N}.
    Keeps backward compat: fetchApi auto-unwraps on the frontend.

    When ``state_store`` is provided, it is used instead of the
    ``_STORE`` global singleton.
    """
    ts, seq = _get_state_meta(state_store=state_store)
    return {
        "data": data,
        "state_timestamp": ts,
        "sequence_id": seq,
    }


BASE = str(Path(__file__).resolve().parent.parent)

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


# Server-context StateStore — initialized explicitly at server startup
# via init_server_store(). Route handlers always receive state_store via
# the handler dispatch (handler.py passes self.server._state_store).
# This module-level variable is only for scripts and tests that call
# handlers directly; prefer injecting state_store explicitly.
_SERVER_STORE: StateStore | None = None


def init_server_store(store: StateStore | None = None, base_dir: str | None = None) -> None:
    """Initialize the server-context StateStore.

    Called once at server startup by ``serve.py``. Accepts an optional
    pre-existing ``store`` instance (preferred) or a base_dir to create one.
    """
    global _SERVER_STORE
    if store is not None:
        _SERVER_STORE = store
        return
    from paper_trading.state_store import StateStore

    _SERVER_STORE = StateStore(base_dir or _PROJECT_ROOT)


def get_server_store() -> StateStore:
    """Return the server-context StateStore.

    Raises RuntimeError if the store has not been initialized via
    :func:`init_server_store`.  By the time API routes are called
    (after server startup), the store is guaranteed to be initialized.
    """
    if _SERVER_STORE is None:
        raise RuntimeError("StateStore not initialized. Call init_server_store() before serving requests.")
    return _SERVER_STORE


def reset_server_store() -> None:
    """Reset the server-context StateStore. Test-harness use only."""
    global _SERVER_STORE
    _SERVER_STORE = None


# Provenance store — lazily initialized from env var or explicitly
_PP_STORE: object | None = None  # actually SqliteProvenanceStore, avoid import at module level


def get_provenance_store():
    """Return a SqliteProvenanceStore, lazily initialised from env var.

    Database path comes from ``EIGENCAPITAL_PROVENANCE_DB`` env var, or
    defaults to ``~/.eigencapital/data/provenance.db``.
    """
    global _PP_STORE
    if _PP_STORE is not None:
        return _PP_STORE
    from pathlib import Path

    from eigencapital.domain.provenance.provenance_store import SqliteProvenanceStore

    db = os.environ.get(
        "EIGENCAPITAL_PROVENANCE_DB",
        str(Path.home() / ".eigencapital" / "data" / "provenance.db"),
    )
    if not Path(db).is_file():
        return None
    store = SqliteProvenanceStore(db)
    try:
        store.initialize()
    except (OSError, RuntimeError):
        return None
    _PP_STORE = store
    return _PP_STORE


DASHBOARD_DIST = str(Path(BASE) / "dashboard" / "dist")
FRONTEND_DIR = str(Path(BASE) / "frontend")
_PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent.parent
LOG_PATH = str(_PROJECT_ROOT_PATH / "data" / "live" / "engine.log")
CONFIDENCE_PATH = str(_PROJECT_ROOT_PATH / "data" / "live" / "confidence_buckets.parquet")
OPTIMIZATION_PATH = str(_PROJECT_ROOT_PATH / "data" / "live" / "optimization.json")
LIFECYCLE_PATH = str(_PROJECT_ROOT_PATH / "data" / "live" / "lifecycle.json")
LATEST_ATTRIBUTION_PATH = str(_PROJECT_ROOT_PATH / "data" / "live" / "latest_attribution.json")
HEALTHCHECK_PATH = str(_PROJECT_ROOT_PATH / "data" / "logs" / "healthcheck" / "latest.json")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".js": "application/javascript",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".json": "application/json",
}

_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL: dict[str, float] = {
    "/state.json": 5.0,
    "/trades.json": 15.0,
    "/equity_history.json": 30.0,
    "/confidence.json": 15.0,
    "/volatility.json": 15.0,
    "/risk.json": 30.0,
    "/shadow-actions": 30.0,
    "/health.json": 30.0,
    "/narrative.json": 30.0,
    "/liquidity.json": 30.0,
    "/governance.json": 30.0,
    "/risk-parity.json": 30.0,
    "/psi.json": 30.0,
    "/weekly-review.json": 30.0,
    "/trade-outcomes.json": 5.0,
    "/healthcheck.json": 30.0,
}


def clear_cache() -> None:
    """Clear the in-memory API response cache.

    Called after reset_dashboard.py deletes persistence files so the
    next request returns fresh (zero-state) data instead of stale
    cached responses.
    """
    _CACHE.clear()


def cache_get(key: str) -> str | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() > expiry:
        del _CACHE[key]
        return None
    return value


def cache_set(key: str, value: str, ttl: float | None = None) -> None:
    if ttl is None:
        base_key = key.split("?")[0]
        ttl = _CACHE_TTL.get(base_key, 5.0)
    _CACHE[key] = (value, time.monotonic() + ttl)


_FALLBACK_VOL_BASELINES = {
    "GC": 0.009129,
    "NZDJPY": 0.006581,
    "CADJPY": 0.005989,
    "USDCAD": 0.004463,
    "EURAUD": 0.005026,
    "AUDJPY": 0.006759,
    "GBPJPY": 0.006138,
    "USDJPY": 0.004498,
    "USDCHF": 0.004307,
    "GBPUSD": 0.005595,
    "CHFJPY": 0.004780,
    "EURCAD": 0.003476,
    "DJI": 0.008061,
    "GBPCHF": 0.004500,
    "AUDUSD": 0.005500,
    "NZDUSD": 0.005000,
    "CADCHF": 0.004500,
    "GBPCAD": 0.004500,
    # "GBPNZD": 0.005000,  # removed 2026-06-20
    "NZDCAD": 0.004500,
    "CL": 0.015000,
    "ES": 0.008000,
    "NQ": 0.010000,
}


def get_vol_baselines() -> dict:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    return cfg.vol_baselines or _FALLBACK_VOL_BASELINES


# ── Rate Limiting ───────────────────────────────────────────────────────────
# Configurable via EIGENCAPITAL_RATE_LIMIT (max requests) env var.
# Window duration (60s) could also be made configurable via env var
# (e.g. EIGENCAPITAL_RATE_LIMIT_WINDOW) if needed.

_RATE_LIMIT_MAX: int = int(os.environ.get("EIGENCAPITAL_RATE_LIMIT", "100"))
_RATE_LIMIT_WINDOW: float = 60.0


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP address using monotonic time.
    Thread-safe via a per-instance lock for use with ThreadingMixIn servers.
    """

    def __init__(self, max_requests: int = _RATE_LIMIT_MAX, window_seconds: float = _RATE_LIMIT_WINDOW) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> bool:
        """Check and record a request from *client_ip*.  Returns True if allowed."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows.setdefault(client_ip, [])
            while window and window[0] < cutoff:
                window.pop(0)
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            return True

    def remaining(self, client_ip: str) -> int:
        """Number of requests remaining in the current window for *client_ip*."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows.get(client_ip, [])
            while window and window[0] < cutoff:
                window.pop(0)
            return max(0, self.max_requests - len(window))


# Global rate limiter instance shared across handler threads
_RATE_LIMITER = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _RATE_LIMITER


# ── Authentication ──────────────────────────────────────────────────────────

_AUTH_TOKEN: str | None = None  # None = not yet loaded, "" = no auth configured


def _load_auth_token() -> str:
    global _AUTH_TOKEN
    if _AUTH_TOKEN is None:
        from paper_trading.config_manager import get_config

        cfg = get_config()
        _AUTH_TOKEN = cfg.api_token or ""
        if not _AUTH_TOKEN and os.environ.get("EIGENCAPITAL_DISABLE_AUTH") != "1":
            _AUTH_TOKEN = secrets.token_hex(32)
            logging.getLogger("eigencapital.auth").info(
                "Auto-generated API token for dashboard (dev mode on 127.0.0.1)"
            )
        elif not _AUTH_TOKEN:
            logging.getLogger("eigencapital.auth").warning(
                "No API auth token configured. Set EIGENCAPITAL_API_TOKEN env var or api_token in config. "
                "Authentication is REQUIRED by default. To disable auth in development, "
                "set EIGENCAPITAL_DISABLE_AUTH=1."
            )
        else:
            logging.getLogger("eigencapital.auth").info(
                "API auth enabled (token from %s)",
                "env EIGENCAPITAL_API_TOKEN" if os.environ.get("EIGENCAPITAL_API_TOKEN") else "config file",
            )
    return _AUTH_TOKEN


def require_auth(headers: dict) -> bool:
    """Check Authorization header against configured token.

    Returns True if auth token is valid.
    Returns False if token is missing, invalid, or no token is configured
    (unless EIGENCAPITAL_DISABLE_AUTH=1 is set for development).
    """
    token = _load_auth_token()
    if not token:
        # Secure by default: reject when no token is configured unless
        # the operator explicitly opts out via env var.
        if os.environ.get("EIGENCAPITAL_DISABLE_AUTH") == "1":
            logging.getLogger("eigencapital.auth").warning("Auth explicitly disabled via EIGENCAPITAL_DISABLE_AUTH=1")
            return True
        return False
    provided = headers.get("Authorization", "")
    if provided.startswith("Bearer "):
        return hmac.compare_digest(provided[7:], token)
    return False


def auth_headers() -> dict:
    """Return CORS and auth-related headers for responses."""
    return {
        "Access-Control-Allow-Origin": "http://127.0.0.1:3000",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Expose-Headers": "Authorization",
    }


STATIC_ROUTES_VANILLA = {
    "/": "index.html",
    "/index.html": "index.html",
    "/style.css": "style.css",
    "/script.js": "script.js",
}


def get_index_html():
    dist = str(Path(DASHBOARD_DIST) / "index.html")
    if Path(dist).exists():
        return str(Path(DASHBOARD_DIST) / "index.html")
    return str(Path(FRONTEND_DIR) / "index.html")


def try_serve_file(path, resp):
    """Try to serve a static file from dist/ or frontend/ by exact path."""
    clean = unquote(path.split("?", 1)[0]).lstrip("/")
    candidates = []
    for root in (DASHBOARD_DIST, FRONTEND_DIR):
        if not root:
            continue
        root_real = str(Path(root).resolve())
        fp = str(Path(root_real) / clean)
        if Path(root_real) not in Path(fp).parents:
            continue
        candidates.append(fp)
    for fp in candidates:
        if Path(fp).exists() and Path(fp).is_file():
            ext = Path(fp).suffix
            ct = MIME_TYPES.get(ext, "application/octet-stream")
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                resp.send_response(200)
                resp.send_header("Content-Type", ct)
                if "/assets/" in path:
                    resp.send_header("Cache-Control", "public, max-age=31536000, immutable")
                else:
                    resp.send_header("Cache-Control", "no-cache")
                if len(data) > 512 and "gzip" in resp.headers.get("Accept-Encoding", ""):
                    data = gzip.compress(data)
                    resp.send_header("Content-Encoding", "gzip")
                resp.end_headers()
                try:
                    resp.wfile.write(data)
                except OSError as e:
                    if e.errno in (errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED):
                        pass  # client disconnected — continue to return True
                    else:
                        raise
                return True
            except (OSError, ValueError, TypeError):
                pass
    return False
