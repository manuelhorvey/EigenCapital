import json
import os
import sys
import time
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_trading.config_manager import get_config
from paper_trading.health_score import compute_all as _compute_health_all
from paper_trading.health_score import get_latest as _get_health_latest
from paper_trading.portfolio_builder import build_paper_portfolio
from paper_trading.risk_governance import get_latest as _get_risk_latest
from paper_trading.state_store import StateStore

_STORE = StateStore(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PORT = 5000
BASE = os.path.dirname(os.path.abspath(__file__))

DASHBOARD_DIST = os.path.join(BASE, "dashboard", "dist")
FRONTEND_DIR = os.path.join(BASE, "frontend")
LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "live", "engine.log")
CONFIDENCE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "live", "confidence_buckets.parquet")

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
}


def _cache_get(key: str) -> str | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() > expiry:
        del _CACHE[key]
        return None
    return value


def _cache_set(key: str, value: str, ttl: float | None = None) -> None:
    if ttl is None:
        ttl = _CACHE_TTL.get(key, 5.0)
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
}


def _get_vol_baselines() -> dict:
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
    clean = path.split("?")[0].lstrip("/")
    candidates = []
    if DASHBOARD_DIST:
        candidates.append(os.path.join(DASHBOARD_DIST, clean))
    if FRONTEND_DIR:
        candidates.append(os.path.join(FRONTEND_DIR, clean))
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


