import type { ReactNode } from 'react'
import { Skeleton } from './Skeleton'

type StatCardVariant = 'default' | 'compact' | 'kpi'

interface StatCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  variant?: StatCardVariant
  accent?: string
  loading?: boolean
  size?: 'sm' | 'md'
  className?: string
}

function LoadingSkeleton({ variant }: { variant: StatCardVariant }) {
  if (variant === 'kpi') {
    return (
      <div className="bg-panel/60 border border-default rounded-lg p-2.5">
        <Skeleton className="h-3 w-16 mb-1.5 rounded" />
        <Skeleton className="h-4 w-12 rounded" />
      </div>
    )
  }
  return (
    <div className="bg-panel border border-default rounded-lg p-3 sm:p-3.5">
      <Skeleton className="h-2.5 w-16 mb-2 rounded" />
      <Skeleton className="h-6 w-20 mb-1.5 rounded" />
      <Skeleton className="h-2.5 w-14 rounded" />
    </div>
  )
}

export default function StatCard({
  label,
  value,
  sub,
  variant = 'default',
  accent,
  loading = false,
  className = '',
}: StatCardProps) {
  if (loading) return <LoadingSkeleton variant={variant} />

  if (variant === 'kpi') {
    return (
      <div className={`bg-panel/60 border border-default rounded-lg p-2.5 relative overflow-hidden ${className}`}>
        {accent && (
          <span
            className="absolute top-0 left-0 right-0 h-0.5 rounded-t-lg pointer-events-none"
            style={{ backgroundColor: accent }}
          />
        )}
        <div className="flex items-center justify-between gap-2 mb-0.5">
          <span className="text-[10px] text-tertiary font-medium truncate">{label}</span>
        </div>
        <div className={`text-sm font-bold tabular-nums tracking-tight ${accent ? '' : 'text-secondary'}`}
          style={accent ? { color: accent } : undefined}
        >
          {value}
        </div>
      </div>
    )
  }

  return (
    <div className={`bg-panel border border-default rounded-lg p-3 sm:p-3.5 transition-colors duration-200 hover:border-strong ${className}`}>
      <span className="text-[11px] font-medium text-tertiary uppercase tracking-wider">{label}</span>
      <div className="text-xl font-semibold tracking-tight font-mono tabular-nums mt-1 text-primary">
        {value}
      </div>
      {sub != null && (
        <p className="text-[11px] text-tertiary font-mono tabular-nums mt-1">{sub}</p>
      )}
    </div>
  )
}
