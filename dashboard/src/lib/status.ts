/**
 * EigenCapital status semantics — single source of truth (contract §8.1).
 *
 * Every status → visual mapping in the dashboard routes through this module.
 * Do not inline status color logic in pages; add a mapping here instead.
 */

// ─── Status levels ───────────────────────────────────────────────────
export type StatusLevel = "positive" | "warning" | "danger" | "info" | "diagnostic" | "neutral";

// ─── Health dimension vocabulary (backend contract-tested) ──────────
// HEALTHY / DEGRADED / BLOCKED / CONTAINED / HALTED (+ UNKNOWN)
export type HealthDimensionState =
  | "HEALTHY"
  | "DEGRADED"
  | "BLOCKED"
  | "CONTAINED"
  | "HALTED"
  | string;

// ─── Risk level vocabulary (RiskObserver) ────────────────────────────
// NORMAL / ELEVATED / WARNING / CRITICAL / HALT (+ UNKNOWN)
export type RiskLevel = "NORMAL" | "ELEVATED" | "WARNING" | "CRITICAL" | "HALT" | string;

// ─── Dot levels (StatusDot) ──────────────────────────────────────────
export type DotLevel = "green" | "yellow" | "red" | "blue" | "purple" | "gray";

/**
 * Map an arbitrary state string (health dimension, risk level, status field)
 * to a StatusLevel. Unknown states map to "neutral" — never to positive.
 */
export function stateToLevel(state: string | null | undefined): StatusLevel {
  const upper = (state ?? "").toUpperCase();
  if (
    upper === "HEALTHY" ||
    upper === "NORMAL" ||
    upper === "AUTHORIZED" ||
    upper === "PASS" ||
    upper === "SUFFICIENT" ||
    upper === "CLEAN"
  ) {
    return "positive";
  }
  if (upper === "DEGRADED" || upper === "WARNING" || upper === "ELEVATED" || upper === "CONTAINED" || upper === "COLLECTING") {
    return "warning";
  }
  if (upper === "BLOCKED" || upper === "CRITICAL" || upper === "HALT" || upper === "HALTED" || upper === "FAIL") {
    return "danger";
  }
  if (upper === "INFO") {
    return "info";
  }
  return "neutral";
}

/** Map an arbitrary state string to a StatusDot level. */
export function stateToDotLevel(state: string | null | undefined): DotLevel {
  const level = stateToLevel(state);
  switch (level) {
    case "positive":
      return "green";
    case "warning":
      return "yellow";
    case "danger":
      return "red";
    case "info":
      return "blue";
    case "diagnostic":
      return "purple";
    default:
      return "gray";
  }
}

/** Text color class for a state string. */
export function stateTextColor(state: string | null | undefined): string {
  switch (stateToLevel(state)) {
    case "positive":
      return "text-success";
    case "warning":
      return "text-warning";
    case "danger":
      return "text-danger";
    case "info":
      return "text-info";
    case "diagnostic":
      return "text-purple";
    default:
      return "text-text-muted";
  }
}

/** Background + border classes (subtle) for a state string. */
export function stateBg(state: string | null | undefined): string {
  switch (stateToLevel(state)) {
    case "positive":
      return "bg-success-subtle border-success/15";
    case "warning":
      return "bg-warning-subtle border-warning/15";
    case "danger":
      return "bg-danger-subtle border-danger/15";
    case "info":
      return "bg-info-subtle border-info/15";
    case "diagnostic":
      return "bg-purple-subtle border-purple/15";
    default:
      return "bg-surface-overlay border-border-primary";
  }
}

/** Badge variant for a state string (StatusBadge variants). */
export type BadgeVariant = "success" | "warning" | "danger" | "info" | "purple" | "neutral";

export function stateToBadgeVariant(state: string | null | undefined): BadgeVariant {
  const level = stateToLevel(state);
  switch (level) {
    case "positive":
      return "success";
    case "warning":
      return "warning";
    case "danger":
      return "danger";
    case "info":
      return "info";
    case "diagnostic":
      return "purple";
    default:
      return "neutral";
  }
}

/** Chart color (hex) keyed by StatusLevel — the deuteranopia-safe palette used by all charts. */
export const CHART_COLORS: Record<StatusLevel, string> = {
  positive: "#009B77",
  warning: "#F08A00",
  danger: "#D33F49",
  diagnostic: "#8C6FE6",
  info: "#0072B5",
  neutral: "#52525b",
};

export function stateToChartColor(state: string | null | undefined): string {
  return CHART_COLORS[stateToLevel(state)] ?? CHART_COLORS.neutral;
}

/** Uppercase a state for display, with UNKNOWN fallback. */
export function stateLabel(state: string | null | undefined): string {
  const upper = (state ?? "").toUpperCase();
  return upper || "UNKNOWN";
}
