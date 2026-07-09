import { useNavigate } from 'react-router-dom'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'
import Button from '../components/ui/Button'

/**
 * 500 Server Error page.
 * Shown when the engine fails to respond or returns an unrecoverable error.
 */
export default function ServerErrorPage() {
  const navigate = useNavigate()

  const handleRetry = () => {
    window.location.reload()
  }

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-6 px-6 animate-fade-in">
      <div className="w-16 h-16 rounded-xl panel border-gov-red/30 flex items-center justify-center">
        <AlertTriangle className="w-8 h-8 text-gov-red/60" strokeWidth={1.25} />
      </div>

      <div className="text-center max-w-md">
        <h1 className="text-3xl font-bold text-primary tracking-tight">500</h1>
        <p className="text-sm text-tertiary mt-2 leading-relaxed">
          The engine encountered an internal error and couldn't complete your request.
          This is usually temporary — try reloading the page.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          onClick={handleRetry}
          icon={<RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />}
        >
          Reload page
        </Button>
        <Button
          variant="secondary"
          onClick={() => navigate('/')}
          icon={<Home className="w-3.5 h-3.5" strokeWidth={2} />}
        >
          Dashboard
        </Button>
      </div>

      <details className="mt-4 max-w-md">
        <summary className="text-2xs text-tertiary cursor-pointer hover:text-secondary transition-colors">
          Troubleshooting steps
        </summary>
        <ol className="mt-3 space-y-2 text-2xs text-tertiary leading-relaxed list-decimal list-inside">
          <li>Check that the paper trading engine is running on port 5000</li>
          <li>Verify the MT5 bridge is connected (Wine process)</li>
          <li>Check the engine logs for stack traces</li>
          <li>Restart the engine: <code className="font-mono text-secondary">./monitor_all</code></li>
          <li>If the problem persists, check <code className="font-mono text-secondary">data/live/state.json</code> for corruption</li>
        </ol>
      </details>
    </div>
  )
}
