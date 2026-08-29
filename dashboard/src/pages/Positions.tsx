import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPositions, getAccount } from "../lib/api";
import { formatCurrency, formatNumber, cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Metric from "../components/ui/Metric";
import Skeleton from "../components/ui/Skeleton";
import EmptyState from "../components/ui/EmptyState";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import { Search, Briefcase, ArrowUpDown, X, Clock, MapPin, ShieldCheck } from "lucide-react";

type SortKey = "symbol" | "size" | "entry_price" | "current_price" | "unrealized_pnl" | "holding_time";

export default function Positions() {
  const [filter, setFilter] = useState<"all" | "long" | "short" | "unprotected">("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selectedTicket, setSelectedTicket] = useState<number | null>(null);

  const { data: positions, isLoading } = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 5000 });
  const { data: account } = useQuery({ queryKey: ["account"], queryFn: getAccount, refetchInterval: 5000 });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }

  const filtered = (positions || [])
    .filter((p) => {
      if (filter === "long" && p.direction !== "BUY") return false;
      if (filter === "short" && p.direction !== "SELL") return false;
      if (filter === "unprotected" && p.protected) return false;
      if (search && !p.symbol.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "symbol": cmp = a.symbol.localeCompare(b.symbol); break;
        case "size": cmp = Math.abs(a.size) - Math.abs(b.size); break;
        case "entry_price": cmp = a.entry_price - b.entry_price; break;
        case "current_price": cmp = a.current_price - b.current_price; break;
        case "unrealized_pnl": cmp = a.unrealized_pnl - b.unrealized_pnl; break;
        case "holding_time": cmp = (a.holding_time || "").localeCompare(b.holding_time || ""); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });

  const protectedCount = positions?.filter((p) => p.protected).length || 0;
  const totalCount = positions?.length || 0;
  const selectedPos = positions?.find((p) => p.ticket === selectedTicket);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) => (
    <ArrowUpDown className={cn("w-2.5 h-2.5 ml-1 shrink-0", sortKey === col ? "text-success" : "text-text-muted/50")} />
  );

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 lg:gap-4">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Positions</h1>
          <div className="hidden sm:flex items-center gap-3">
            <Metric label="Open" value={totalCount} status="neutral" />
            <Metric label="Equity" value={formatCurrency(account?.equity || 0)} status="neutral" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusDot level={protectedCount === totalCount ? "green" : "yellow"} size="xs" />
          <span className="text-xs text-text-secondary">{protectedCount}/{totalCount} Protected</span>
        </div>
      </div>

      {/* Mobile metrics row */}
      <div className="sm:hidden flex items-center gap-3">
        <Metric label="Equity" value={formatCurrency(account?.equity || 0)} status="neutral" />
        <FreshnessIndicator level={account?.freshness === "LIVE" ? "live" : "stale"} timestamp={account?.timestamp} compact />
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 lg:gap-3">
        <div className="relative flex-1 max-w-[240px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
          <input
            type="text"
            placeholder="Filter symbols..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 lg:py-2 text-xs bg-surface-overlay border border-border-primary rounded-md text-text-primary placeholder:text-text-muted focus:outline-none focus:border-success/50 transition-colors"
          />
        </div>
        <div className="flex gap-px bg-border-subtle rounded-md overflow-hidden">
          {(["all", "long", "short", "unprotected"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-2 lg:px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors",
                filter === f ? "bg-surface-overlay text-text-primary" : "bg-surface-raised text-text-muted hover:text-text-secondary"
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* ═══ Desktop Table ═══ */}
      <div className="hidden lg:block ec-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="ec-table">
            <thead>
              <tr>
                {[
                  { key: "symbol" as SortKey, label: "Symbol", align: "left" },
                  { key: "direction" as SortKey, label: "Side", align: "left" },
                  { key: "size" as SortKey, label: "Size", align: "right" },
                  { key: "entry_price" as SortKey, label: "Entry", align: "right" },
                  { key: "current_price" as SortKey, label: "Mark", align: "right" },
                  { key: "unrealized_pnl" as SortKey, label: "P&L", align: "right" },
                  { key: "unrealized_pnl" as SortKey, label: "P&L %", align: "right" },
                  { key: "holding_time" as SortKey, label: "SL", align: "center" },
                  { key: "holding_time" as SortKey, label: "Risk", align: "center" },
                ].map((col, i) => (
                  <th
                    key={`${col.key}-${i}`}
                    className={cn(
                      col.align === "right" && "text-right",
                      col.align === "center" && "text-center",
                      ["symbol", "size", "entry_price", "current_price", "unrealized_pnl"].includes(col.key) && "cursor-pointer select-none"
                    )}
                    onClick={() => {
                      if (["symbol", "size", "entry_price", "current_price", "unrealized_pnl"].includes(col.key)) {
                        toggleSort(col.key);
                      }
                    }}
                  >
                    <span className="inline-flex items-center">
                      {col.label}
                      {["symbol", "size", "entry_price", "current_price", "unrealized_pnl"].includes(col.key) && (
                        <SortIcon col={col.key} />
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((pos) => (
                <tr
                  key={pos.ticket}
                  className={cn(
                    "group cursor-pointer",
                    selectedTicket === pos.ticket && "bg-success/5"
                  )}
                  onClick={() => setSelectedTicket(selectedTicket === pos.ticket ? null : pos.ticket)}
                >
                  <td>
                    <span className="font-mono font-medium text-text-primary">{pos.symbol}</span>
                  </td>
                  <td>
                    <StatusBadge variant={pos.direction === "BUY" ? "success" : "warning"} size="sm">
                      {pos.direction === "BUY" ? "LONG" : "SHORT"}
                    </StatusBadge>
                  </td>
                  <td className="text-right">
                    <span className="font-mono text-text-primary">{formatNumber(Math.abs(pos.size), 2)}</span>
                  </td>
                  <td className="text-right">
                    <span className="font-mono text-text-secondary">{formatNumber(pos.entry_price, 5)}</span>
                  </td>
                  <td className="text-right">
                    <span className="font-mono text-text-primary">{formatNumber(pos.current_price, 5)}</span>
                  </td>
                  <td className="text-right">
                    <span className={cn("font-mono font-medium", pos.unrealized_pnl >= 0 ? "text-success" : "text-danger")}>
                      {pos.unrealized_pnl >= 0 ? "+" : ""}{formatCurrency(pos.unrealized_pnl)}
                    </span>
                  </td>
                  <td className="text-right">
                    <span className={cn("font-mono text-[11px]", pos.unrealized_pnl_pct >= 0 ? "text-success" : "text-danger")}>
                      {pos.unrealized_pnl_pct >= 0 ? "+" : ""}{(pos.unrealized_pnl_pct * 100).toFixed(2)}%
                    </span>
                  </td>
                  <td className="text-center">
                    <StatusDot level={pos.protected ? "green" : "red"} size="xs" />
                  </td>
                  <td className="text-center">
                    <StatusDot
                      level={pos.risk_state === "NORMAL" ? "green" : pos.risk_state === "WARNING" ? "yellow" : "red"}
                      size="xs"
                    />
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState
                      icon={<Briefcase className="w-5 h-5" />}
                      title="No positions"
                      description={search ? `No positions match "${search}"` : "No open positions in this category"}
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ═══ Desktop Detail Drawer ═══ */}
      {selectedPos && (
        <Panel className="hidden lg:block" accent={selectedPos.protected ? undefined : "danger"}>
          <PanelHeader>
            <div className="flex items-center gap-3">
              <span className="text-sm font-mono font-bold text-text-primary">{selectedPos.symbol}</span>
              <StatusBadge variant={selectedPos.direction === "BUY" ? "success" : "warning"} size="sm">
                {selectedPos.direction === "BUY" ? "LONG" : "SHORT"}
              </StatusBadge>
              <StatusDot level={selectedPos.protected ? "green" : "red"} label={selectedPos.protected ? "Protected" : "Unprotected"} size="xs" />
              <StatusDot
                level={selectedPos.risk_state === "NORMAL" ? "green" : selectedPos.risk_state === "WARNING" ? "yellow" : "red"}
                label={selectedPos.risk_state}
                size="xs"
              />
            </div>
            <button
              onClick={() => setSelectedTicket(null)}
              className="p-1 rounded hover:bg-surface-hover text-text-muted"
            >
              <X className="w-4 h-4" />
            </button>
          </PanelHeader>
          <PanelContent>
            {/* Core metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
              <Metric label="Entry" value={formatNumber(selectedPos.entry_price, 5)} status="neutral" />
              <Metric label="Mark" value={formatNumber(selectedPos.current_price, 5)} status="neutral" />
              <Metric label="Size" value={formatNumber(Math.abs(selectedPos.size), 2)} status="neutral" />
              <Metric label="P&L" value={formatCurrency(selectedPos.unrealized_pnl)} status={selectedPos.unrealized_pnl >= 0 ? "positive" : "negative"} />
              <Metric label="P&L %" value={`${selectedPos.unrealized_pnl_pct >= 0 ? "+" : ""}${(selectedPos.unrealized_pnl_pct * 100).toFixed(2)}%`} status={selectedPos.unrealized_pnl_pct >= 0 ? "positive" : "negative"} />
              <Metric label="Holding" value={selectedPos.holding_time || "No data"} status="neutral" />
            </div>

            {/* Risk & Protection row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 pb-4 border-b border-border-subtle">
              <Metric label="Stop Loss" value={selectedPos.stop_loss ? formatNumber(selectedPos.stop_loss, 5) : "NOT SET"} status={selectedPos.stop_loss ? "neutral" : "negative"} />
              <Metric label="Distance to SL" value={selectedPos.distance_to_sl ? formatNumber(selectedPos.distance_to_sl, 5) : "No data"} status="neutral" />
              <Metric label="MAE" value={selectedPos.mae != null ? formatCurrency(selectedPos.mae) : "No data"} status="neutral" />
              <Metric label="MFE" value={selectedPos.mfe != null ? formatCurrency(selectedPos.mfe) : "No data"} status="neutral" />
            </div>

            {/* Lifecycle & Provenance */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Lifecycle */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <Clock className="w-3 h-3 text-text-muted" />
                  <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Lifecycle</p>
                </div>
                <div className="space-y-1.5">
                  {[
                    { step: "SIGNAL", icon: "→", active: true },
                    { step: "ORDER", icon: "→", active: true },
                    { step: "FILL", icon: "→", active: true },
                    { step: "POSITION", icon: "→", active: true },
                    { step: "RISK", icon: "→", active: true },
                    { step: "EXIT", icon: "", active: false },
                    { step: "P&L", icon: "", active: false },
                  ].map((s) => (
                    <div key={s.step} className="flex items-center gap-2">
                      <span className={cn("w-1.5 h-1.5 rounded-full", s.active ? "bg-success" : "bg-surface-overlay")} />
                      <span className={cn("text-[10px] font-mono", s.active ? "text-text-primary" : "text-text-muted")}>{s.step}</span>
                      {s.icon && <span className="text-[8px] text-text-muted">{s.icon}</span>}
                    </div>
                  ))}
                </div>
              </div>

              {/* Provenance */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <MapPin className="w-3 h-3 text-text-muted" />
                  <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Provenance</p>
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Ticket</span>
                    <span className="text-[10px] font-mono text-text-primary">{selectedPos.ticket}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Protection</span>
                    <span className={cn("text-[10px] font-mono", selectedPos.protected ? "text-success" : "text-danger")}>{selectedPos.protected ? "SL SET" : "UNPROTECTED"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Attribution</span>
                    <span className="text-[10px] font-mono text-text-muted">{selectedPos.attribution_state || "No data"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Last Update</span>
                    <span className="text-[10px] font-mono text-text-muted">{new Date(selectedPos.last_update).toLocaleTimeString()}</span>
                  </div>
                </div>
              </div>

              {/* Risk summary */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <ShieldCheck className="w-3 h-3 text-text-muted" />
                  <p className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Risk Summary</p>
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">State</span>
                    <StatusBadge
                      variant={selectedPos.risk_state === "NORMAL" ? "success" : selectedPos.risk_state === "WARNING" ? "warning" : "danger"}
                      size="sm"
                    >
                      {selectedPos.risk_state}
                    </StatusBadge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Exposure</span>
                    <span className="text-[10px] font-mono text-text-primary">{formatCurrency(Math.abs(selectedPos.size * selectedPos.current_price))}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Direction</span>
                    <span className={cn("text-[10px] font-mono font-medium", selectedPos.direction === "BUY" ? "text-success" : "text-warning")}>{selectedPos.direction === "BUY" ? "LONG" : "SHORT"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-text-muted">Freshness</span>
                    <FreshnessIndicator level={selectedPos.freshness === "LIVE" ? "live" : "stale"} timestamp={selectedPos.last_update} compact />
                  </div>
                </div>
              </div>
            </div>
          </PanelContent>
        </Panel>
      )}

      {/* ═══ Mobile Card List ═══ */}
      <div className="lg:hidden space-y-2">
        {filtered.length === 0 ? (
          <EmptyState
            icon={<Briefcase className="w-5 h-5" />}
            title="No positions"
            description={search ? `No positions match "${search}"` : "No open positions in this category"}
          />
        ) : (
          filtered.map((pos) => (
            <div
              key={pos.ticket}
              className={cn(
                "ec-panel p-3 cursor-pointer transition-colors",
                selectedTicket === pos.ticket ? "border-success/30 bg-success/5" : "hover:bg-surface-hover"
              )}
              onClick={() => setSelectedTicket(selectedTicket === pos.ticket ? null : pos.ticket)}
            >
              {/* Header row */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-mono font-bold text-text-primary">{pos.symbol}</span>
                  <StatusBadge variant={pos.direction === "BUY" ? "success" : "warning"} size="sm">
                    {pos.direction === "BUY" ? "LONG" : "SHORT"}
                  </StatusBadge>
                </div>
                <span className={cn("text-sm font-mono font-bold", pos.unrealized_pnl >= 0 ? "text-success" : "text-danger")}>
                  {pos.unrealized_pnl >= 0 ? "+" : ""}{formatCurrency(pos.unrealized_pnl)}
                </span>
              </div>
              {/* Size + P&L% row */}
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-muted">Qty {formatNumber(Math.abs(pos.size), 2)}</span>
                <span className={cn("font-mono", pos.unrealized_pnl_pct >= 0 ? "text-success" : "text-danger")}>
                  {pos.unrealized_pnl_pct >= 0 ? "+" : ""}{(pos.unrealized_pnl_pct * 100).toFixed(2)}%
                </span>
              </div>
              {/* Status row */}
              <div className="flex items-center gap-3 mt-2 pt-2 border-t border-border-subtle">
                <StatusDot level={pos.protected ? "green" : "red"} size="xs" label={pos.protected ? "Protected" : "No SL"} />
                <StatusDot
                  level={pos.risk_state === "NORMAL" ? "green" : pos.risk_state === "WARNING" ? "yellow" : "red"}
                  size="xs"
                  label={pos.risk_state}
                />
                {pos.holding_time && (
                  <span className="text-[10px] text-text-muted ml-auto">{pos.holding_time}</span>
                )}
              </div>
              {/* Expanded detail */}
              {selectedTicket === pos.ticket && (
                <div className="mt-3 pt-3 border-t border-border-subtle">
                  {/* Core metrics */}
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    <Metric label="Entry" value={formatNumber(pos.entry_price, 5)} status="neutral" />
                    <Metric label="Mark" value={formatNumber(pos.current_price, 5)} status="neutral" />
                    <Metric label="SL" value={pos.stop_loss ? formatNumber(pos.stop_loss, 5) : "NOT SET"} status={pos.stop_loss ? "neutral" : "negative"} />
                    <Metric label="Dist SL" value={pos.distance_to_sl ? formatNumber(pos.distance_to_sl, 5) : "No data"} status="neutral" />
                    <Metric label="MAE" value={pos.mae != null ? formatCurrency(pos.mae) : "No data"} status="neutral" />
                    <Metric label="MFE" value={pos.mfe != null ? formatCurrency(pos.mfe) : "No data"} status="neutral" />
                  </div>
                  {/* Lifecycle */}
                  <div className="pt-2 border-t border-border-subtle">
                    <p className="text-[9px] text-text-muted uppercase tracking-wider mb-1.5">Lifecycle</p>
                    <div className="flex items-center gap-1">
                      {["SIGNAL", "ORDER", "FILL", "POSITION", "RISK"].map((step, i) => (
                        <span key={step} className="inline-flex items-center gap-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-success" />
                          <span className="text-[8px] font-mono text-text-muted">{step}</span>
                          {i < 4 && <span className="text-[7px] text-text-muted/50">→</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
