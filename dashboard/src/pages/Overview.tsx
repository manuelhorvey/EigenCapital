import { useQuery } from "@tanstack/react-query";
import {
  getSystemHealth,
  getAccount,
  getPositions,
  getRiskState,
  getAlerts,
  getQualification,
  getBuildIdentity,
  getHealth,
} from "../lib/api";
import { formatCurrency, formatPercent, cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Metric from "../components/ui/Metric";
import HealthMatrix from "../components/ui/HealthMatrix";
import Skeleton from "../components/ui/Skeleton";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
  Clock,
} from "lucide-react";

export default function Overview() {
  const { data: health, isLoading: healthLoading } = useQuery({ queryKey: ["systemHealth"], queryFn: getSystemHealth, refetchInterval: 10000 });
  const { data: fullHealth } = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 10000 });
  const { data: build } = useQuery({ queryKey: ["buildIdentity"], queryFn: getBuildIdentity, refetchInterval: 60000 });
  const { data: account } = useQuery({ queryKey: ["account"], queryFn: getAccount, refetchInterval: 5000 });
  const { data: positions } = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 5000 });
  const { data: risk } = useQuery({ queryKey: ["riskState"], queryFn: getRiskState, refetchInterval: 10000 });
  const { data: alerts } = useQuery({ queryKey: ["alerts"], queryFn: () => getAlerts(5), refetchInterval: 15000 });
  const { data: qual } = useQuery({ queryKey: ["qualification"], queryFn: getQualification, refetchInterval: 30000 });

  const authState = health?.trading_authorization || "UNKNOWN";
  const isAuthorized = authState === "TRADING_AUTHORIZED";
  const protectedCount = positions?.filter((p) => p.protected).length || 0;
  const totalCount = positions?.length || 0;

  if (healthLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-20 rounded-lg" />
        <div className="grid grid-cols-3 gap-px bg-border-subtle rounded-lg overflow-hidden">
          {[1, 2, 3].map((i) => <div key={i} className="bg-surface-raised h-16" />)}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-px bg-border-subtle rounded-lg overflow-hidden">
          {[1, 2, 3, 4, 5, 6].map((i) => <div key={i} className="bg-surface-raised h-16" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* ═══ Trading Authorization — dominates on mobile ═══ */}
      <div className={cn(
        "rounded-lg border p-3 lg:p-4",
        isAuthorized
          ? "bg-success-subtle border-success/15"
          : authState.includes("BLOCKED")
          ? "bg-danger-subtle border-danger/15"
          : "bg-warning-subtle border-warning/15"
      )}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
              isAuthorized ? "bg-success/10" : authState.includes("BLOCKED") ? "bg-danger/10" : "bg-warning/10"
            )}>
              {isAuthorized ? (
                <ShieldCheck className="w-5 h-5 text-success" />
              ) : authState.includes("BLOCKED") ? (
                <ShieldX className="w-5 h-5 text-danger" />
              ) : (
                <ShieldAlert className="w-5 h-5 text-warning" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className={cn(
                  "text-base lg:text-lg font-bold tracking-tight",
                  isAuthorized ? "text-success" : authState.includes("BLOCKED") ? "text-danger" : "text-warning"
                )}>
                  {authState}
                </h1>
                <StatusDot level={isAuthorized ? "green" : authState.includes("BLOCKED") ? "red" : "yellow"} pulse={isAuthorized} size="sm" />
              </div>
              <FreshnessIndicator
                level={health ? "live" : "disconnected"}
                timestamp={health?.timestamp}
                compact
                className="mt-0.5"
              />
            </div>
          </div>

          {/* Desktop only — side stats */}
          <div className="hidden sm:flex items-center gap-6">
            <div className="text-right">
              <p className="text-[9px] text-text-muted uppercase tracking-wider">Campaign</p>
              <p className="text-xs font-mono text-text-secondary mt-0.5">{qual?.campaign_id || "—"}</p>
            </div>
            <div className="text-right">
              <p className="text-[9px] text-text-muted uppercase tracking-wider">Build</p>
              <p className="text-xs font-mono text-text-secondary mt-0.5">{build?.git_head?.slice(0, 7) || "—"}</p>
            </div>
            <div className="text-right">
              <p className="text-[9px] text-text-muted uppercase tracking-wider">Positions</p>
              <p className="text-xs font-mono text-text-secondary mt-0.5">{protectedCount}/{totalCount} protected</p>
            </div>
          </div>
        </div>

        {/* Mobile — compact stats row */}
        <div className="sm:hidden flex items-center gap-4 mt-3 pt-3 border-t border-border-subtle/50">
          <div className="flex-1 min-w-0">
            <p className="text-[9px] text-text-muted uppercase">Build</p>
            <p className="text-[11px] font-mono text-text-secondary truncate">{build?.git_head?.slice(0, 7) || "—"}</p>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[9px] text-text-muted uppercase">Positions</p>
            <p className="text-[11px] font-mono text-text-secondary">{protectedCount}/{totalCount}</p>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[9px] text-text-muted uppercase">Campaign</p>
            <p className="text-[11px] font-mono text-text-secondary truncate">{qual?.campaign_id || "—"}</p>
          </div>
        </div>

        {/* Gate strip */}
        <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-border-subtle/50">
          {[
            { label: "Build", ok: build?.verified },
            { label: "Watchdog", ok: health?.status === "ok" },
            { label: "Risk", ok: !risk?.any_critical },
            { label: "Recon", ok: account?.freshness === "LIVE" },
            { label: "Broker", ok: account?.freshness === "LIVE" },
            { label: "Data", ok: risk?.freshness === "LIVE" || risk?.freshness === "STALE" },
          ].map((g) => (
            <span
              key={g.label}
              className={cn(
                "ec-badge text-[10px]",
                g.ok
                  ? "bg-success-subtle text-success border border-success/10"
                  : "bg-danger-subtle text-danger border border-danger/10"
              )}
            >
              <span className={cn("w-1 h-1 rounded-full", g.ok ? "bg-success" : "bg-danger")} />
              {g.label}
            </span>
          ))}
        </div>
      </div>

      {/* ═══ System Health Matrix ═══ */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-text-muted" />
            <h3>System Health</h3>
          </div>
          <StatusBadge
            variant={fullHealth?.overall_state === "HEALTHY" ? "success" : fullHealth?.blocking_dimensions?.length ? "danger" : "warning"}
            size="sm"
          >
            {fullHealth?.overall_state || "UNKNOWN"}
          </StatusBadge>
        </PanelHeader>
        <PanelContent noPadding>
          <HealthMatrix dimensions={fullHealth?.dimensions || []} className="m-3" />
        </PanelContent>
      </Panel>

      {/* ═══ Core Metrics — 2-col mobile, 6-col desktop ═══ */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-px bg-border-subtle rounded-lg overflow-hidden">
        {[
          {
            label: "Equity",
            value: formatCurrency(account?.equity || 0),
            sub: `Balance: ${formatCurrency(account?.balance || 0)}`,
            status: "neutral" as const,
            freshness: account?.freshness,
          },
          {
            label: "Daily P&L",
            value: formatCurrency(account?.daily_pnl || 0),
            sub: `Budget: ${formatCurrency(account?.daily_loss_remaining || 0)}`,
            status: (account?.daily_pnl ?? 0) >= 0 ? ("positive" as const) : ("negative" as const),
            icon: (account?.daily_pnl ?? 0) >= 0 ? TrendingUp : TrendingDown,
            freshness: account?.freshness,
          },
          {
            label: "Drawdown",
            value: formatPercent(account?.drawdown_pct || 0),
            sub: `HWM: ${formatCurrency(account?.equity_high_water || 0)}`,
            status: (account?.drawdown_pct ?? 0) > 0.05 ? ("warning" as const) : ("neutral" as const),
            freshness: account?.freshness,
          },
          {
            label: "Positions",
            value: `${totalCount}`,
            sub: `${protectedCount} protected`,
            status: protectedCount === totalCount ? ("positive" as const) : ("warning" as const),
          },
          {
            label: "Exposure",
            value: formatCurrency(account?.margin_used || 0),
            sub: `Util: ${((account?.margin_utilization || 0) * 100).toFixed(1)}%`,
            status: (account?.margin_utilization ?? 0) > 0.8 ? ("warning" as const) : ("neutral" as const),
            freshness: account?.freshness,
          },
          {
            label: "Risk",
            value: risk?.overall_level || "UNKNOWN",
            sub: risk?.any_critical ? "Critical detected" : "Nominal",
            status: risk?.overall_level === "NORMAL" ? ("positive" as const) : risk?.any_critical ? ("negative" as const) : ("warning" as const),
            freshness: risk?.freshness,
          },
        ].map((m) => (
          <div key={m.label} className="bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3">
            <Metric
              label={m.label}
              value={
                <span className="flex items-center gap-1.5">
                  {m.icon && <m.icon className={cn("w-3.5 h-3.5", m.status === "positive" ? "text-success" : "text-danger")} />}
                  {m.value}
                </span>
              }
              subvalue={m.sub}
              status={m.status}
            />
            {m.freshness && (
              <FreshnessIndicator level={m.freshness === "LIVE" ? "live" : m.freshness === "STALE" ? "stale" : "unknown"} compact className="mt-1" />
            )}
          </div>
        ))}
      </div>

      {/* ═══ Two-column: Protection + Qualification ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 lg:gap-4">
        {/* Protection Status */}
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-3.5 h-3.5 text-text-muted" />
              <h3>Protection</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <div className="space-y-2">
              {[
                { label: "SL Coverage", value: `${protectedCount} / ${totalCount} positions`, level: protectedCount === totalCount ? ("green" as const) : ("yellow" as const) },
                { label: "Risk Envelope", value: risk?.overall_level === "NORMAL" ? "Within limits" : risk?.overall_level || "UNKNOWN", level: risk?.overall_level === "NORMAL" ? ("green" as const) : ("red" as const) },
                { label: "Reconciliation", value: "Reconciled", level: "green" as const },
                { label: "Shadow REDUCED", value: "Simulation only", level: "purple" as const },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between py-1">
                  <span className="text-xs text-text-secondary">{item.label}</span>
                  <StatusDot level={item.level} label={item.value} size="xs" />
                </div>
              ))}
            </div>
          </PanelContent>
        </Panel>

        {/* Qualification */}
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-text-muted" />
              <h3>Qualification</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <div className="space-y-2">
              <div className="flex items-center justify-between py-1">
                <span className="text-xs text-text-secondary">Status</span>
                <StatusBadge variant={qual?.evidence_insufficient ? "warning" : "success"} size="sm">
                  {qual?.evidence_insufficient ? "COLLECTING" : "SUFFICIENT"}
                </StatusBadge>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-xs text-text-secondary">Closed Trades</span>
                <span className="text-xs font-medium ec-num text-text-primary">{qual?.evidence_maturity?.e0_count || 0}</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-xs text-text-secondary">Open Trades</span>
                <span className="text-xs font-medium ec-num text-text-primary">{totalCount}</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-xs text-text-secondary">Days Observed</span>
                <span className="text-xs font-medium ec-num text-text-primary">{qual?.evidence_maturity?.observation_days || 0}</span>
              </div>
            </div>
          </PanelContent>
        </Panel>
      </div>

      {/* ═══ Recent Alerts ═══ */}
      {alerts && alerts.length > 0 && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-text-muted" />
              <h3>Recent Alerts</h3>
            </div>
            <span className="text-[10px] text-text-muted">{alerts.length} total</span>
          </PanelHeader>
          <PanelContent noPadding>
            <div>
              {alerts.slice(0, 4).map((alert) => (
                <div key={alert.alert_id} className="flex items-center gap-3 px-4 py-2.5 border-b border-border-subtle last:border-b-0 hover:bg-surface-hover transition-colors">
                  <StatusDot
                    level={alert.severity === "CRITICAL" ? "red" : alert.severity === "WARNING" ? "yellow" : "blue"}
                    size="xs"
                  />
                  <span className="text-xs text-text-primary flex-1 truncate min-w-0">{alert.message}</span>
                  <span className="text-[10px] text-text-muted shrink-0 ec-badge bg-surface-overlay text-text-muted border border-border-primary hidden sm:inline">
                    {alert.category}
                  </span>
                </div>
              ))}
            </div>
          </PanelContent>
        </Panel>
      )}
    </div>
  );
}
