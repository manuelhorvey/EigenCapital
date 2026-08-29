import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, ReferenceLine } from "recharts";
import { cn } from "../../lib/utils";

// ─── Theme colors for charts (color-blind safe palette) ──────────────
const COLORS = {
  success: "#009B77",     // Deuteranopia-safe green
  warning: "#F08A00",     // Deuteranopia-safe amber
  danger: "#D33F49",      // Deuteranopia-safe red
  purple: "#8C6FE6",      // Deuteranopia-safe purple
  info: "#0072B5",        // Deuteranopia-safe blue
  muted: "#52525b",
  surface: "#18181b",
  border: "#27272a",
  textPrimary: "#fafafa",
  textSecondary: "#a1a1aa",
  textMuted: "#52525b",
};

function getLevelColor(level: string): string {
  const upper = level.toUpperCase();
  if (upper === "NORMAL" || upper === "HEALTHY") return COLORS.success;
  if (upper === "WARNING" || upper === "ELEVATED") return COLORS.warning;
  if (upper === "CRITICAL" || upper === "HALT") return COLORS.danger;
  return COLORS.muted;
}

// ─── Custom Tooltip ─────────────────────────────────────────────────
interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; payload: { name: string; value: number; limit: number | null; level: string } }>;
  label?: string;
}

function ChartTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload;
  return (
    <div className="bg-surface-elevated border border-border-primary rounded-lg px-3 py-2 shadow-xl">
      <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1">{data.name}</p>
      <p className="text-sm font-mono font-medium text-text-primary">
        {data.value.toFixed(2)}
        {data.limit ? <span className="text-text-muted"> / {data.limit.toFixed(2)}</span> : null}
      </p>
      <p className="text-[10px] text-text-muted mt-0.5">{data.level}</p>
    </div>
  );
}

// ─── Risk Utilization Bar Chart ─────────────────────────────────────
interface RiskBarData {
  name: string;
  value: number;
  limit: number | null;
  level: string;
}

interface RiskUtilizationChartProps {
  data: RiskBarData[];
  className?: string;
}

function ChartSummary({ data, type }: { data: RiskBarData[]; type: "utilization" | "drawdown" | "exposure" | "heatmap" }) {
  const items = data
    .filter((d) => d.limit && d.limit > 0)
    .map((d) => ({
      ...d,
      utilization: (d.value / d.limit!) * 100,
      shortName: d.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    }));

  if (items.length === 0) return null;

  const critical = items.filter((d) => d.utilization > 80);
  const warning = items.filter((d) => d.utilization > 60 && d.utilization <= 80);
  const normal = items.filter((d) => d.utilization <= 60);

  let summary = "";
  if (type === "utilization") {
    summary = `Risk Utilization: ${items.length} dimensions tracked. ${critical.length} critical (>80%), ${warning.length} warning (60-80%), ${normal.length} normal (≤60%).`;
  } else if (type === "drawdown") {
    summary = `Drawdown monitoring active with warning at 60% and critical at 80% of limit.`;
  } else if (type === "exposure") {
    const long = items.find((d) => d.name.includes("long"))?.value || 0;
    const short = items.find((d) => d.name.includes("short"))?.value || 0;
    summary = `Exposure distribution: ${items.length} categories. Long ${long.toFixed(0)}, Short ${short.toFixed(0)}.`;
  } else if (type === "heatmap") {
    summary = `Risk heatmap: ${items.length} dimensions. ${critical.length} critical, ${warning.length} warning, ${normal.length} normal.`;
  }

  return (
    <div className="sr-only" role="status" aria-live="polite">
      {summary}
    </div>
  );
}

