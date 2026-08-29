import { cn } from "../../lib/utils";

interface HealthDimension {
  dimension: string;
  state: string;
  message?: string;
}

interface HealthMatrixProps {
  dimensions: HealthDimension[];
  className?: string;
}

function getStateColor(state: string): string {
  const upper = state.toUpperCase();
  if (upper.includes("HEALTHY") || upper === "OK" || upper === "NORMAL") return "bg-success";
  if (upper.includes("DEGRADED") || upper.includes("WARNING") || upper.includes("ELEVATED")) return "bg-warning";
  if (upper.includes("BLOCKED") || upper.includes("CRITICAL") || upper.includes("HALT") || upper.includes("FAIL")) return "bg-danger";
  return "bg-text-muted";
}

function getStateLabel(state: string): string {
  const upper = state.toUpperCase();
  if (upper.includes("HEALTHY") || upper === "OK" || upper === "NORMAL") return "OK";
  if (upper.includes("DEGRADED") || upper.includes("WARNING") || upper.includes("ELEVATED")) return "WARN";
  if (upper.includes("BLOCKED") || upper.includes("CRITICAL") || upper.includes("HALT") || upper.includes("FAIL")) return "CRIT";
  return upper.slice(0, 4);
}

function formatDimName(dim: string): string {
  return dim.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function HealthMatrix({ dimensions, className }: HealthMatrixProps) {
  // Screen-reader summary
  const healthy = dimensions.filter((d) => getStateLabel(d.state) === "OK").length;
  const warnings = dimensions.filter((d) => getStateLabel(d.state) === "WARN").length;
  const critical = dimensions.filter((d) => getStateLabel(d.state) === "CRIT").length;
  const summary = `System health: ${healthy} healthy, ${warnings} warning, ${critical} critical out of ${dimensions.length} dimensions.`;

  return (
    <div className={cn("relative", className)}>
      <div className="sr-only" role="status" aria-live="polite">
        {summary}
      </div>
      <div
        className={cn(
          // 2 cols on mobile (more room per cell), 3 cols on sm+
          "grid grid-cols-2 sm:grid-cols-3 gap-px bg-border-subtle rounded-lg overflow-hidden"
        )}
        role="grid"
        aria-label="System health dimensions"
      >
        {dimensions.map((dim) => (
        <div
          key={dim.dimension}
          className="bg-surface-raised px-2.5 sm:px-3 py-2 sm:py-2.5 flex items-center gap-2 group"
          title={dim.message || `${dim.dimension}: ${dim.state}`}
          role="gridcell"
        >
          <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", getStateColor(dim.state))} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="text-[9px] sm:text-[10px] font-medium text-text-muted uppercase tracking-wider truncate">
              {formatDimName(dim.dimension)}
            </p>
            <p className={cn(
              "text-[9px] sm:text-[10px] font-medium ec-num mt-0.5",
              dim.state.toUpperCase().includes("HEALTHY") || dim.state.toUpperCase() === "OK"
                ? "text-success"
                : dim.state.toUpperCase().includes("CRITICAL") || dim.state.toUpperCase().includes("HALT")
                ? "text-danger"
                : dim.state.toUpperCase().includes("WARNING") || dim.state.toUpperCase().includes("DEGRADED")
                ? "text-warning"
                : "text-text-muted"
            )}>
              {getStateLabel(dim.state)}
            </p>
          </div>
        </div>
      ))}
      </div>
    </div>
  );
}
