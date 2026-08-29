import { cn } from "../../lib/utils";
import { Wifi, WifiOff, Clock } from "lucide-react";

type FreshnessLevel = "live" | "recent" | "stale" | "unknown" | "disconnected";

interface FreshnessIndicatorProps {
  level: FreshnessLevel;
  timestamp?: string;
  className?: string;
  compact?: boolean;
}

const levelConfig: Record<FreshnessLevel, { color: string; icon: typeof Clock; label: string }> = {
  live: { color: "text-success", icon: Wifi, label: "LIVE" },
  recent: { color: "text-info", icon: Clock, label: "RECENT" },
  stale: { color: "text-warning", icon: Clock, label: "STALE" },
  unknown: { color: "text-text-muted", icon: Clock, label: "UNKNOWN" },
  disconnected: { color: "text-danger", icon: WifiOff, label: "DISCONNECTED" },
};

function getRelativeTime(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  } catch {
    return "";
  }
}

export default function FreshnessIndicator({ level, timestamp, className, compact = false }: FreshnessIndicatorProps) {
  const config = levelConfig[level];
  const Icon = config.icon;

  return (
    <div className={cn("inline-flex items-center gap-1.5", config.color, className)}>
      <Icon className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />
      <span className={cn("font-medium", compact ? "text-[10px]" : "text-[11px]")}>{config.label}</span>
      {timestamp && level === "live" && !compact && (
        <span className="text-text-muted text-[10px]">{getRelativeTime(timestamp)}</span>
      )}
      {timestamp && level === "stale" && !compact && (
        <span className="text-text-muted text-[10px]">last {getRelativeTime(timestamp)}</span>
      )}
    </div>
  );
}
