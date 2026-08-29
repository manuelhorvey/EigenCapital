import { useQuery } from "@tanstack/react-query";
import { getRiskState, getRiskEnvelope } from "../lib/api";
import { cn, formatNumber } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Metric from "../components/ui/Metric";
import Skeleton from "../components/ui/Skeleton";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import { RiskUtilizationChart, DrawdownGauge, ExposurePieChart, RiskHeatmap } from "../components/ui/RiskCharts";
import { Shield, TrendingUp, AlertTriangle, BarChart3 } from "lucide-react";

interface DimensionGroup {
  label: string;
  dimensions: string[];
}

const DIMENSION_GROUPS: DimensionGroup[] = [
  { label: "Capital", dimensions: ["drawdown", "daily_loss", "loss_velocity", "equity_floor"] },
  { label: "Exposure", dimensions: ["gross_exposure", "net_exposure", "concentration", "position_count", "sector_breakdown"] },
  { label: "Execution / Protection", dimensions: ["margin", "sl_protection", "stale_data"] },
  { label: "Diagnostic", dimensions: ["var"] },
];

export default function Risk() {
  const { data: risk, isLoading } = useQuery({ queryKey: ["riskState"], queryFn: getRiskState, refetchInterval: 10000 });
  const { data: envelope } = useQuery({ queryKey: ["riskEnvelope"], queryFn: getRiskEnvelope, refetchInterval: 60000 });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-48 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }

  const getLevel = (level: string): "green" | "yellow" | "red" | "gray" => {
    switch (level.toUpperCase()) {
      case "NORMAL": return "green";
      case "WARNING": case "ELEVATED": return "yellow";
      case "CRITICAL": case "HALT": return "red";
      default: return "gray";
    }
  };

  const getObsForDim = (dimName: string) => risk?.observations?.find((o) => o.dimension === dimName);
  const formatDimName = (dim: string) => dim.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  // Prepare chart data from observations
  const allObs = risk?.observations || [];
  const chartData = allObs.map((obs) => ({
    name: obs.dimension,
    value: obs.value,
    limit: obs.limit,
    level: obs.level,
  }));

  // Exposure data for pie chart
  const grossObs = getObsForDim("gross_exposure");
  const netObs = getObsForDim("net_exposure");
  const longExposure = netObs ? Math.max(0, netObs.value) : 0;
  const shortExposure = netObs ? Math.abs(Math.min(0, netObs.value)) : 0;

  // Drawdown data
  const drawdownObs = getObsForDim("drawdown");
  const drawdownLimit = envelope?.max_account_drawdown_pct
    ? envelope.max_account_drawdown_pct * 100
    : 10;

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Risk</h1>
          <StatusBadge
            variant={risk?.overall_level === "NORMAL" ? "success" : risk?.any_critical ? "danger" : "warning"}
            size="md"
          >
            {risk?.overall_level || "UNKNOWN"}
          </StatusBadge>
        </div>
        <FreshnessIndicator level={risk?.freshness === "LIVE" ? "live" : risk?.freshness === "STALE" ? "stale" : "unknown"} compact />
      </div>

      {/* Top status strip */}
      <div className="grid grid-cols-3 gap-px bg-border-subtle rounded-lg overflow-hidden">
        <div className={cn("bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3", risk?.overall_level === "NORMAL" && "border-l-2 border-l-success")}>
          <Metric label="Overall" value={risk?.overall_level || "UNKNOWN"} status={risk?.overall_level === "NORMAL" ? "positive" : risk?.any_critical ? "negative" : "warning"} />
        </div>
        <div className={cn("bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3", (risk?.critical_dimensions?.length || 0) > 0 && "border-l-2 border-l-danger")}>
          <Metric label="Critical" value={risk?.critical_dimensions?.length || 0} status={(risk?.critical_dimensions?.length || 0) > 0 ? "negative" : "neutral"} />
        </div>
        <div className={cn("bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3", (risk?.warning_dimensions?.length || 0) > 0 && "border-l-2 border-l-warning")}>
          <Metric label="Warning" value={risk?.warning_dimensions?.length || 0} status={(risk?.warning_dimensions?.length || 0) > 0 ? "warning" : "neutral"} />
        </div>
      </div>

      {/* ═══ Visualizations Row ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-4">
        {/* Risk Heatmap */}
        <Panel className="lg:col-span-2">
          <PanelHeader>
            <div className="flex items-center gap-2">
              <BarChart3 className="w-3.5 h-3.5 text-text-muted" />
              <h3>Risk Heatmap</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <RiskHeatmap
              items={allObs.map((o) => ({ name: o.dimension, level: o.level, value: o.value, limit: o.limit }))}
              columns={window.innerWidth < 640 ? 3 : 5}
            />
          </PanelContent>
        </Panel>

        {/* Exposure Distribution */}
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <TrendingUp className="w-3.5 h-3.5 text-text-muted" />
              <h3>Exposure</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <ExposurePieChart longExposure={longExposure} shortExposure={shortExposure} />
            <div className="mt-3 pt-3 border-t border-border-subtle grid grid-cols-2 gap-2">
              <Metric label="Gross" value={grossObs ? formatNumber(grossObs.value, 0) : "—"} status="neutral" />
              <Metric label="Net" value={netObs ? formatNumber(netObs.value, 0) : "neutral" as const} status={netObs ? (netObs.value >= 0 ? "positive" : "negative") : "neutral"} />
            </div>
          </PanelContent>
        </Panel>
      </div>

      {/* ═══ Utilization + Drawdown ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-4">
        {/* Utilization Bar Chart */}
        <Panel className="lg:col-span-2">
          <PanelHeader>
            <div className="flex items-center gap-2">
              <BarChart3 className="w-3.5 h-3.5 text-text-muted" />
              <h3>Utilization</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <RiskUtilizationChart data={chartData} />
          </PanelContent>
        </Panel>

        {/* Drawdown Gauge */}
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-text-muted" />
              <h3>Drawdown</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <DrawdownGauge
              current={drawdownObs?.value ?? 0}
              max={drawdownLimit}
              label="Account Drawdown"
            />
            <div className="mt-4 pt-3 border-t border-border-subtle space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Daily Loss</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("daily_loss") ? formatNumber(getObsForDim("daily_loss")!.value, 2) : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Loss Velocity</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("loss_velocity") ? formatNumber(getObsForDim("loss_velocity")!.value, 2) : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Equity Floor</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("equity_floor") ? `$${formatNumber(getObsForDim("equity_floor")!.value, 0)}` : "—"}
                </span>
              </div>
            </div>
          </PanelContent>
        </Panel>
      </div>

      {/* ═══ Dimension Groups ═══ */}
      {DIMENSION_GROUPS.map((group) => {
        const groupObs = group.dimensions.map(getObsForDim).filter(Boolean) as NonNullable<ReturnType<typeof getObsForDim>>[];
        if (groupObs.length === 0) return null;

        return (
          <Panel key={group.label}>
            <PanelHeader>
              <div className="flex items-center gap-2">
                {group.label === "Diagnostic" ? <AlertTriangle className="w-3.5 h-3.5 text-text-muted" /> : group.label === "Capital" ? <Shield className="w-3.5 h-3.5 text-text-muted" /> : <TrendingUp className="w-3.5 h-3.5 text-text-muted" />}
                <h3>{group.label}</h3>
              </div>
            </PanelHeader>
            <PanelContent noPadding>
              <div className="divide-y divide-border-subtle">
                {groupObs.map((obs) => {
                  const utilization = obs.limit ? (obs.value / obs.limit) * 100 : 0;
                  const level = getLevel(obs.level);
                  return (
                    <div
                      key={obs.dimension}
                      className={cn(
                        "flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 px-3 lg:px-4 py-2.5 lg:py-3 hover:bg-surface-hover transition-colors",
                        obs.level === "CRITICAL" && "bg-danger-subtle/30",
                        obs.level === "WARNING" && "bg-warning-subtle/30"
                      )}
                    >
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <StatusDot level={level} size="xs" />
                        <span className="text-xs font-medium text-text-primary">{formatDimName(obs.dimension)}</span>
                        {obs.dimension === "var_estimate" && <StatusBadge variant="purple" size="sm">DIAG</StatusBadge>}
                      </div>
                      <div className="flex items-center gap-3 shrink-0 sm:ml-auto">
                        {obs.limit && (
                          <div className="w-20 lg:w-24">
                            <div className="h-1 rounded-full bg-surface-overlay overflow-hidden">
                              <div
                                className={cn("h-full rounded-full transition-all duration-500", utilization > 80 ? "bg-danger" : utilization > 60 ? "bg-warning" : "bg-success")}
                                style={{ width: `${Math.min(utilization, 100)}%` }}
                              />
                            </div>
                          </div>
                        )}
                        <span className="text-xs font-mono font-medium text-text-primary w-16 text-right">
                          {formatNumber(obs.value, 2)}
                          {obs.limit && <span className="text-text-muted"> / {formatNumber(obs.limit, 2)}</span>}
                        </span>
                        <StatusBadge
                          variant={level === "green" ? "success" : level === "yellow" ? "warning" : level === "red" ? "danger" : "neutral"}
                          size="sm"
                        >
                          {obs.level}
                        </StatusBadge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </PanelContent>
          </Panel>
        );
      })}

      {/* ═══ Risk Envelope ═══ */}
      {envelope && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-text-muted" />
              <h3>Risk Envelope</h3>
            </div>
          </PanelHeader>
          <PanelContent>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-3">
              {[
                { label: "Max Positions", value: String(envelope.max_concurrent_positions) },
                { label: "Max Daily Loss", value: `$${envelope.max_daily_loss}` },
                { label: "Min Equity", value: `$${envelope.min_equity}` },
                { label: "Max Drawdown", value: `${(envelope.max_account_drawdown_pct * 100).toFixed(0)}%` },
                { label: "Max Position Notional", value: `$${envelope.max_position_notional}` },
                { label: "Max Order Notional", value: `$${envelope.max_order_notional}` },
                { label: "Per-Position Loss", value: `${(envelope.max_per_position_loss_pct * 100).toFixed(0)}%` },
                { label: "SL Required", value: envelope.require_sl_on_positions ? "YES" : "NO" },
              ].map((item) => (
                <div key={item.label} className="bg-surface-overlay rounded-md px-3 py-2">
                  <p className="text-[10px] text-text-muted uppercase tracking-wider">{item.label}</p>
                  <p className="text-sm font-semibold ec-num text-text-primary mt-0.5">{item.value}</p>
                </div>
              ))}
            </div>
          </PanelContent>
        </Panel>
      )}
    </div>
  );
}
