import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getEvents } from "../lib/api";
import { cn } from "../lib/utils";
import Panel, { PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import EmptyState from "../components/ui/EmptyState";
import Skeleton from "../components/ui/Skeleton";
import { ChevronLeft, ChevronRight, Layers, Copy, Check } from "lucide-react";

function getEventTypeLevel(type: string): "blue" | "yellow" | "green" | "purple" | "gray" {
  const upper = type.toUpperCase();
  if (upper.includes("ORDER") || upper.includes("FILL") || upper.includes("SIGNAL")) return "blue";
  if (upper.includes("RISK")) return "yellow";
  if (upper.includes("POSITION") || upper.includes("EXIT")) return "green";
  if (upper.includes("RECONCILIATION")) return "purple";
  return "gray";
}

function getEventTypeVariant(type: string): "info" | "warning" | "success" | "purple" | "neutral" {
  const upper = type.toUpperCase();
  if (upper.includes("ORDER") || upper.includes("FILL") || upper.includes("SIGNAL")) return "info";
  if (upper.includes("RISK")) return "warning";
  if (upper.includes("POSITION") || upper.includes("EXIT")) return "success";
  if (upper.includes("RECONCILIATION")) return "purple";
  return "neutral";
}

function CopyableId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 text-[10px] font-mono text-text-muted hover:text-text-secondary transition-colors"
      title="Click to copy"
    >
      {value.slice(0, 8)}
      {copied ? <Check className="w-2.5 h-2.5 text-success" /> : <Copy className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100" />}
    </button>
  );
}

export default function Events() {
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: events, isLoading } = useQuery({
    queryKey: ["events", page],
    queryFn: () => getEvents(page, 50),
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Events</h1>
          <span className="text-xs text-text-muted font-mono">{events?.total || 0} events</span>
        </div>
        <span className="text-[10px] text-text-muted">Page {page}</span>
      </div>

      {/* Timeline */}
      <Panel>
        <PanelContent noPadding>
          {!events?.events || events.events.length === 0 ? (
            <EmptyState
              icon={<Layers className="w-5 h-5" />}
              title="No events recorded"
              description="Events will appear here as the trading system operates"
            />
          ) : (
            <div>
              {events.events.map((event) => {
                const level = getEventTypeLevel(event.event_type);
                const isExpanded = expanded === event.event_id;

                return (
                  <div
                    key={event.event_id}
                    className={cn(
                      "border-b border-border-subtle last:border-b-0 hover:bg-surface-hover transition-colors",
                      isExpanded && "bg-surface-overlay"
                    )}
                  >
                    <button
                      onClick={() => setExpanded(isExpanded ? null : event.event_id)}
                      className="w-full flex items-start gap-2 lg:gap-3 px-3 lg:px-4 py-2.5 text-left group"
                    >
                      <StatusDot level={level} size="xs" className="mt-1 shrink-0" />

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 lg:gap-2 flex-wrap">
                          <StatusBadge variant={getEventTypeVariant(event.event_type)} size="sm">
                            {event.event_type}
                          </StatusBadge>
                          {event.symbol && (
                            <span className="text-[11px] font-mono font-medium text-text-primary">{event.symbol}</span>
                          )}
                        </div>
                        <p className="text-xs text-text-secondary truncate mt-0.5">{event.message}</p>
                      </div>

                      <div className="text-right shrink-0">
                        <p className="text-[10px] text-text-muted font-mono">{new Date(event.timestamp).toLocaleTimeString()}</p>
                        {event.correlation_id && (
                          <div className="hidden sm:block">
                            <CopyableId value={event.correlation_id} />
                          </div>
                        )}
                      </div>
                    </button>

                    {/* Expanded details */}
                    {isExpanded && event.details && Object.keys(event.details).length > 0 && (
                      <div className="px-3 lg:px-4 pb-3 pl-8 lg:pl-10">
                        <div className="bg-surface-overlay rounded-md p-3 border border-border-subtle">
                          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Details</p>
                          <pre className="text-[11px] font-mono text-text-secondary whitespace-pre-wrap break-all leading-relaxed">
                            {JSON.stringify(event.details, null, 2)}
                          </pre>
                        </div>
                        {event.correlation_id && (
                          <div className="sm:hidden mt-2">
                            <CopyableId value={event.correlation_id} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </PanelContent>
      </Panel>

      {/* Pagination */}
      {events && events.total > 50 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 px-3 py-2 text-xs text-text-secondary bg-surface-overlay border border-border-primary rounded-md hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors min-h-[44px]"
          >
            <ChevronLeft className="w-3 h-3" /> <span className="hidden sm:inline">Previous</span>
          </button>
          <span className="text-xs text-text-muted font-mono">Page {page}</span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={!events.has_more}
            className="flex items-center gap-1 px-3 py-2 text-xs text-text-secondary bg-surface-overlay border border-border-primary rounded-md hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors min-h-[44px]"
          >
            <span className="hidden sm:inline">Next</span> <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}
