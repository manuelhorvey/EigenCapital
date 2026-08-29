import { cn } from "../../lib/utils";
import type { ReactNode } from "react";

interface PanelProps {
  children: ReactNode;
  className?: string;
  /** Subtle accent left border */
  accent?: "success" | "warning" | "danger" | "info" | "purple";
  noPadding?: boolean;
}

const accentBorders = {
  success: "border-l-2 border-l-success",
  warning: "border-l-2 border-l-warning",
  danger: "border-l-2 border-l-danger",
  info: "border-l-2 border-l-info",
  purple: "border-l-2 border-l-purple",
};

export default function Panel({ children, className, accent, noPadding = false }: PanelProps) {
  return (
    <div
      className={cn(
        "ec-panel",
        accent && accentBorders[accent],
        className
      )}
    >
      {noPadding ? children : <div className="p-4">{children}</div>}
    </div>
  );
}

export function PanelHeader({
  children,
  className,
  action,
}: {
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <div className={cn("ec-panel-header", className)}>
      {children}
      {action}
    </div>
  );
}

export function PanelContent({
  children,
  className,
  noPadding = false,
}: {
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
}) {
  return (
    <div className={cn(noPadding ? "" : "p-4", className)}>
      {children}
    </div>
  );
}
