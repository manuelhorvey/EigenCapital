import { AlertTriangle, RefreshCw } from 'lucide-react'
import { signalText } from './governance'

interface PanelFallbackProps {
  title: string
  error?: Error
  className?: string
  /** Callback for the retry button. Defaults to `window.location.reload()`. */
  onRetry?: () => void
}

/** Error fallback card shown when a panel's content fails to render. Displays error message and reload button. */
export default function PanelFallback({ title, error, className = '', onRetry }: PanelFallbackProps) {
  const handleRetry = onRetry ?? (() => window.location.reload())
  return (
    <div className={`panel rounded-lg p-4 ${className}`}>
      <div className="flex flex-col items-center justify-center py-6 gap-2">
        <AlertTriangle className={`w-4 h-4 ${signalText.WARN}`} strokeWidth={1.5} />
        <span className="text-xs text-tertiary font-medium">{title} — Error</span>
        {error && <span className="text-2xs text-muted font-mono max-w-xs text-center">{error.message}</span>}
        <button
          type="button"
          onClick={handleRetry}
          className="flex items-center gap-1 mt-1 px-2 py-1 rounded-md border border-default hover:border-strong text-2xs text-secondary hover:text-primary transition-colors"
        >
          <RefreshCw className="w-2.5 h-2.5" strokeWidth={2} />
          Reload
        </button>
      </div>
    </div>
  )
}
