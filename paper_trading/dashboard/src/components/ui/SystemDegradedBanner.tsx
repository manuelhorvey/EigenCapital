import { AlertTriangle, Activity } from 'lucide-react'
import type { SystemIntegrity } from '../../hooks/useSystemIntegrity'

interface SystemDegradedBannerProps {
  integrity: SystemIntegrity
  onDismiss?: () => void
  className?: string
}

/** Top-of-page banner alerting when system integrity is degraded or broken. Returns null when healthy. */
export function SystemDegradedBanner({ integrity, onDismiss, className = '' }: SystemDegradedBannerProps) {
  if (integrity.isHealthy) return null

  return (
    <div
      className={`flex items-center gap-3 px-4 py-2 text-xs font-medium border-b ${className} ${
        integrity.isBroken
          ? 'bg-signal-short-muted border-signal-short/20 text-signal-short'
          : 'bg-signal-warn-muted border-signal-warn/20 text-signal-warn'
      }`}
      role="alert"
    >
      {integrity.isBroken
        ? <AlertTriangle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
        : <Activity className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
      }
      <span className="flex-1">
        {integrity.label === 'partial_failure' && 'System snapshot unavailable — some data may be missing'}
        {integrity.label === 'degraded' && integrity.hasStaleLive && (
          `Live data source degraded (${integrity.staleSources.join(', ')}) — data may lag`
        )}
        {integrity.label === 'degraded' && !integrity.hasStaleLive && 'System operating in degraded mode'}
        {integrity.label === 'no_data' && 'Waiting for system data...'}
      </span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 px-2 py-0.5 rounded border border-current/30 hover:bg-current/10 transition-colors"
          aria-label="Dismiss banner"
        >
          Dismiss
        </button>
      )}
    </div>
  )
}
