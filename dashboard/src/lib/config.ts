export function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = import.meta.env.VITE_WS_HOST || window.location.hostname;
  const port = import.meta.env.VITE_WS_PORT || "8080";
  return `${protocol}//${host}:${port}/ws/live`;
}

export function getApiBase(): string {
  return import.meta.env.VITE_API_BASE || "/api/v1";
}