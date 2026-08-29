import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function formatNumber(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

export function getStateColor(state: string): string {
  const upper = state.toUpperCase();
  if (upper.includes("HEALTHY") || upper.includes("NORMAL") || upper.includes("AUTHORIZED") || upper === "PASS") {
    return "text-success";
  }
  if (upper.includes("DEGRADED") || upper.includes("WARNING") || upper.includes("ELEVATED")) {
    return "text-warning";
  }
  if (upper.includes("BLOCKED") || upper.includes("CRITICAL") || upper.includes("HALT")) {
    return "text-danger";
  }
  if (upper.includes("CONTAINED")) {
    return "text-warning";
  }
  return "text-text-muted";
}

export function getStateBg(state: string): string {
  const upper = state.toUpperCase();
  if (upper.includes("HEALTHY") || upper.includes("NORMAL") || upper.includes("AUTHORIZED") || upper === "PASS") {
    return "bg-success-subtle border-success/15";
  }
  if (upper.includes("DEGRADED") || upper.includes("WARNING") || upper.includes("ELEVATED")) {
    return "bg-warning-subtle border-warning/15";
  }
  if (upper.includes("BLOCKED") || upper.includes("CRITICAL") || upper.includes("HALT")) {
    return "bg-danger-subtle border-danger/15";
  }
  if (upper.includes("CONTAINED")) {
    return "bg-warning-subtle border-warning/15";
  }
  return "bg-surface-overlay border-border-primary";
}

export function getSeverityColor(severity: string): string {
  const upper = severity.toUpperCase();
  if (upper === "CRITICAL") return "text-danger";
  if (upper === "WARNING") return "text-warning";
  return "text-info";
}

export function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

export function formatRelativeTime(iso: string): string {
  try {
    const date = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 5) return "just now";
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  } catch {
    return iso;
  }
}
