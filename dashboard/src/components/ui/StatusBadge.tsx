import { cn } from "../../lib/utils";

type BadgeVariant = "success" | "warning" | "danger" | "info" | "purple" | "neutral";

const variantAriaLabels: Record<BadgeVariant, string> = {
  success: "success",
  warning: "warning",
  danger: "critical",
  info: "informational",
  purple: "diagnostic",
  neutral: "neutral",
};

const variantStyles: Record<BadgeVariant, string> = {
  success: "bg-success-subtle text-success border border-success/15",
  warning: "bg-warning-subtle text-warning border border-warning/15",
  danger: "bg-danger-subtle text-danger border border-danger/15",
  info: "bg-info-subtle text-info border border-info/15",
  purple: "bg-purple-subtle text-purple border border-purple/15",
  neutral: "bg-surface-overlay text-text-secondary border border-border-primary",
};

interface StatusBadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  size?: "sm" | "md";
  pulse?: boolean;
}

export default function StatusBadge({ variant, children, size = "sm", pulse = false }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "ec-badge",
        size === "sm" ? "text-[10px] px-1.5 py-0.5" : "text-xs px-2 py-0.5",
        variantStyles[variant],
        pulse && "ec-pulse"
      )}
      role="status"
      aria-label={variantAriaLabels[variant]}
    >
      {children}
    </span>
  );
}
