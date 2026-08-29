import { cn } from "../../lib/utils";

interface MetricCardProps {
  label: string;
  value: string | number;
  subvalue?: string;
  status?: "healthy" | "warning" | "critical" | "neutral";
  className?: string;
  mono?: boolean;
}

export default function MetricCard({
  label,
  value,
  subvalue,
  status = "neutral",
  className,
  mono = true,
}: MetricCardProps) {
  const statusColors = {
    healthy: "text-status-green",
    warning: "text-status-yellow",
    critical: "text-status-red",
    neutral: "text-text-primary",
  };

  return (
    <div
      className={cn(
        "rounded-lg border border-border-default bg-bg-card p-4 transition-colors hover:border-border-strong",
        className
      )}
    >
      <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2 font-medium">
        {label}
      </p>
      <p
        className={cn(
          "text-2xl font-bold tracking-tight",
          mono && "font-mono",
          statusColors[status]
        )}
      >
        {value}
      </p>
      {subvalue && (
        <p className="text-xs text-text-muted mt-1.5">{subvalue}</p>
      )}
    </div>
  );
}
