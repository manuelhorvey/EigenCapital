import type { ReactNode } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface MetricCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  valueClassName?: string
  accent?: 'emerald' | 'blue' | 'amber' | 'neutral'
  trend?: 'up' | 'down' | 'neutral'
  className?: string
}

const accentRing: Record<NonNullable<MetricCardProps['accent']>, string> = {
  emerald: 'bg-accent-emerald/30',
  blue: 'bg-accent-blue/30',
  amber: 'bg-accent-amber/30',
  neutral: 'bg-gov-init/40',
}

const trendIcon: Record<string, ReactNode> = {
  up: <TrendingUp className="w-3 h-3 text-gov-green" strokeWidth={2} />,
  down: <TrendingDown className="w-3 h-3 text-gov-red" strokeWidth={2} />,
  neutral: <Minus className="w-3 h-3 text-tertiary" strokeWidth={2} />,
}

export default function MetricCard({
  label,
  value,
  sub,
  valueClassName = 'text-primary',
  accent = 'emerald',
  trend,
  className = '',
}: MetricCardProps) {
  return (
    <div className={`metric-card group ${className}`}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className={`w-0.5 h-3 rounded-full ${accentRing[accent]}`} />
          <span className="metric-label">{label}</span>
        </div>
        {trend && trendIcon[trend]}
      </div>
      <div className={`text-xl font-semibold tracking-tight metric-value ${valueClassName}`}>
        {value}
      </div>
      {sub != null && <div className="text-2xs text-tertiary mt-1 font-mono tabular-nums">{sub}</div>}
    </div>
  )
}
