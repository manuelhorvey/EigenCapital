import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description: string;
  className?: string;
}

export default function EmptyState({ icon, title, description, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-12 px-6 text-center", className)}>
      {icon && (
        <div className="w-10 h-10 rounded-lg bg-surface-overlay flex items-center justify-center mb-3 text-text-muted">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-medium text-text-primary mb-1">{title}</h3>
      <p className="text-xs text-text-muted max-w-xs leading-relaxed">{description}</p>
    </div>
  );
}
