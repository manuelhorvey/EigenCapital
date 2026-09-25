import { cn } from "../../lib/utils";
import { Wifi, WifiOff, Clock } from "lucide-react";
import { getFreshnessInfo } from "../../lib/dataState";

type FreshnessLevel = "live" | "stale" | "disconnected";

interface FreshnessIndicatorProps {
  /** Server-reported freshness — the single authority for the verdict. */
  level: FreshnessLevel;
  /** Observation time — contributes an age suffix only, never a verdict. */
  timestamp?: string;
  className?: string;
  compact?: boolean;
  showLabel?: boolean;
}

export default function FreshnessIndicator({ level, timestamp, className, compact = false, showLabel = true }: FreshnessIndicatorProps) {
  const isLive = level === "live";
  const isDisconnected = level === "disconnected";
  const verdict = isLive ? "Live" : isDisconnected ? "Disconnected" : "Stale";
  const verdictClass = isLive ? "text-success" : isDisconnected ? "text-text-muted" : "text-warning";
  const age = timestamp ? getFreshnessInfo(timestamp) : null;
  const ageLabel = age && age.label !== "LIVE" ? (age.label === "Unknown" ? null : age.label) : timestamp ? "now" : null;

  return (
    <div className={cn("inline-flex items-center gap-1.5", className)} title={timestamp}>
      {isLive && <Wifi className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {isDisconnected && <WifiOff className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {!isLive && !isDisconnected && <Clock className={cn("shrink-0", compact ? "w-2.5 h-2.5" : "w-3 h-3")} />}
      {showLabel && (
        <span className={cn("font-medium", compact ? "text-[10px]" : "text-[11px]", verdictClass)}>
          {verdict}
          {ageLabel && <span className="text-text-muted font-normal"> · {ageLabel}</span>}
        </span>
      )}
    </div>
  );
}
