import type { ReactNode } from 'react'

interface KpiCardProps {
  label: string
  value: string
  color?: string
  trend?: 'up' | 'down' | 'neutral'
  icon?: ReactNode
  className?: string
}

export default function KpiCard({
  label,
  value,
  color = 'text-secondary',
  trend,
  icon,
  className = '',
}: KpiCardProps) {
  return (
    <div className={`bg-panel/60 border border-default rounded-lg p-2.5 ${className}`}>
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <span className="text-[10px] text-tertiary font-medium truncate">{label}</span>
        {icon && <span className="shrink-0 text-muted">{icon}</span>}
      </div>
      <div className={`text-sm font-bold tabular-nums tracking-tight ${color}`}>{value}</div>
    </div>
  )
}
