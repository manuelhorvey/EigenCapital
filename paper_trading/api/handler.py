import errno
import gzip
import json
import logging
import os

from paper_trading.api.common import (
    MIME_TYPES,
    _with_state_meta,
    auth_headers,
    cache_get,
    get_index_html,
    get_rate_limiter,
    json_dumps,
    require_auth,
    try_serve_file,
)
from paper_trading.api.routes import GET_ROUTES, GET_ROUTES_PREFIX, POST_ROUTES

logger = logging.getLogger("eigencapital.auth")


class Handler:
    @staticmethod
    def _safe_write(wfile, data: bytes) -> None:
        """Write data to wfile, silently ignoring client disconnection errors."""
        try:
            wfile.write(data)
        except OSError as e:
            if e.errno in (errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED):
                pass  # client disconnected — nothing to do
            else:
                raise

    def _send_json(self, data: str, status: int = 200) -> None:
        payload = json.loads(data)
        if isinstance(payload, dict):
            seq = payload.get("sequence_id")
            ts = payload.get("timestamp", "")
            if seq is not None and ts:
                wrapped = {"data": payload, "state_timestamp": ts, "sequence_id": seq}
                data = json_dumps(wrapped)
            else:
                data = json_dumps(_with_state_meta(payload))
        else:
            data = json_dumps(_with_state_meta(payload))
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
        for k, v in auth_headers().items():
            self.send_header(k, v)
        self.end_headers()
        if getattr(self, "_send_body", True):
            self._safe_write(self.wfile, body)

    def _send_text(self, data: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        for k, v in auth_headers().items():
            self.send_header(k, v)
        self.end_headers()
        if getattr(self, "_send_body", True):
            self._safe_write(self.wfile, data.encode("utf-8"))

    def _send_unauthorized(self) -> None:
        body = json_dumps({"error": "unauthorized", "message": "Valid Bearer token required"})
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        for k, v in auth_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self._safe_write(self.wfile, body.encode("utf-8"))

    @staticmethod
    def _is_static_path(path: str) -> bool:
        """Return True if *path* is a static file exempt from rate limiting."""
        return path in ("/", "/index.html") or path.startswith("/assets/") or path.startswith("/favicon.ico")

    def _check_rate_limit(self) -> bool:
        """Enforce per-IP rate limiting for non-static requests.

        Returns True if the request is allowed.  Sends 429 and returns False
        if the client has exceeded the rate limit.
        """
        if self._is_static_path(self.path.split("?", 1)[0]):
            return True
        client_ip = self.client_address[0]
        limiter = get_rate_limiter()
        if not limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for %s on %s", client_ip, self.path)
            body = json_dumps({"error": "rate_limit", "message": "Too many requests"})
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "60")
            for k, v in auth_headers().items():
                self.send_header(k, v)
            self.end_headers()
            self._safe_write(self.wfile, body.encode("utf-8"))
            return False
        return True

    def _requires_auth(self) -> bool:
        """Check auth for the current request. Returns True if authorized."""
        # Static files are always accessible
        if self._is_static_path(self.path.split("?", 1)[0]):
            return True
        if not require_auth(dict(self.headers)):
            logger.warning("Unauthorized request to %s from %s", self.path, self.client_address[0])
            self._send_unauthorized()
            return False
        return True

    @staticmethod
    def _parse_query(query_string: str) -> dict[str, str]:
        params = {}
        if query_string:
            for part in query_string.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
        return params

    def do_HEAD(self):  # noqa: N802
        self._send_body = False
        self.do_GET()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        for k, v in auth_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if not self._check_rate_limit():
            return
        if not self._requires_auth():
            return

        qs = self.path.split("?", 1)
        path = qs[0]
        query = self._parse_query(qs[1] if len(qs) > 1 else "")

        if path in ("/", "/index.html"):
            idx_path = get_index_html()
            try:
                with open(idx_path, "rb") as f:
                    data = f.read()
                # Auth token is embedded in a <meta name="api-token"> tag in the HTML
                # (security via short-lived page rendering — token never exposed as API endpoint).
                ext = os.path.splitext(idx_path)[1]
                ct = MIME_TYPES.get(ext, "text/html; charset=utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self._safe_write(self.wfile, data)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
            return

        if path.startswith("/assets/") or path.startswith("/favicon.ico"):
            if try_serve_file(path, self):
                return
            self.send_response(404)
            self.end_headers()
            return

        if path in GET_ROUTES:
            cached = None
            fn, is_text = GET_ROUTES[path]
            if not is_text:
                cached = cache_get(self.path)
            if cached is not None:
                self._send_json(cached)
                return
            result = fn(path, query)
            if is_text:
                self._send_text(result)
            else:
                self._send_json(result)
            return

        for prefix, fn, is_text in GET_ROUTES_PREFIX:
            if path.startswith(prefix) and path.endswith(".json"):
                result = fn(path, query)
                if isinstance(result, tuple):
                    data, status = result
                    self._send_json(data, status)
                elif is_text:
                    self._send_text(result)
                else:
                    self._send_json(result)
                return

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
            self._safe_write(self.wfile, data)
            return
        except FileNotFoundError:
            pass

        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # noqa: N802
        if not self._check_rate_limit():
            return
        if not self._requires_auth():
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > 4 * 1024 * 1024:  # 4 MiB max payload
            self._send_json({"error": "payload too large"}, 413)
            return
        body = self.rfile.read(length) if length > 0 else b""
        path = self.path.split("?")[0]
        fn = POST_ROUTES.get(path)
        if fn is not None:
            data, status = fn(body)
            self._send_json(data, status)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            for k, v in auth_headers().items():
                self.send_header(k, v)
            self.end_headers()
            self._safe_write(self.wfile, json.dumps({"error": "not found"}).encode())
