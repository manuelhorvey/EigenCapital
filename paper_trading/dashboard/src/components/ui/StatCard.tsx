import type { ReactNode } from 'react'
import { Skeleton } from './Skeleton'
import { semanticColor } from './semantic'

type StatCardVariant = 'default' | 'compact' | 'kpi'

interface StatCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  variant?: StatCardVariant
  /** CSS color used for accent line + value (default variant only) */
  accent?: string
  /** Tailwind color classes for the value (overrides accent) */
  valueClassName?: string
  /** Leading icon for hero cards (default variant) */
  icon?: ReactNode
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

const valueSize = {
  sm: 'text-sm sm:text-base',
  md: 'text-xl sm:text-2xl',
} as const

export default function StatCard({
  label,
  value,
  sub,
  variant = 'default',
  accent,
  valueClassName,
  icon,
  loading = false,
  size = 'md',
  className = '',
  animate = false,
}: StatCardProps) {
  if (loading) return <LoadingSkeleton variant={variant} />

  const resolvedAccent = accent ? semanticColor(accent) : undefined

  if (variant === 'kpi') {
    return (
      <div className={`bg-surface border border-default rounded-xl p-3 shadow-panel relative overflow-hidden group transition-all duration-200 hover:border-strong hover:shadow-card ${animate ? 'animate-fade-in' : ''} ${className}`}>
        {resolvedAccent && (
          <span
            className="absolute top-0 left-0 right-0 h-0.5 rounded-t-xl pointer-events-none transition-all duration-300 group-hover:h-1"
            style={{ backgroundColor: resolvedAccent }}
          />
        )}
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-[10px] text-tertiary font-medium truncate tracking-wider uppercase">{label}</span>
        </div>
        <div
          className={`text-sm font-bold tabular-nums tracking-tight transition-colors duration-200 ${valueClassName ?? (resolvedAccent ? '' : 'text-primary')}`}
          style={resolvedAccent && !valueClassName ? { color: resolvedAccent } : undefined}
        >
          {value}
        </div>
      </div>
    )
  }

  if (variant === 'compact') {
    return (
      <div className={`bg-surface border border-default rounded-xl p-3 shadow-panel transition-all duration-200 hover:border-strong hover:shadow-card group ${animate ? 'animate-fade-in' : ''} ${className}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-medium text-tertiary uppercase tracking-wider">{label}</span>
          <div
            className={`text-sm font-semibold tracking-tight font-mono tabular-nums transition-colors ${valueClassName ?? (resolvedAccent ? '' : 'text-primary')}`}
            style={resolvedAccent && !valueClassName ? { color: resolvedAccent } : undefined}
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
      'bg-surface border border-default rounded-xl p-3 sm:p-4',
      'transition-all duration-200 ease-out',
      'hover:border-strong hover:-translate-y-0.5 hover:shadow-card',
      'group relative overflow-hidden shadow-panel',
      animate ? 'animate-slide-up' : '',
      className,
    ].join(' ')}>
      {/* Subtle top gradient line */}
      {resolvedAccent && (
        <span
          className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity duration-300"
          style={{ background: `linear-gradient(90deg, ${resolvedAccent}, transparent)` }}
        />
      )}

      {/* Accent dot on hover */}
      {resolvedAccent && (
        <span
          className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full opacity-0 group-hover:opacity-40 transition-opacity duration-300"
          style={{ backgroundColor: resolvedAccent }}
        />
      )}

      {icon != null ? (
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-panel flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform duration-200">
            {icon}
          </div>
          <div className="min-w-0 flex-1">
            <span className={[
              'text-[11px] font-medium uppercase tracking-wider transition-colors duration-200 block truncate',
              'group-hover:text-secondary',
              'text-tertiary',
            ].join(' ')}>
              {label}
            </span>
            <div
              className={[
                `${valueSize[size]} font-semibold tracking-tight font-mono tabular-nums mt-0.5 leading-tight`,
                'transition-colors duration-200',
                valueClassName ?? (resolvedAccent ? '' : 'text-primary'),
              ].join(' ')}
              style={resolvedAccent && !valueClassName ? { color: resolvedAccent } : undefined}
            >
              {value}
            </div>
          </div>
        </div>
      ) : (
        <>
          <span className={[
            'text-[11px] font-medium uppercase tracking-wider transition-colors duration-200',
            'group-hover:text-secondary',
            'text-tertiary',
          ].join(' ')}>
            {label}
          </span>
          <div
            className={[
              `${valueSize[size]} font-semibold tracking-tight font-mono tabular-nums mt-1 leading-tight`,
              'transition-colors duration-200',
              valueClassName ?? (resolvedAccent ? '' : 'text-primary'),
            ].join(' ')}
            style={resolvedAccent && !valueClassName ? { color: resolvedAccent } : undefined}
          >
            {value}
          </div>
        </>
      )}
      {sub != null && (
        <p className="text-[11px] text-tertiary font-mono tabular-nums mt-1 opacity-80 group-hover:opacity-100 transition-opacity duration-200">{sub}</p>
      )}
    </div>
  )
}
