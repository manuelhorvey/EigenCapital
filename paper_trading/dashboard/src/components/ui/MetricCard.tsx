import type { ReactNode } from 'react'

interface MetricCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  valueClassName?: string
  accent?: 'emerald' | 'blue' | 'amber' | 'neutral'
  className?: string
}

const accentRing: Record<NonNullable<MetricCardProps['accent']>, string> = {
  emerald: 'bg-accent-emerald/30',
  blue: 'bg-accent-blue/30',
  amber: 'bg-accent-amber/30',
  neutral: 'bg-gov-init/40',
}

export default function MetricCard({
  label,
  value,
  sub,
  valueClassName = 'text-primary',
  accent = 'emerald',
  className = '',
}: MetricCardProps) {
  return (
    <div className={`metric-card group ${className}`}>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-0.5 h-3 rounded-full ${accentRing[accent]}`} />
        <span className="metric-label">{label}</span>
      </div>
      <div className={`text-xl font-semibold tracking-tight metric-value ${valueClassName}`}>
        {value}
      </div>
      {sub != null && <div className="text-2xs text-tertiary mt-1 font-mono tabular-nums">{sub}</div>}
    </div>
  )
}
