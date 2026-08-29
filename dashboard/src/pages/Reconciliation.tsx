import { useQuery } from "@tanstack/react-query";
import { getReconciliation, getPositions } from "../lib/api";
import { cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Metric from "../components/ui/Metric";
import Skeleton, { SkeletonTable } from "../components/ui/Skeleton";
import EmptyState from "../components/ui/EmptyState";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import { Activity, CheckCircle, ArrowLeftRight, AlertTriangle } from "lucide-react";

export default function Reconciliation() {
  const { data: recon, isLoading: reconLoading } = useQuery({ queryKey: ["reconciliation"], queryFn: getReconciliation, refetchInterval: 10000 });
  const { data: positions } = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 10000 });

  if (reconLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <SkeletonTable rows={5} />
      </div>
    );
  }

  const protectedCount = positions?.filter((p) => p.protected).length || 0;
  const totalCount = positions?.length || 0;
  const status = recon?.overall_status || "UNKNOWN";
  const isClean = status === "CLEAN";

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Reconciliation</h1>
          <StatusBadge variant={isClean ? "success" : status === "NO_DATA" ? "neutral" : "warning"} size="md">
            {status}
          </StatusBadge>
        </div>
        <FreshnessIndicator level={recon?.freshness === "LIVE" ? "live" : recon?.freshness === "STALE" ? "stale" : "unknown"} compact />
      </div>

      {/* Status banner */}
      <div className={cn(
        "rounded-lg border p-3 lg:p-4",
        isClean ? "bg-success-subtle border-success/15" : status === "NO_DATA" ? "bg-surface-overlay border-border-primary" : "bg-warning-subtle border-warning/15"
      )}>
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
            isClean ? "bg-success/10" : status === "NO_DATA" ? "bg-surface-overlay" : "bg-warning/10"
          )}>
            <ArrowLeftRight className={cn("w-5 h-5", isClean ? "text-success" : status === "NO_DATA" ? "text-text-muted" : "text-warning")} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-text-primary">BROKER ↔ INTERNAL STATE</h2>
            <p className="text-xs text-text-muted mt-0.5">
              {isClean
                ? "All positions reconciled — broker and internal state match"
                : status === "NO_DATA"
                ? "No reconciliation data available"
                : `${recon?.checks_critical || 0} critical, ${recon?.checks_warning || 0} warning discrepancies`}
            </p>
          </div>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-border-subtle rounded-lg overflow-hidden">
        <div className="bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3">
          <Metric label="Protected" value={`${protectedCount} / ${totalCount}`} status={protectedCount === totalCount ? "positive" : "warning"} />
        </div>
        <div className="bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3">
          <Metric label="Missing Fills" value={String(recon?.missing_fills || 0)} status={(recon?.missing_fills || 0) > 0 ? "negative" : "neutral"} />
        </div>
        <div className="bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3">
          <Metric label="Foreign" value={String(recon?.foreign_positions || 0)} status={(recon?.foreign_positions || 0) > 0 ? "negative" : "neutral"} />
        </div>
        <div className="bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3">
          <Metric label="Stale" value={String(recon?.stale_positions || 0)} status={(recon?.stale_positions || 0) > 0 ? "warning" : "neutral"} />
        </div>
      </div>

      {/* Position state table — desktop */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-text-muted" />
            <h3>Position State</h3>
          </div>
        </PanelHeader>
        <PanelContent noPadding>
          {!positions || positions.length === 0 ? (
            <EmptyState
              icon={<Activity className="w-5 h-5" />}
              title="No positions to reconcile"
              description="No open positions — nothing to compare against broker state"
            />
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden lg:block overflow-x-auto">
                <table className="ec-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Direction</th>
                      <th className="text-right">Size</th>
                      <th className="text-center">Stop Loss</th>
                      <th className="text-center">Reconciled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.ticket}>
                        <td><span className="font-mono font-medium text-text-primary">{pos.symbol}</span></td>
                        <td><StatusBadge variant={pos.direction === "BUY" ? "success" : "warning"} size="sm">{pos.direction === "BUY" ? "LONG" : "SHORT"}</StatusBadge></td>
                        <td className="text-right"><span className="font-mono text-text-primary">{pos.size}</span></td>
                        <td className="text-center"><StatusDot level={pos.stop_loss != null ? "green" : "red"} label={pos.stop_loss != null ? "SET" : "MISSING"} size="xs" /></td>
                        <td className="text-center">
                          {pos.protected ? <CheckCircle className="w-3.5 h-3.5 text-success mx-auto" /> : <span className="text-[10px] text-text-muted font-mono">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Mobile cards */}
              <div className="lg:hidden divide-y divide-border-subtle">
                {positions.map((pos) => (
                  <div key={pos.ticket} className="flex items-center justify-between px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-medium text-text-primary">{pos.symbol}</span>
                      <StatusBadge variant={pos.direction === "BUY" ? "success" : "warning"} size="sm">{pos.direction === "BUY" ? "L" : "S"}</StatusBadge>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusDot level={pos.protected ? "green" : "red"} size="xs" />
                      {pos.protected ? <CheckCircle className="w-3 h-3 text-success" /> : <AlertTriangle className="w-3 h-3 text-danger" />}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </PanelContent>
      </Panel>
    </div>
  );
}
