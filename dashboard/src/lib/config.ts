export function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = import.meta.env.VITE_WS_HOST || window.location.hostname;
  const port = import.meta.env.VITE_WS_PORT || "8080";
  // Browsers cannot set custom headers on the WS handshake — the API key is
  // passed as the `token` query parameter (validated server-side). Dev-only
  // fallback (see api.ts); production builds must set VITE_API_KEY or the
  // server rejects the handshake and the UI shows a disconnected state.
  const token =
    import.meta.env.VITE_API_KEY || (import.meta.env.DEV ? "dev-key-change-in-production" : undefined);
  const base = `${protocol}//${host}:${port}/ws/live`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function getApiBase(): string {
  return import.meta.env.VITE_API_BASE || "/api/v1";
}