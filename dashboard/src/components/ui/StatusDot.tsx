import { cn } from "../../lib/utils";

type DotLevel = "green" | "yellow" | "red" | "blue" | "purple" | "gray";

const levelAriaLabels: Record<DotLevel, string> = {
  green: "healthy",
  yellow: "warning",
  red: "critical",
  blue: "informational",
  purple: "diagnostic",
  gray: "unknown",
};

const dotStyles: Record<DotLevel, string> = {
  green: "bg-success",
  yellow: "bg-warning",
  red: "bg-danger",
  blue: "bg-info",
  purple: "bg-purple",
  gray: "bg-text-muted",
};

const textStyles: Record<DotLevel, string> = {
  green: "text-success",
  yellow: "text-warning",
  red: "text-danger",
  blue: "text-info",
  purple: "text-purple",
  gray: "text-text-muted",
};

const sizes = { xs: 5, sm: 6, md: 8 };

interface StatusDotProps {
  level: DotLevel;
  label?: string;
  pulse?: boolean;
  size?: "xs" | "sm" | "md";
  className?: string;
}

export default function StatusDot({ level, label, pulse = false, size = "sm", className }: StatusDotProps) {
  const px = sizes[size];
  return (
    <div className={cn("inline-flex items-center gap-1.5", textStyles[level], className)}>
      <span
        className={cn("shrink-0 rounded-full", dotStyles[level], pulse && "ec-pulse")}
        style={{ width: px, height: px }}
        role="status"
        aria-label={levelAriaLabels[level]}
      />
      {label && <span className="text-xs font-medium">{label}</span>}
    </div>
  );
}
