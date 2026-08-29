import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { cn } from "../../lib/utils";
import { LayoutDashboard, Briefcase, Shield, Activity, FileText, Layers, AlertTriangle, Settings, Search, X, DollarSign, GitBranch, Hash } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getPositions, getEvents } from "../../lib/api";

interface SearchResult {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
  group: string;
  type: "nav" | "symbol" | "event" | "correlation";
  subtitle?: string;
  correlationId?: string;
  symbol?: string;
}

const navigationCommands: SearchResult[] = [
  { path: "/", label: "Overview", icon: LayoutDashboard, group: "Operations", type: "nav" },
  { path: "/positions", label: "Positions", icon: Briefcase, group: "Operations", type: "nav" },
  { path: "/risk", label: "Risk", icon: Shield, group: "Operations", type: "nav" },
  { path: "/reconciliation", label: "Reconciliation", icon: Activity, group: "Operations", type: "nav" },
  { path: "/evidence", label: "Evidence", icon: FileText, group: "Evidence", type: "nav" },
  { path: "/events", label: "Events", icon: Layers, group: "Evidence", type: "nav" },
  { path: "/alerts", label: "Alerts", icon: AlertTriangle, group: "System", type: "nav" },
  { path: "/system", label: "System", icon: Settings, group: "System", type: "nav" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const { data: positions } = useQuery({ queryKey: ["positions_cmd"], queryFn: getPositions, staleTime: 30000 });
  const { data: events } = useQuery({ queryKey: ["events_cmd"], queryFn: () => getEvents(1, 100), staleTime: 30000 });

  const filteredNav = navigationCommands.filter(
    (c) => c.label.toLowerCase().includes(query.toLowerCase()) || c.group.toLowerCase().includes(query.toLowerCase())
  );

  const symbolResults: SearchResult[] = query
    ? (positions || [])
        .filter((p) => p.symbol.toLowerCase().includes(query.toLowerCase()))
        .map((p) => ({
          type: "symbol" as const,
          symbol: p.symbol,
          path: "/positions",
          label: p.symbol,
          group: "Positions",
          icon: DollarSign,
          subtitle: `${p.direction === "BUY" ? "LONG" : "SHORT"} · ${p.unrealized_pnl >= 0 ? "+" : ""}${p.unrealized_pnl.toFixed(2)}`,
        }))
    : [];

  const eventResults: SearchResult[] = query
    ? (events?.events || [])
        .filter((e) => e.event_type.toLowerCase().includes(query.toLowerCase()) || e.message.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 5)
        .map((e) => ({
          type: "event" as const,
          path: "/events",
          label: e.event_type,
          group: "Events",
          icon: GitBranch,
          subtitle: `${e.message.slice(0, 40)}${e.message.length > 40 ? "…" : ""}`,
          correlationId: e.correlation_id || undefined,
        }))
    : [];

  const correlationResults: SearchResult[] = query
    ? (events?.events || [])
        .filter((e) => e.correlation_id && e.correlation_id.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 3)
        .map((e) => ({
          type: "correlation" as const,
          path: "/events",
          label: e.correlation_id!.slice(0, 12) + "…",
          group: "Correlation",
          icon: Hash,
          subtitle: `From ${e.event_type}`,
          correlationId: e.correlation_id || undefined,
        }))
    : [];

  const allResults = [...filteredNav, ...symbolResults, ...eventResults, ...correlationResults];

  const handleQueryChange = (value: string) => {
    setQuery(value);
    setSelectedIdx(0);
  };

  const handleOpen = useCallback(() => {
    setOpen(true);
    setQuery("");
    setSelectedIdx(0);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        handleOpen();
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleOpen]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const select = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, allResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && allResults[selectedIdx]) {
      select(allResults[selectedIdx].path);
    }
  };

  if (!open) {
    return (
      <button
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-muted bg-surface-overlay border border-border-primary rounded-lg hover:bg-surface-hover hover:text-text-secondary transition-colors"
        title="Command palette (⌘K)"
      >
        <Search className="w-3 h-3" />
        <span className="hidden sm:inline">Search</span>
        <kbd className="hidden sm:inline text-[10px] font-mono bg-surface-base border border-border-primary px-1 py-0.5 rounded">⌘K</kbd>
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-md mx-4 bg-surface-raised border border-border-primary rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle">
          <Search className="w-4 h-4 text-text-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Navigate, search symbols, events, correlation IDs..."
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
          />
          <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-secondary">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="max-h-64 overflow-y-auto py-1">
          {allResults.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-text-muted">No results for "{query}"</div>
          )}
          {allResults.map((cmd, idx) => {
            const isActive = location.pathname === cmd.path && !query;
            const Icon = cmd.icon;
            return (
              <button
                key={`${cmd.type || "nav"}-${cmd.label}-${idx}`}
                onClick={() => select(cmd.path)}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                  idx === selectedIdx && "bg-surface-hover",
                  isActive && "bg-surface-overlay"
                )}
              >
                <Icon className={cn("w-4 h-4 shrink-0", isActive ? "text-success" : "text-text-muted")} />
                <div className="flex-1 min-w-0">
                  <span className={cn("text-sm", isActive ? "text-success font-medium" : "text-text-primary")}>
                    {cmd.label}
                  </span>
                  {cmd.subtitle && (
                    <span className="text-[10px] text-text-muted ml-2 truncate block">{cmd.subtitle}</span>
                  )}
                  <span className="text-[10px] text-text-muted ml-2">{cmd.group}</span>
                </div>
                {isActive && <span className="text-[10px] text-success font-medium">current</span>}
                {cmd.correlationId && (
                  <kbd className="text-[9px] font-mono bg-surface-base border border-border-primary px-1 py-0.5 rounded ml-2 opacity-70">
                    {cmd.correlationId.slice(0, 8)}
                  </kbd>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}