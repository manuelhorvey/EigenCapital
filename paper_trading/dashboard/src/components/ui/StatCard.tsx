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
  /** Show subtle entrance animation */
  animate?: boolean
}

function LoadingSkeleton({ variant }: { variant: StatCardVariant }) {
  if (variant === 'kpi') {
    return (
      <div className="bg-panel/60 border border-default rounded-lg p-2.5">
        <Skeleton className="h-3 w-16 mb-1.5 rounded" shimmer />
        <Skeleton className="h-4 w-12 rounded" shimmer />
      </div>
    )
  }
  return (
    <div className="bg-panel border border-default rounded-lg p-3 sm:p-3.5">
      <Skeleton className="h-2.5 w-16 mb-2 rounded" shimmer />
      <Skeleton className="h-6 w-20 mb-1.5 rounded" shimmer />
      <Skeleton className="h-2.5 w-14 rounded" shimmer />
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
  animate = false,
}: StatCardProps) {
  if (loading) return <LoadingSkeleton variant={variant} />

  if (variant === 'kpi') {
    return (
      <div className={`bg-panel/60 border border-default rounded-lg p-2.5 relative overflow-hidden group ${animate ? 'animate-fade-in' : ''} ${className}`}>
        {accent && (
          <span
            className="absolute top-0 left-0 right-0 h-0.5 rounded-t-lg pointer-events-none transition-all duration-300 group-hover:h-1"
            style={{ backgroundColor: accent }}
          />
        )}
        <div className="flex items-center justify-between gap-2 mb-0.5">
          <span className="text-[10px] text-tertiary font-medium truncate tracking-wider uppercase">{label}</span>
        </div>
        <div className={`text-sm font-bold tabular-nums tracking-tight transition-colors duration-200 ${accent ? '' : 'text-secondary'}`}
          style={accent ? { color: accent } : undefined}
        >
          {value}
        </div>
      </div>
    )
  }

  if (variant === 'compact') {
    return (
      <div className={`bg-panel/60 border border-default rounded-lg p-3 transition-all duration-200 hover:border-strong group ${animate ? 'animate-fade-in' : ''} ${className}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-medium text-tertiary uppercase tracking-wider">{label}</span>
          <div className={`text-sm font-semibold tracking-tight font-mono tabular-nums transition-colors ${accent ? '' : 'text-primary'}`}
            style={accent ? { color: accent } : undefined}
          >
            {value}
          </div>
        </div>
        {sub != null && (
          <p className="text-[10px] text-tertiary font-mono tabular-nums mt-0.5">{sub}</p>
        )}
      </div>
    )
  }

  return (
    <div className={[
      'bg-panel border border-default rounded-lg p-3 sm:p-3.5',
      'transition-all duration-200 ease-out',
      'hover:border-strong hover:-translate-y-0.5 hover:shadow-card',
      'group relative overflow-hidden',
      animate ? 'animate-slide-up' : '',
      className,
    ].join(' ')}>
      {/* Subtle top gradient line */}
      {accent && (
        <span
          className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity duration-300"
          style={{ background: `linear-gradient(90deg, ${accent}, transparent)` }}
        />
      )}

      {/* Accent dot on hover */}
      {accent && (
        <span
          className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full opacity-0 group-hover:opacity-40 transition-opacity duration-300"
          style={{ backgroundColor: accent }}
        />
      )}

      <span className={[
        'text-[11px] font-medium uppercase tracking-wider transition-colors duration-200',
        'group-hover:text-secondary',
        accent ? 'text-tertiary' : 'text-tertiary',
      ].join(' ')}>
        {label}
      </span>
      <div className={[
        'text-xl sm:text-2xl font-semibold tracking-tight font-mono tabular-nums mt-1 leading-tight',
        'transition-colors duration-200',
        accent ? '' : 'text-primary',
      ].join(' ')}
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
      {sub != null && (
        <p className="text-[11px] text-tertiary font-mono tabular-nums mt-1 opacity-80 group-hover:opacity-100 transition-opacity duration-200">{sub}</p>
      )}
    </div>
  )
}
