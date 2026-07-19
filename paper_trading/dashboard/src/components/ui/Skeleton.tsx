import Panel from './Panel'

type SkeletonVariant = 'default' | 'metric-card' | 'table' | 'page'

interface SkeletonProps {
  className?: string
  shimmer?: boolean
  variant?: SkeletonVariant
  count?: number
  rows?: number
}

function Skeleton({ className = '', shimmer = false, variant = 'default', count, rows }: SkeletonProps) {
  if (variant === 'metric-card') {
    const c = count ?? 4
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {Array.from({ length: c }).map((_, i) => (
          <div key={i} className="bg-panel border border-default rounded-lg p-3 sm:p-3.5">
            <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} h-2.5 w-16 mb-3 rounded`} aria-hidden />
            <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} h-7 w-24 mb-2 rounded`} aria-hidden />
            <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} h-2.5 w-20 rounded`} aria-hidden />
          </div>
        ))}
      </div>
    )
  }

  if (variant === 'table') {
    const r = rows ?? 5
    return (
      <Panel className="p-4">
        <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} h-4 w-28 mb-4 rounded`} aria-hidden />
        <div className="space-y-2">
          {Array.from({ length: r }).map((_, i) => (
            <div key={i} className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} h-6 w-full rounded`} aria-hidden />
          ))}
        </div>
      </Panel>
    )
  }

  return <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} ${className}`} aria-hidden />
}

export function MetricCardSkeleton({ count }: { count?: number }) {
  return <Skeleton variant="metric-card" count={count} shimmer />
}
MetricCardSkeleton.displayName = 'MetricCardSkeleton'

export function TableSkeleton({ rows }: { rows?: number }) {
  return <Skeleton variant="table" rows={rows} shimmer />
}
TableSkeleton.displayName = 'TableSkeleton'

export { Skeleton }
export default Skeleton