import { useQuery } from "@tanstack/react-query";
import { getRiskState, getRiskEnvelope } from "../lib/api";
import { cn, formatNumber, formatPercent, formatDimName } from "../lib/utils";
import { stateToDotLevel, stateToBadgeVariant } from "../lib/status";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Metric from "../components/ui/Metric";
import Skeleton from "../components/ui/Skeleton";
import PageError from "../components/ui/PageError";
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
  { label: "Execution / Protection", dimensions: ["margin_utilization", "sl_protection", "stale_data", "slippage"] },
  { label: "Diagnostic", dimensions: ["var_estimate"] },
];

export default function Risk() {
  const { data: risk, isLoading, isError, refetch } = useQuery({ queryKey: ["riskState"], queryFn: getRiskState, refetchInterval: 10000 });
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

  if (isError && !risk) {
    return <PageError title="Risk" subsystem="GET /risk" onRetry={() => refetch()} />;
  }

  // Status → color mapping is centralized in lib/status.ts (contract §8.1)
  const getLevel = (level: string): "green" | "yellow" | "red" | "gray" => {
    const dot = stateToDotLevel(level);
    return dot === "blue" || dot === "purple" ? "gray" : dot;
  };

  const getObsForDim = (dimName: string) => risk?.observations?.find((o) => o.dimension === dimName);

  // Unit-aware value formatting for risk observation rows. RiskObserver emits
  // mixed units: fractions (drawdown/concentration/utilization), USD
  // (daily_loss/equity_floor/notionals), and counts.
  const RISK_DIM_UNITS: Record<string, "pct" | "usd" | "count"> = {
    drawdown: "pct",
    daily_loss: "usd",
    equity_floor: "usd",
    gross_exposure: "usd",
    net_exposure: "usd",
    concentration: "pct",
    position_count: "count",
    margin_utilization: "pct",
    sl_protection: "pct",
    loss_velocity: "usd",
    var_estimate: "pct",
  };

  const formatObsValue = (dim: string, value: number): string => {
    switch (RISK_DIM_UNITS[dim]) {
      case "pct":
        return formatPercent(value);
      case "usd":
        return `$${formatNumber(value, 2)}`;
      case "count":
        return formatNumber(value, 0);
      default:
        return formatNumber(value, 2);
    }
  };

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

  // Drawdown data. RiskObserver emits drawdown as a fraction (0–1) with the
  // limit in the same unit; the envelope limit is also a fraction. The gauge
  // works in percent, so scale both by 100. Missing data renders as unknown,
  // never as 0% (contract T3: unknown ≠ zero).
  const drawdownObs = getObsForDim("drawdown");
  const drawdownLimitPct = envelope?.max_account_drawdown_pct
    ? envelope.max_account_drawdown_pct * 100
    : null;
  const drawdownCurrentPct = drawdownObs?.value != null ? drawdownObs.value * 100 : null;

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
            {risk?.overall_level || "No data"}
          </StatusBadge>
        </div>
        <FreshnessIndicator level={risk?.freshness === "LIVE" ? "live" : "stale"} timestamp={risk?.timestamp} compact />
      </div>

      {/* Top status strip */}
      <div className="grid grid-cols-3 gap-px bg-border-subtle rounded-lg overflow-hidden">
        <div className={cn("bg-surface-raised px-3 lg:px-4 py-2.5 lg:py-3", risk?.overall_level === "NORMAL" && "border-l-2 border-l-success")}>
          <Metric label="Overall" value={risk?.overall_level || "No data"} status={risk?.overall_level === "NORMAL" ? "positive" : risk?.any_critical ? "negative" : "warning"} />
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
              columns={3}
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
              <Metric label="Gross" value={grossObs ? formatNumber(grossObs.value, 0) : "No data"} status="neutral" />
              <Metric label="Net" value={netObs ? formatNumber(netObs.value, 0) : "No data"} status={netObs ? (netObs.value >= 0 ? "positive" : "negative") : "neutral"} />
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
            {drawdownCurrentPct != null && drawdownLimitPct != null ? (
              <DrawdownGauge
                current={drawdownCurrentPct}
                max={drawdownLimitPct}
                label="Account Drawdown"
              />
            ) : (
              <div className="flex items-center justify-center h-16 text-xs text-text-muted">
                Drawdown data not available
              </div>
            )}
            <div className="mt-4 pt-3 border-t border-border-subtle space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Daily Loss</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("daily_loss") ? formatObsValue("daily_loss", getObsForDim("daily_loss")!.value) : "No data"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Loss Velocity</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("loss_velocity") ? formatObsValue("loss_velocity", getObsForDim("loss_velocity")!.value) : "No data"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Equity Floor</span>
                <span className="text-xs font-mono text-text-primary">
                  {getObsForDim("equity_floor") ? formatObsValue("equity_floor", getObsForDim("equity_floor")!.value) : "No data"}
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
                        {(obs.dimension === "var_estimate" || obs.dimension === "slippage") && <StatusBadge variant="purple" size="sm">DIAG</StatusBadge>}
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
                        <span className="text-xs font-mono font-medium text-text-primary w-24 text-right">
                          {formatObsValue(obs.dimension, obs.value)}
                          {obs.limit != null && <span className="text-text-muted"> / {formatObsValue(obs.dimension, obs.limit)}</span>}
                        </span>
                        <StatusBadge
                          variant={stateToBadgeVariant(obs.level)}
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
                { label: "Max Drawdown", value: `${formatNumber(envelope.max_account_drawdown_pct * 100, 0)}%` },
                { label: "Max Position Notional", value: `$${envelope.max_position_notional}` },
                { label: "Max Order Notional", value: `$${envelope.max_order_notional}` },
                { label: "Per-Position Loss", value: `${formatNumber(envelope.max_per_position_loss_pct * 100, 0)}%` },
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
