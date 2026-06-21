import json
import os
import threading
import time
from urllib.parse import unquote

class _StrictJSONEncoder(json.JSONEncoder):
    """Fails loud on non-serializable types instead of silently converting via default=str."""

    def default(self, o):
        raise TypeError(
            f"Object of type {type(o).__name__} is not JSON serializable: {o!r}. "
            "Fix the type or add an explicit serializer."
        )


def json_dumps(obj, **kwargs):
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(obj, cls=_StrictJSONEncoder, **kwargs)


_mt5_status: dict | None = None
_mt5_status_lock = threading.Lock()


def set_mt5_status(status: dict) -> None:
    global _mt5_status
    with _mt5_status_lock:
        _mt5_status = status


def get_mt5_status() -> dict:
    with _mt5_status_lock:
        if _mt5_status is not None:
            return dict(_mt5_status)
    return {"connected": False, "status": "UNKNOWN", "last_heartbeat": None, "account": None}


def _get_state_meta() -> tuple[str, int]:
    """Return (state_timestamp, sequence_id) from latest snapshot."""
    from paper_trading.state_store import EngineSnapshot

    snapshot: EngineSnapshot | None = _STORE.load_snapshot()
    if snapshot is not None:
        return snapshot.timestamp, snapshot.sequence_id
    return "", 0


def _with_state_meta(data) -> dict:
    """Wrap response data in a standard envelope with state metadata.

    Returns {"data": <original>, "state_timestamp": "...", "sequence_id": N}.
    Keeps backward compat: fetchApi auto-unwraps on the frontend.
    """
    ts, seq = _get_state_meta()
    return {
        "data": data,
        "state_timestamp": ts,
        "sequence_id": seq,
    }


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _LazyStore:
    def __getattr__(self, name):
        cls = type(self)
        if cls._instance is None:
            from paper_trading.state_store import StateStore

            cls._instance = StateStore(_PROJECT_ROOT)
        return getattr(cls._instance, name)

    _instance = None


_STORE = _LazyStore()

DASHBOARD_DIST = os.path.join(BASE, "dashboard", "dist")
FRONTEND_DIR = os.path.join(BASE, "frontend")
LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "live", "engine.log")
CONFIDENCE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "live", "confidence_buckets.parquet"
)

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
}


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


STATIC_ROUTES_VANILLA = {
    "/": "index.html",
    "/index.html": "index.html",
    "/style.css": "style.css",
    "/script.js": "script.js",
}


def get_index_html():
    dist = os.path.join(DASHBOARD_DIST, "index.html")
    if os.path.exists(dist):
        return os.path.join(DASHBOARD_DIST, "index.html")
    return os.path.join(FRONTEND_DIR, "index.html")


def try_serve_file(path, resp):
    """Try to serve a static file from dist/ or frontend/ by exact path."""
    clean = unquote(path.split("?", 1)[0]).lstrip("/")
    candidates = []
    for root in (DASHBOARD_DIST, FRONTEND_DIR):
        if not root:
            continue
        root_real = os.path.realpath(root)
        fp = os.path.realpath(os.path.join(root_real, clean))
        if os.path.commonpath([root_real, fp]) != root_real:
            continue
        candidates.append(fp)
    for fp in candidates:
        if os.path.exists(fp) and os.path.isfile(fp):
            ext = os.path.splitext(fp)[1]
            ct = MIME_TYPES.get(ext, "application/octet-stream")
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                resp.send_response(200)
                resp.send_header("Content-Type", ct)
                resp.send_header("Cache-Control", "no-cache")
                resp.end_headers()
                resp.wfile.write(data)
                return True
            except Exception:
                pass
    return False
