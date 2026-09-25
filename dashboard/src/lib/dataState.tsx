import { formatRelativeTime } from "./utils";

/**
 * Timestamp → human age label.
 *
 * This is an AGE descriptor only — it never decides LIVE/STALE verdicts.
 * Freshness verdicts come from the server (`freshness` field / `level` prop);
 * see components/ui/FreshnessIndicator (contract T5, audit: dual-source
 * freshness confusion).
 *
 * Dead helpers (createDataState/formatDataValue/renderDataState/DataState*)
 * were removed 2026-09-25 — nothing imported them.
 */
export function getFreshnessInfo(timestamp?: string): { label: string; className: string; isStale: boolean } {
  if (!timestamp) {
    return { label: "Unknown", className: "text-text-muted", isStale: false };
  }
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 10) {
    return { label: "LIVE", className: "text-success", isStale: false };
  }
  if (seconds < 60) {
    return { label: `${seconds}s ago`, className: "text-success", isStale: false };
  }
  if (seconds < 300) {
    return { label: `${Math.floor(seconds / 60)}m ago`, className: "text-warning", isStale: true };
  }
  return { label: formatRelativeTime(timestamp), className: "text-danger", isStale: true };
}
