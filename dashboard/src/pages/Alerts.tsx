import { useQuery } from "@tanstack/react-query";
import { getAlerts } from "../lib/api";
import { cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import EmptyState from "../components/ui/EmptyState";
import Skeleton from "../components/ui/Skeleton";
import { AlertTriangle, AlertOctagon, Info } from "lucide-react";

export default function Alerts() {
  const { data: alerts, isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => getAlerts(100),
    refetchInterval: 15000,
  });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
      </div>
    );
  }

  const critical = alerts?.filter((a) => a.severity === "CRITICAL") || [];
  const warnings = alerts?.filter((a) => a.severity === "WARNING") || [];
  const infos = alerts?.filter((a) => a.severity !== "CRITICAL" && a.severity !== "WARNING") || [];

  const renderAlertList = (items: NonNullable<typeof alerts>, variant: "danger" | "warning" | "info" | "neutral") => (
    <div className="divide-y divide-border-subtle">
      {items.map((alert) => (
        <div
          key={alert.alert_id}
          className={cn(
            "flex items-start gap-2 lg:gap-3 px-3 lg:px-4 py-2.5 hover:bg-surface-hover transition-colors",
            variant === "danger" && "bg-danger-subtle/20"
          )}
        >
          <StatusDot
            level={variant === "danger" ? "red" : variant === "warning" ? "yellow" : "blue"}
            size="xs"
            pulse={variant === "danger"}
            className="mt-1 shrink-0"
          />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-text-primary truncate">{alert.message}</p>
            <div className="flex items-center gap-2 mt-0.5">
              {alert.category && (
                <span className="ec-badge bg-surface-overlay text-text-muted border border-border-primary text-[9px]">
                  {alert.category}
                </span>
              )}
              {alert.correlation_id && (
                <span className="text-[9px] font-mono text-text-muted">{alert.correlation_id.slice(0, 8)}</span>
              )}
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className="text-[10px] text-text-muted font-mono">{new Date(alert.timestamp).toLocaleTimeString()}</p>
            {alert.consecutive_count > 1 && (
              <p className="text-[9px] text-text-muted">×{alert.consecutive_count}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Alerts</h1>
          <div className="flex items-center gap-2">
            {critical.length > 0 && <StatusBadge variant="danger" size="sm" pulse>{critical.length} critical</StatusBadge>}
            {warnings.length > 0 && <StatusBadge variant="warning" size="sm">{warnings.length} warning</StatusBadge>}
          </div>
        </div>
        <span className="text-xs text-text-muted font-mono">{alerts?.length || 0} total</span>
      </div>

      {critical.length > 0 && (
        <Panel accent="danger">
          <PanelHeader>
            <div className="flex items-center gap-2">
              <AlertOctagon className="w-3.5 h-3.5 text-danger" />
              <h3 className="!text-danger">Critical</h3>
            </div>
            <StatusBadge variant="danger" size="sm" pulse>{critical.length}</StatusBadge>
          </PanelHeader>
          <PanelContent noPadding>{renderAlertList(critical, "danger")}</PanelContent>
        </Panel>
      )}

      {warnings.length > 0 && (
        <Panel accent="warning">
          <PanelHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-warning" />
              <h3 className="!text-warning">Warnings</h3>
            </div>
            <StatusBadge variant="warning" size="sm">{warnings.length}</StatusBadge>
          </PanelHeader>
          <PanelContent noPadding>{renderAlertList(warnings, "warning")}</PanelContent>
        </Panel>
      )}

      {infos.length > 0 && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Info className="w-3.5 h-3.5 text-text-muted" />
              <h3>Informational</h3>
            </div>
            <span className="text-[10px] text-text-muted">{infos.length}</span>
          </PanelHeader>
          <PanelContent noPadding>{renderAlertList(infos, "info")}</PanelContent>
        </Panel>
      )}

      {(!alerts || alerts.length === 0) && (
        <EmptyState
          icon={<AlertTriangle className="w-5 h-5" />}
          title="No alerts"
          description="All systems operating normally — no alerts have been raised"
        />
      )}
    </div>
  );
}
