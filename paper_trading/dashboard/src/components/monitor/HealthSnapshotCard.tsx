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
    case 'healthy': return 'text-gov-green'
    case 'degraded': return 'text-gov-yellow'
    case 'critical': return 'text-gov-red'
    default: return 'text-tertiary'
  }
}

function statusBg(status: HealthSnapshotCardProps['status']): string {
  switch (status) {
    case 'healthy': return 'bg-gov-green'
    case 'degraded': return 'bg-gov-yellow'
    case 'critical': return 'bg-gov-red'
    default: return 'bg-tertiary'
  }
}

export default function HealthSnapshotCard({
  title, value, status, trend, change, icon,
}: HealthSnapshotCardProps) {
  return (
    <div
      className="bg-panel border border-default rounded-lg px-3 py-2.5"
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
            trend === 'up' ? 'text-gov-green' : trend === 'down' ? 'text-gov-red' : 'text-tertiary'
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