def serve(port=DEFAULT_PORT, shutdown_event=None):
    import gzip
    import http.server
    import socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _send_json(self, data: str, status: int = 200) -> None:
            body = data.encode("utf-8")
            accept_gzip = self.headers.get("Accept-Encoding", "")
            if "gzip" in accept_gzip and len(body) > 512:
                body = gzip.compress(body)
                ct = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Encoding", "gzip")
            else:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, data: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode("utf-8"))

        @staticmethod
        def _parse_query(query_string: str) -> dict[str, str]:
            params = {}
            if query_string:
                for part in query_string.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        params[k] = v
            return params

        def do_GET(self):
            qs = self.path.split("?", 1)
            path = qs[0]
            query = self._parse_query(qs[1] if len(qs) > 1 else "")

            # Serve root and index.html from React build or vanilla fallback
            if path in ("/", "/index.html"):
                idx_path = get_index_html()
                try:
                    with open(idx_path, "rb") as f:
                        data = f.read()
                    ext = os.path.splitext(idx_path)[1]
                    ct = MIME_TYPES.get(ext, "text/html; charset=utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(data)
                except FileNotFoundError:
                    self.send_response(404)
                    self.end_headers()
                return

            # Try static file from dist/ or frontend/
            if path.startswith("/assets/") or path.startswith("/favicon.ico"):
                if try_serve_file(path, self):
                    return
                self.send_response(404)
                self.end_headers()
                return

            # API endpoints
            if path in _CACHE_TTL:
                cached = _cache_get(path)
                if cached is not None:
                    self._send_json(cached)
                    return

            if path == "/state.json":
                snapshot = _STORE.load_snapshot()
                if snapshot is not None:
                    data = json.dumps(asdict(snapshot), indent=2, default=str)
                else:
                    cfg = get_config()
                    pf = build_paper_portfolio(cfg.halt)
                    data = json.dumps(
                        {
                            "engine_status": {"initialized": True, "last_update": None, "start_time": None},
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
                                "satellite_allocation_pct": 5.0,
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
                _cache_set("/state.json", data)
                self._send_json(data)
            elif path == "/trades.json":
                limit = max(1, min(int(query.get("limit", 10)), 200))
                offset = max(0, int(query.get("offset", 0)))
                trades = _STORE.read_trades(limit + offset)

                # De-duplicate using a unique signature with rounded floats
                seen = set()
                deduped = []

                def _sig(t):
                    return (t.get("asset"), t.get("exit_date"), t.get("reason"),
                            round(t.get("entry", 0), 4), round(t.get("exit", 0), 4))

                for t in trades:
                    s = _sig(t)
                    if s not in seen:
                        seen.add(s)
                        deduped.append(t)

                if len(deduped) < limit + offset:
                    snapshot = _STORE.load_snapshot()
                    if snapshot and snapshot.assets:
                        for aname, adata in snapshot.assets.items():
                            for t in adata.get("metrics", {}).get("trade_log", []):
                                if t.get("exit_date") is None:
                                    continue
                                s = _sig(t)
                                if s not in seen:
                                    seen.add(s)
                                    deduped.append(t)
                        deduped = sorted(deduped, key=lambda x: x.get("exit_date", ""), reverse=True)

                data = json.dumps(deduped[offset : offset + limit], default=str)
                _cache_set("/trades.json", data)
                self._send_json(data)
            elif path == "/equity_history.json":
                history = _STORE.read_equity_history()
                data = json.dumps(history, default=str)
                _cache_set("/equity_history.json", data)
                self._send_json(data)
            elif path == "/confidence.json":
                snapshot = _STORE.load_snapshot()
                if snapshot and snapshot.assets:
                    live = {}
                    for name, asset in snapshot.assets.items():
                        sig = asset.get("last_signal", {})
                        conf = sig.get("confidence", 0)
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
                    data = json.dumps({"live": live, "historical": historical}, indent=2, default=str)
                else:
                    data = json.dumps({"live": {}, "historical": []})
                _cache_set("/confidence.json", data)
                self._send_json(data)
            elif path == "/volatility.json":
                snapshot = _STORE.load_snapshot()
                regimes = []
                vol_baselines = _get_vol_baselines()
                if snapshot and snapshot.assets:
                    for name, asset in sorted(snapshot.assets.items()):
                        training_vol = vol_baselines.get(name)
                        pos = asset.get("metrics", {}).get("position", {})
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
                data = json.dumps(regimes, indent=2, default=str)
                _cache_set("/volatility.json", data)
                self._send_json(data)
            elif path == "/logs":
                try:
                    with open(LOG_PATH) as f:
                        lines = f.readlines()
                    boundary = None
                    for i in range(len(lines) - 1, -1, -1):
                        if "Server stopped." in lines[i]:
                            boundary = i + 1
                            break
                    tail = "".join(lines[boundary:][-200:]) if boundary is not None else "".join(lines[-200:])
                    self._send_text(tail)
                except FileNotFoundError:
                    self._send_text("[no log file yet]")
            elif path == "/risk.json":
                data = json.dumps(_get_risk_latest(), indent=2, default=str)
                _cache_set("/risk.json", data)
                self._send_json(data)
            elif path.startswith("/risk/") and path.endswith(".json"):
                asset = path[len("/risk/") : -len(".json")]
                signal = _get_risk_latest(asset)
                if signal is not None:
                    self._send_json(json.dumps(signal, indent=2, default=str))
                else:
                    self._send_json(json.dumps({"error": f"No risk signal for {asset}", "asset": asset}), status=404)
            elif path == "/shadow-actions":
                snapshot = _STORE.load_snapshot()
                actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
                data = json.dumps(actions or {}, indent=2, default=str)
                _cache_set("/shadow-actions", data)
                self._send_json(data)
            elif path.startswith("/shadow-actions/") and path.endswith(".json"):
                asset = path[len("/shadow-actions/") : -len(".json")]
                snapshot = _STORE.load_snapshot()
                actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
                action = (actions or {}).get(asset)
                if action is not None:
                    self._send_json(json.dumps(action, indent=2, default=str))
                else:
                    self._send_json(json.dumps({"error": f"No shadow action for {asset}", "asset": asset}), status=404)
            elif path == "/health.json":
                data = json.dumps(_compute_health_all(), indent=2, default=str)
                _cache_set("/health.json", data)
                self._send_json(data)
            elif path.startswith("/health/") and path.endswith(".json"):
                asset = path[len("/health/") : -len(".json")]
                signal = _get_health_latest(asset)
                if signal is not None:
                    self._send_json(json.dumps(signal, indent=2, default=str))
                else:
                    self._send_json(json.dumps({"error": f"No health score for {asset}", "asset": asset}), status=404)
            elif path == "/ping":
                self._send_json(json.dumps({"status": "ok"}, indent=2))
            else:
                self.send_response(404)
                self.end_headers()

    class ReuseServer(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = ReuseServer(("127.0.0.1", port), Handler)
    httpd.timeout = 0.5

    print(f"Dashboard: http://127.0.0.1:{port}")
    try:
        while not (shutdown_event and shutdown_event.is_set()):
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT)
