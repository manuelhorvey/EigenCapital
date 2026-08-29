import { cn } from "../../lib/utils";
import type { ReactNode } from "react";

interface MetricProps {
  label: string;
  value: ReactNode;
  subvalue?: string;
  align?: "left" | "right";
  className?: string;
  /** Status affects value color */
  status?: "positive" | "negative" | "warning" | "neutral";
}

const statusColors = {
  positive: "text-success",
  negative: "text-danger",
  warning: "text-warning",
  neutral: "text-text-primary",
};

export default function Metric({ label, value, subvalue, align = "left", className, status = "neutral" }: MetricProps) {
  return (
    <div className={cn("min-w-0", align === "right" && "text-right", className)}>
      <p className="text-[10px] font-medium text-text-muted uppercase tracking-wider truncate">
        {label}
      </p>
      <p className={cn("text-base font-semibold ec-num mt-0.5 leading-tight", statusColors[status])}>
        {value}
      </p>
      {subvalue && (
        <p className="text-[11px] text-text-muted mt-0.5 truncate">{subvalue}</p>
      )}
    </div>
  );
}

export function MetricRow({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center justify-between py-1.5", className)}>
      <span className="text-xs text-text-secondary">{label}</span>
      <span className="text-xs font-medium ec-num text-text-primary">{value}</span>
    </div>
  );
}
