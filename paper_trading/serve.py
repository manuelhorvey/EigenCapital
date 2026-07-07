import http.server
import logging
import os
import socketserver
import time
from socketserver import ThreadingMixIn

from paper_trading.api.handler import Handler
from paper_trading.metrics.exposition import global_registry

logger = logging.getLogger("eigencapital.serve")

DEFAULT_PORT = 5000
DEFAULT_BIND = os.environ.get("EIGENCAPITAL_BIND", "127.0.0.1")

# ── Prometheus metrics ────────────────────────────────────────────────────
_metrics = global_registry()
_http_requests_total = _metrics.counter("http_requests_total", "Total HTTP requests by method and path")
_http_request_duration_seconds = _metrics.histogram(
    "http_request_duration_seconds",
    "HTTP request latency by method and path",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
_http_errors_total = _metrics.counter("http_errors_total", "Total HTTP error responses by status code")
_uptime_gauge = _metrics.gauge("uptime_seconds", "Seconds since the HTTP server started")
_server_start = time.monotonic()


class ReuseServer(ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ServingHandler(Handler, http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._req_start = time.monotonic()
        super().__init__(*args, **kwargs)

    def log_request(self, code: int | str = ..., size: int | str = ...) -> None:
        """Override log_request to record Prometheus metrics."""
        path = self.path.split("?", 1)[0]
        method = self.command
        _http_requests_total.inc(method=method, path=path)
        elapsed = time.monotonic() - self._req_start
        _http_request_duration_seconds.observe(elapsed, method=method, path=path)
        status_code = int(code) if code is not None else 200
        if status_code >= 400:
            _http_errors_total.inc(status_code=str(status_code), path=path)
        _uptime_gauge.set(time.monotonic() - _server_start)
        super().log_request(code, size)


def serve(port=DEFAULT_PORT, shutdown_event=None):
    bind = DEFAULT_BIND
    if bind != "127.0.0.1":
        logger.warning(
            "⚠  Dashboard binding to %s (not localhost). "
            "Ensure API auth token is configured via the EIGENCAPITAL_API_TOKEN env var or the dashboard auth config.",
            bind,
        )
        from paper_trading.api.common import _load_auth_token

        _load_auth_token()

    # Create a single StateStore instance and inject it into the server
    # so route handlers receive it via self.server._state_store instead of
    # relying on the _STORE global singleton (H-06 Phase 2).
    from paper_trading.api.common import init_store as _init_api_store
    from paper_trading.state_store import StateStore

    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _state_store = StateStore(_base_dir)
    _init_api_store(store=_state_store)  # module-level backstop uses same instance

    httpd = ReuseServer((bind, port), ServingHandler)
    httpd._state_store = _state_store
    httpd.timeout = 0.5

    url = f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}"
    logger.info("Dashboard: %s", url)
    try:
        while not (shutdown_event and shutdown_event.is_set()):
            httpd.handle_request()
    except KeyboardInterrupt:
        logger.info("Dashboard server shutting down (SIGINT)")
    httpd.server_close()
