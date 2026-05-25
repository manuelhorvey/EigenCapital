import type { ReactNode } from 'react'

interface CompactMetricProps {
  label: string
  value: ReactNode
  className?: string
}

export default function CompactMetric({ label, value, className = '' }: CompactMetricProps) {
  return (
    <div className={`flex items-center justify-between gap-2 py-0.5 ${className}`}>
      <span className="text-[10px] text-tertiary font-medium truncate">{label}</span>
      <span className="text-[11px] text-primary font-mono tabular-nums font-semibold shrink-0">{value}</span>
    </div>
  )
}
