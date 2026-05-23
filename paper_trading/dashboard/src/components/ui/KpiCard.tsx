import type { ReactNode } from 'react'

interface KpiCardProps {
  label: string
  value: string
  color?: string
  trend?: 'up' | 'down' | 'neutral'
  className?: string
}

export default function KpiCard({ label, value, color = 'text-secondary', trend, className = '' }: KpiCardProps) {
  return (
    <div className={`bg-panel/60 border border-default rounded-lg p-3 text-center ${className}`}>
      <div className="text-2xs text-tertiary uppercase tracking-wider mb-1 font-medium">{label}</div>
      <div className={`text-sm font-bold tabular-nums tracking-tight ${color}`}>
        {value}
      </div>
    </div>
  )
}
