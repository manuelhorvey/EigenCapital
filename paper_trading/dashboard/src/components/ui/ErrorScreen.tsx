import { AlertTriangle, RefreshCw } from 'lucide-react'
import { signalText } from './governance'
import Button from './Button'

interface ErrorScreenProps {
  title?: string
  message?: string
  onRetry?: () => void
}

/** Full-screen error state with title, message, and retry button. Falls back to engine-not-reachable defaults. */
export default function ErrorScreen({
  title = 'Engine Not Reachable',
  message = 'Make sure the paper trading engine is running on port 5000',
  onRetry = () => window.location.reload(),
}: ErrorScreenProps) {
  return (
    <div className="min-h-screen bg-app flex flex-col items-center justify-center gap-5 px-6 animate-fade-in">
      <div className="w-12 h-12 rounded panel border-signal-warn/30 flex items-center justify-center">
        <AlertTriangle className={`w-6 h-6 ${signalText.WARN}`} strokeWidth={1.5} />
      </div>
      <div className="text-center max-w-md">
        <h2 className="text-primary text-lg font-semibold tracking-tight">{title}</h2>
        <p className="text-tertiary text-sm mt-1.5">{message}</p>
      </div>
      <Button variant="primary" onClick={onRetry} icon={<RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />}>
        Retry connection
      </Button>
    </div>
  )
}
