import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { cn } from "../lib/utils";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className={cn("flex flex-col items-center justify-center py-12 px-6 text-center", "bg-danger-subtle border border-danger/15 rounded-lg")}>
          <div className="w-10 h-10 rounded-lg bg-danger/10 flex items-center justify-center mb-3">
            <AlertTriangle className="w-5 h-5 text-danger" />
          </div>
          <h3 className="text-sm font-medium text-text-primary mb-1">Widget failed to load</h3>
          <p className="text-xs text-text-muted max-w-xs leading-relaxed mb-4">
            This section encountered an error. The rest of the dashboard is still operational.
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-3 py-1.5 text-xs font-medium text-text-secondary bg-surface-overlay border border-border-primary rounded-md hover:bg-surface-hover transition-colors"
          >
            <RefreshCw className="w-3 h-3 inline mr-1" />
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}