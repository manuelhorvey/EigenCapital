import { cn } from "../../lib/utils";
import { Wifi, WifiOff, Clock } from "lucide-react";
import { getFreshnessInfo } from "../../lib/dataState";

type FreshnessLevel = "live" | "stale" | "disconnected";

interface FreshnessIndicatorProps {
  level: FreshnessLevel;
  timestamp?: string;
  className?: string;
  compact?: boolean;
  showLabel?: boolean;
}

export default function FreshnessIndicator({ level, timestamp, className, compact = false, showLabel = true }: FreshnessIndicatorProps) {
  const info = timestamp ? getFreshnessInfo(timestamp) : { label: "Unknown", className: "text-text-muted", isStale: false };
  const isLive = level === "live";
  const isDisconnected = level === "disconnected";

  return (
    <div className={cn("inline-flex items-center gap-1.5", info.className, className)}>
      {isLive && <Wifi className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {isDisconnected && <WifiOff className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {!isLive && !isDisconnected && <Clock className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {showLabel && <span className={cn("font-medium", compact ? "text-[10px]" : "text-[11px]")}>{info.label}</span>}
      {timestamp && !compact && !isLive && <span className="text-text-muted text-[10px]">{info.label}</span>}
    </div>
  );
}