export function RiskUtilizationChart({ data, className }: RiskUtilizationChartProps) {
  // Only show dimensions with limits (utilizable dimensions)
  const chartData = data
    .filter((d) => d.limit && d.limit > 0)
    .map((d) => ({
      ...d,
      utilization: (d.value / d.limit!) * 100,
      shortName: d.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    }));

  if (chartData.length === 0) {
    return (
      <div className={cn("flex items-center justify-center h-32 text-xs text-text-muted", className)}>
        No utilization data available
      </div>
    );
  }

  return (
    <div className={cn("w-full", className)}>
      <ChartSummary data={data} type="utilization" />
      <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 32)}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 80, left: 10, bottom: 0 }}
          barSize={16}
        >
          <XAxis
            type="number"
            domain={[0, 120]}
            tick={{ fontSize: 10, fill: COLORS.textMuted }}
            axisLine={{ stroke: COLORS.border }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="shortName"
            tick={{ fontSize: 10, fill: COLORS.textSecondary }}
            axisLine={false}
            tickLine={false}
            width={110}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
          <ReferenceLine x={80} stroke={COLORS.warning} strokeDasharray="3 3" strokeWidth={1} />
          <ReferenceLine x={100} stroke={COLORS.danger} strokeDasharray="3 3" strokeWidth={1} />
          <Bar dataKey="utilization" radius={[0, 4, 4, 0]}>
            {chartData.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.utilization > 80 ? COLORS.danger : entry.utilization > 60 ? COLORS.warning : COLORS.success}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Drawdown Gauge ─────────────────────────────────────────────────
interface DrawdownGaugeProps {
  current: number;
  max: number;
  label?: string;
  className?: string;
}

export function DrawdownGauge({ current, max, label = "Drawdown", className }: DrawdownGaugeProps) {
  const pct = max > 0 ? Math.min((current / max) * 100, 100) : 0;
  const color = pct > 80 ? COLORS.danger : pct > 60 ? COLORS.warning : COLORS.success;

  const summary = `Drawdown: ${current.toFixed(2)}% of ${max.toFixed(0)}% limit (${pct > 80 ? "critical" : pct > 60 ? "warning" : "normal"}). Warning threshold at 60%, critical at 80%.`;

  return (
    <div className={cn("w-full", className)}>
      <div className="sr-only" role="status" aria-live="polite">{summary}</div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-text-muted uppercase tracking-wider">{label}</span>
        <span className="text-xs font-mono text-text-primary">{current.toFixed(2)}% / {max.toFixed(0)}%</span>
      </div>
      <div className="relative h-3 bg-surface-overlay rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
        {/* Limit markers */}
        <div className="absolute top-0 h-full w-px bg-warning/50" style={{ left: "60%" }} />
        <div className="absolute top-0 h-full w-px bg-danger/50" style={{ left: "80%" }} />
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-[8px] text-text-muted">0%</span>
        <span className="text-[8px] text-text-muted">60%</span>
        <span className="text-[8px] text-text-muted">80%</span>
        <span className="text-[8px] text-text-muted">100%</span>
      </div>
    </div>
  );
}

// ─── Exposure Distribution Pie ──────────────────────────────────────
interface ExposureSlice {
  name: string;
  value: number;
}

interface ExposurePieChartProps {
  longExposure: number;
  shortExposure: number;
  className?: string;
}

export function ExposurePieChart({ longExposure, shortExposure, className }: ExposurePieChartProps) {
  const data: ExposureSlice[] = [
    { name: "Long", value: Math.abs(longExposure) },
    { name: "Short", value: Math.abs(shortExposure) },
  ].filter((d) => d.value > 0);

  if (data.length === 0) {
    return (
      <div className={cn("flex items-center justify-center h-32 text-xs text-text-muted", className)}>
        No exposure data
      </div>
    );
  }

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const longPct = data.find((d) => d.name === "Long") ? ((data.find((d) => d.name === "Long")!.value / total) * 100).toFixed(1) : "0";
  const shortPct = data.find((d) => d.name === "Short") ? ((data.find((d) => d.name === "Short")!.value / total) * 100).toFixed(1) : "0";

  const summary = `Exposure distribution: ${data.length} categories. Long ${longPct}%, Short ${shortPct}%. Total notional ${(total / 1000).toFixed(1)}K.`;

  return (
    <div className={cn("flex items-center gap-4", className)}>
      <div className="sr-only" role="status" aria-live="polite">{summary}</div>
      <div className="relative">
        <ResponsiveContainer width={120} height={120}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={30}
              outerRadius={50}
              paddingAngle={2}
              dataKey="value"
              strokeWidth={0}
            >
              {data.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={entry.name === "Long" ? COLORS.success : COLORS.warning}
                />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        {/* Center label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-[9px] text-text-muted uppercase">Total</span>
          <span className="text-xs font-mono font-medium text-text-primary">{(total / 1000).toFixed(1)}K</span>
        </div>
      </div>
      <div className="space-y-2">
        {data.map((entry) => (
          <div key={entry.name} className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: entry.name === "Long" ? COLORS.success : COLORS.warning }}
            />
            <span className="text-xs text-text-secondary">{entry.name}</span>
            <span className="text-xs font-mono text-text-primary ml-auto">
              {((entry.value / total) * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Risk Heatmap Grid ──────────────────────────────────────────────
interface HeatmapItem {
  name: string;
  level: string;
  value: number;
  limit: number | null;
}

interface RiskHeatmapProps {
  items: HeatmapItem[];
  columns?: number;
  className?: string;
}

export function RiskHeatmap({ items, columns = 4, className }: RiskHeatmapProps) {
  const formatDimName = (dim: string) => dim.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const critical = items.filter((i) => getLevelColor(i.level) === COLORS.danger).length;
  const warning = items.filter((i) => getLevelColor(i.level) === COLORS.warning).length;
  const normal = items.filter((i) => getLevelColor(i.level) === COLORS.success).length;

  const summary = `Risk heatmap: ${items.length} dimensions. ${critical} critical, ${warning} warning, ${normal} normal.`;

  return (
    <div
      className={cn("grid gap-px bg-border-subtle rounded-lg overflow-hidden", className)}
      style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
    >
      <div className="sr-only" role="status" aria-live="polite">{summary}</div>
      {items.map((item) => {
        const color = getLevelColor(item.level);
        return (
          <div
            key={item.name}
            className="px-2.5 py-2 bg-surface-raised flex flex-col items-center text-center"
          >
            <span
              className="w-2 h-2 rounded-full mb-1"
              style={{ backgroundColor: color }}
            />
            <span className="text-[9px] text-text-muted uppercase tracking-wider leading-tight mb-0.5">
              {formatDimName(item.name)}
            </span>
            <span className="text-[10px] font-mono font-medium" style={{ color }}>
              {item.level.toUpperCase().slice(0, 4)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
