import { useState } from 'react'
import { X, AlertTriangle, AlertCircle, Info, Shield, Activity, ChevronDown, ChevronUp } from 'lucide-react'
import type { Alert } from '../../hooks/useMonitorAlerts'
import { dismissAlert } from '../../hooks/useMonitorAlerts'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import Badge from '../ui/Badge'

interface AlertFeedProps {
  alerts: Alert[]
}

const DEFAULT_MAX = 10

const severityConfig = {
  critical: { icon: AlertCircle, color: 'text-signal-short', bg: 'bg-signal-short-muted', border: 'border-signal-short/35' },
  warning: { icon: AlertTriangle, color: 'text-signal-warn', bg: 'bg-signal-warn-muted', border: 'border-signal-warn/35' },
  info: { icon: Info, color: 'text-signal-init', bg: 'bg-signal-init-muted', border: 'border-signal-init/35' },
}

const typeIcon = {
  health: Shield,
  halt: AlertCircle,
  governance: Shield,
  performance: Activity,
}

/** Live feed of active system alerts grouped by severity, with dismiss capability and show-more pagination.
 * @param {Alert[]} alerts - Array of alert objects to display */
export default function AlertFeed({ alerts }: AlertFeedProps) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [showAll, setShowAll] = useState(false)

  const visible = alerts.filter(a => !dismissed.has(a.id))
  const display = showAll ? visible : visible.slice(0, DEFAULT_MAX)
  const hasMore = visible.length > DEFAULT_MAX

  const handleDismiss = (id: string) => {
    setDismissed(prev => new Set([...prev, id]))
    dismissAlert(id)
  }

  if (visible.length === 0) return null

  return (
    <Panel padding="md">
      <SectionHeader
        title="Active Alerts"
        accent="amber"
        meta={
          <span className="text-[10px] text-tertiary font-mono bg-surface px-2 py-0.5 rounded border border-default">
            {visible.length} active
          </span>
        }
      />
      <div className="space-y-1.5" role="log" aria-live="polite" aria-label="Active alerts feed">
        {display.map(alert => {
          const sev = severityConfig[alert.severity]
          const TypeIcon = typeIcon[alert.type]
          const hasAssets = (alert.count ?? 1) > 1 && alert.assets && alert.assets.length > 1
          return (
            <div
              key={alert.id}
              className={`flex items-start gap-2 px-2.5 py-2 rounded-md border ${sev.bg} ${sev.border}`}
            >
              <TypeIcon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${sev.color}`} strokeWidth={2} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-medium text-primary">{alert.message}</p>
                  {hasAssets && (
                    <Badge variant={alert.severity === 'critical' ? 'error' : 'warning'} size="sm">
                      {alert.count}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={`text-[10px] font-semibold uppercase ${sev.color}`}>{alert.severity}</span>
                  <span className="text-[10px] text-tertiary font-mono">{alert.asset}</span>
                </div>
              </div>
              <button
                onClick={() => handleDismiss(alert.id)}
                className="p-0.5 rounded hover:bg-default/40 transition-colors shrink-0 mt-0.5"
                aria-label={`Dismiss alert: ${alert.message}`}
              >
                <X className="w-3 h-3 text-tertiary" strokeWidth={2} />
              </button>
            </div>
          )
        })}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="flex items-center gap-1 mx-auto mt-2 text-2xs font-medium text-tertiary hover:text-secondary transition-colors"
        >
          {showAll ? (
            <>Show fewer <ChevronUp className="w-3 h-3" strokeWidth={1.5} /></>
          ) : (
            <>Show all {visible.length} alerts <ChevronDown className="w-3 h-3" strokeWidth={1.5} /></>
          )}
        </button>
      )}
    </Panel>
  )
}
