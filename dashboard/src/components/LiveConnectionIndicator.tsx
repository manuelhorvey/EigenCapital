import { useLiveStream } from "../hooks/useLiveStream";
import { Wifi, WifiOff, RotateCcw } from "lucide-react";
import { cn } from "../lib/utils";

export default function LiveConnectionIndicator({ compact = true, showLabel = true, className }: { compact?: boolean; showLabel?: boolean; className?: string }) {
  const { connected, error, lastUpdate } = useLiveStream();
  const showReconnecting = !connected && !!error;

  if (compact) {
    return (
      <div className={cn("inline-flex items-center gap-1.5", connected ? "text-success" : "text-danger", className)}>
        {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
        {showLabel && <span className="text-[10px] font-medium">{connected ? "LIVE" : "DISCONNECTED"}</span>}
        {showReconnecting && <RotateCcw className="w-3 h-3 animate-spin" />}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-overlay border border-border-primary">
      <div className={cn("flex items-center gap-2", connected ? "text-success" : "text-danger")}>
        {connected ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
        <div className="flex flex-col">
          <span className="text-xs font-medium">{connected ? "Live Connection" : "Disconnected"}</span>
          <span className="text-[10px] text-text-muted">
            {connected ? `Last update: ${lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : "—"}` : error || "Attempting to reconnect…"}
          </span>
        </div>
      </div>
      {!connected && (
        <button
          className="ml-auto px-2 py-1 text-[10px] font-medium text-text-secondary bg-surface-raised border border-border-primary rounded hover:bg-surface-hover transition-colors"
          onClick={() => window.location.reload()}
        >
          <RotateCcw className="w-3 h-3 inline mr-1" />
          Reconnect
        </button>
      )}
    </div>
  );
}