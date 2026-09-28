// RFC 6455 subprotocol token characters (letter/digit and "!#$%&'*+-.^_`|~").
const SUBPROTOCOL_TOKEN = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;

// Must match the backend's DASHBOARD_API_KEY (S7). Set VITE_API_KEY at build
// time — see .env.example. In dev only, fall back to the backend's local-dev
// default so `vite dev` works out of the box; production builds never embed
// this fallback (unknown key → server rejects the handshake with 1008 → the
// UI shows a disconnected state rather than silently shipping a shared key).
export function getWsKey(): string | undefined {
  return (
    import.meta.env.VITE_API_KEY ||
    (import.meta.env.DEV ? "dev-key-change-in-production" : undefined)
  );
}

export function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = import.meta.env.VITE_WS_HOST || window.location.hostname;
  const port = import.meta.env.VITE_WS_PORT || "8080";
  // The API key is NEVER placed in the URL (H-11). Browsers cannot set custom
  // headers on the WS handshake, so the key travels via subprotocol
  // negotiation (see getWsProtocols) instead of `?token=`.
  return `${protocol}//${host}:${port}/ws/live`;
}

// Subprotocols offered on the WS handshake: `api-key.<key>`. The server
// validates the key, echoes the selected protocol (RFC 6455 requires the
// server to pick one of the offered tokens), and closes unauthorized
// handshakes with code 1008. Returns undefined when no key is configured so
// the handshake is sent without credentials (server rejects it).
export function getWsProtocols(): string[] | undefined {
  const key = getWsKey();
  if (!key) {
    return undefined;
  }
  if (!SUBPROTOCOL_TOKEN.test(key)) {
    throw new Error(
      "VITE_API_KEY contains characters that are not valid in a WebSocket " +
        "subprotocol token (allowed: letters, digits and !#$%&'*+-.^_`|~)"
    );
  }
  return [`api-key.${key}`];
}

export function getApiBase(): string {
  return import.meta.env.VITE_API_BASE || "/api/v1";
}
