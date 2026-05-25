import { AlertTriangle, RefreshCw } from 'lucide-react'

interface PanelFallbackProps {
  title: string
  error?: Error
}

export default function PanelFallback({ title, error }: PanelFallbackProps) {
  return (
    <div className="panel rounded-lg p-4">
      <div className="flex flex-col items-center justify-center py-6 gap-2">
        <AlertTriangle className="w-4 h-4 text-gov-yellow" strokeWidth={1.5} />
        <span className="text-xs text-tertiary font-medium">{title} — Error</span>
        {error && <span className="text-2xs text-muted font-mono max-w-xs text-center">{error.message}</span>}
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="flex items-center gap-1 mt-1 px-2 py-1 rounded-md border border-default hover:border-strong text-2xs text-secondary hover:text-primary transition-colors"
        >
          <RefreshCw className="w-2.5 h-2.5" strokeWidth={2} />
          Reload
        </button>
      </div>
    </div>
  )
}
