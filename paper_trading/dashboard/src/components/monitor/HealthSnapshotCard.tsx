import { TrendingUp, TrendingDown } from 'lucide-react'

interface HealthSnapshotCardProps {
  title: string
  value?: string
  status?: 'healthy' | 'degraded' | 'critical' | 'pending'
  trend?: 'up' | 'down' | 'stable'
  change?: string
  icon?: React.ReactNode
}

function statusColor(status: HealthSnapshotCardProps['status']): string {
  switch (status) {
    case 'healthy': return 'text-signal-long'
    case 'degraded': return 'text-signal-warn'
    case 'critical': return 'text-signal-short'
    default: return 'text-tertiary'
  }
}

function statusBg(status: HealthSnapshotCardProps['status']): string {
  switch (status) {
    case 'healthy': return 'bg-signal-long'
    case 'degraded': return 'bg-signal-warn'
    case 'critical': return 'bg-signal-short'
    default: return 'bg-tertiary'
  }
}

function statusBgMuted(status: HealthSnapshotCardProps['status']): string {
  switch (status) {
    case 'healthy': return 'bg-signal-long-muted2'
    case 'degraded': return 'bg-signal-warn-muted2'
    case 'critical': return 'bg-signal-short-muted2'
    default: return ''
  }
}

/** Compact card displaying a single health snapshot metric with status indicator, optional trend arrow, and change text.
 * @param {string} title - Metric label
 * @param {string} [value] - Metric value
 * @param {'healthy'|'degraded'|'critical'|'pending'} [status] - Health status tier
 * @param {'up'|'down'|'stable'} [trend] - Direction of change
 * @param {string} [change] - Formatted change text
 * @param {React.ReactNode} [icon] - Optional icon element */
export default function HealthSnapshotCard({
  title, value, status, trend, change, icon,
}: HealthSnapshotCardProps) {
  return (
    <div
      className={`bg-panel border border-default rounded-lg px-3 py-2.5 transition-all duration-200 hover:border-strong ${status ? statusBgMuted(status) : ''}`}
      role="status"
      aria-label={`${title}: ${value ?? '—'} — ${status ?? 'unknown'}`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-2xs font-medium text-tertiary uppercase tracking-wider">
          {title}
        </span>
        {icon && <span className="text-tertiary">{icon}</span>}
      </div>

      <div className="flex items-center gap-2">
        {status && (
          <span className={`w-2 h-2 rounded-full shrink-0 ${statusBg(status)}`} />
        )}
        {value && (
          <span className={`text-sm font-bold font-mono tabular-nums ${status ? statusColor(status) : 'text-primary'}`}>
            {value}
          </span>
        )}
        {trend && (
          <span className={`inline-flex items-center gap-0.5 text-[10px] font-medium ${
            trend === 'up' ? 'text-signal-long' : trend === 'down' ? 'text-signal-short' : 'text-tertiary'
          }`}>
            {trend === 'up' ? <TrendingUp className="w-2.5 h-2.5" strokeWidth={2.5} /> : null}
            {trend === 'down' ? <TrendingDown className="w-2.5 h-2.5" strokeWidth={2.5} /> : null}
            {change}
          </span>
        )}
      </div>
    </div>
  )
}
