import { formatRelativeTime } from "./utils";

export type DataAvailability = "live" | "stale" | "unavailable" | "loading" | "unknown";

export interface DataState<T> {
  value: T | null;
  availability: DataAvailability;
  timestamp?: string;
  source?: string;
  error?: string;
}

export function createDataState<T>(
  value: T | null | undefined,
  freshness?: "LIVE" | "STALE" | "UNKNOWN",
  timestamp?: string,
  source?: string,
  error?: string
): DataState<T> {
  if (error) {
    return { value: null, availability: "unavailable", timestamp, source, error };
  }
  if (value === null || value === undefined) {
    return { value: null, availability: "unavailable", timestamp, source };
  }
  switch (freshness) {
    case "LIVE":
      return { value, availability: "live", timestamp, source };
    case "STALE":
      return { value, availability: "stale", timestamp, source };
    default:
      return { value, availability: "unknown", timestamp, source };
  }
}

export function formatDataValue<T>(
  state: DataState<T>,
  formatter: (value: T) => string,
  options?: {
    unavailableLabel?: string;
    loadingLabel?: string;
    unknownLabel?: string;
  }
): { text: string; className: string; isStale: boolean } {
  const { unavailableLabel = "Unavailable", loadingLabel = "Loading…", unknownLabel = "Unknown" } = options || {};

  switch (state.availability) {
    case "live":
      return { text: formatter(state.value!), className: "text-text-primary", isStale: false };
    case "stale":
      return {
        text: `${formatter(state.value!)} (stale)`,
        className: "text-warning",
        isStale: true,
      };
    case "loading":
      return { text: loadingLabel, className: "text-text-muted animate-pulse", isStale: false };
    case "unavailable":
      return { text: unavailableLabel, className: "text-text-muted", isStale: false };
    case "unknown":
    default:
      return { text: unknownLabel, className: "text-text-muted", isStale: false };
  }
}

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

export function renderDataState<T>(
  state: DataState<T>,
  renderValue: (value: T) => React.ReactNode,
  options?: {
    unavailable?: React.ReactNode;
    loading?: React.ReactNode;
    unknown?: React.ReactNode;
    showTimestamp?: boolean;
  }
): React.ReactNode {
  const { unavailable = "Unavailable", loading = "Loading…", unknown = "Unknown", showTimestamp = false } = options || {};

  const content = (() => {
    switch (state.availability) {
      case "live":
        return renderValue(state.value!);
      case "stale":
        return (
          <>
            {renderValue(state.value!)}
            <span className="text-warning text-[10px] ml-1">(stale)</span>
          </>
        );
      case "loading":
        return loading;
      case "unavailable":
        return unavailable;
      case "unknown":
      default:
        return unknown;
    }
  })();

  if (!showTimestamp || !state.timestamp) {
    return content;
  }

  const freshness = getFreshnessInfo(state.timestamp);
  return (
    <span className="inline-flex items-center gap-1">
      {content}
      <span className={freshness.className} title={state.timestamp}>{freshness.label}</span>
    </span>
  );
}

export const DataStateLabels = {
  live: "LIVE",
  stale: "STALE",
  unavailable: "Unavailable",
  loading: "Loading…",
  unknown: "Unknown",
} as const;

export function getDataStateLabel(availability: DataAvailability): string {
  return DataStateLabels[availability];
}