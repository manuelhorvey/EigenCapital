import http.server
import logging
import os
import socketserver
import time
from pathlib import Path
from socketserver import ThreadingMixIn

from paper_trading.api.handler import Handler
from paper_trading.metrics.exposition import global_registry

# Import the cross-platform ShutdownManager
from eigencapital.platform.signals import ShutdownManager

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

    def end_headers(self) -> None:
        # Production CSP: Vite generates hashed module scripts (no unsafe-eval).
        # unsafe-inline on script-src is required for the inline theme-restoration
        # <script> in index.html (runs before React loads).
        # style-src 'unsafe-inline' is required for Tailwind utility classes and
        # React style attributes at runtime.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' http://127.0.0.1:5000; "
            "frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), midi=(), payment=(), "
            "usb=(), screen-wake-lock=(), xr-spatial-tracking=()",
        )
        super().end_headers()

    def log_request(self, code: int | str = 0, size: int | str = 0) -> None:
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

    # ── Auth enforcement ────────────────────────────────────────────────
    from paper_trading.api.common import _load_auth_token
    from paper_trading.config_manager import get_config

    cfg = get_config()
    mode = cfg.mode if hasattr(cfg, "mode") else "production"
    auth_token = _load_auth_token()

    if bind != "127.0.0.1":
        # Non-loopback binding — auth is MANDATORY
        if not auth_token:
            logger.error(
                "⚠  CRITICAL: Dashboard binding to %s (non-localhost) WITHOUT authentication. "
                "Set EIGENCAPITAL_API_TOKEN env var to secure the API. "
                "Refusing to start.",
                bind,
            )
            raise RuntimeError(
                f"Dashboard binding to {bind} requires EIGENCAPITAL_API_TOKEN. "
                "Set the env var or use 127.0.0.1 for local-only access."
            )
        logger.warning(
            "⚠  Dashboard binding to %s (not localhost). API auth token is configured.",
            bind,
        )
    elif mode == "production" and not auth_token:
        # Localhost in production mode — warn but still start
        logger.warning(
            "⚠  Production mode WITHOUT API authentication. "
            "Set EIGENCAPITAL_API_TOKEN env var to secure the dashboard API. "
            "Dashboard bound to 127.0.0.1 only (local access)."
        )

    # Create a single StateStore instance and inject it into the server
    # so route handlers receive it via self.server._state_store instead of
    # relying on the _STORE global singleton (H-06 Phase 2).
    from paper_trading.api.common import init_server_store
    from paper_trading.state_store import StateStore

    _base_dir = str(Path(__file__).resolve().parent.parent)
    _state_store = StateStore(_base_dir)
    init_server_store(store=_state_store)  # server-context backstop

    httpd = ReuseServer((bind, port), ServingHandler)
    httpd._state_store = _state_store
    httpd.timeout = 0.5

    url = f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}"
    logger.info("Dashboard: %s", url)

    # Use cross-platform ShutdownManager for signal handling
    shutdown = ShutdownManager()
    shutdown.install_handlers()

    try:
        while not (shutdown_event and shutdown_event.is_set()) and not shutdown.is_set():
            httpd.handle_request()
    except KeyboardInterrupt:
        logger.info("Dashboard server shutting down (SIGINT)")
    httpd.server_close()
