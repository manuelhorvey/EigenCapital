import type { ReactNode } from "react";
import { cn } from "../../lib/utils";
import { AlertTriangle } from "lucide-react";

interface ErrorStateProps {
  title?: string;
  message: string;
  timestamp?: string;
  subsystem?: string;
  retryAction?: () => void;
  className?: string;
  icon?: ReactNode;
}

export default function ErrorState({
  title = "Data temporarily unavailable",
  message,
  timestamp,
  subsystem,
  retryAction,
  className,
  icon,
}: ErrorStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-12 px-6 text-center", className)}>
      <div className="w-10 h-10 rounded-lg bg-danger-subtle flex items-center justify-center mb-3">
        {icon || <AlertTriangle className="w-5 h-5 text-danger" />}
      </div>
      <h3 className="text-sm font-medium text-text-primary mb-1">{title}</h3>
      <p className="text-xs text-text-muted max-w-xs leading-relaxed mb-3">{message}</p>
      <div className="flex items-center gap-3 text-[10px] text-text-muted">
        {subsystem && <span className="ec-badge bg-surface-overlay text-text-muted">{subsystem}</span>}
        {timestamp && <span>{timestamp}</span>}
      </div>
      {retryAction && (
        <button
          onClick={retryAction}
          className="mt-4 px-3 py-1.5 text-xs font-medium text-text-secondary bg-surface-overlay border border-border-primary rounded-md hover:bg-surface-hover transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
