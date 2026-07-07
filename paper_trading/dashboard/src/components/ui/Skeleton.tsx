import Panel from './Panel'

interface SkeletonProps {
  className?: string
  /** When true, renders with a sliding gradient bg; default uses simple pulse */
  shimmer?: boolean
}

/** Skeleton placeholder for loading content. @param shimmer - enables sliding gradient animation instead of default pulse. */
export function Skeleton({ className = '', shimmer = false }: SkeletonProps) {
  return <div className={`${shimmer ? 'skeleton-shimmer' : 'skeleton'} ${className}`} aria-hidden />
}

/** Row of metric card skeletons for dashboard stat loading. @param count - number of skeleton cards to render (default 4). */
export function MetricCardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-panel border border-default rounded-lg p-3 sm:p-3.5">
          <Skeleton className="h-2.5 w-16 mb-3 rounded" shimmer />
          <Skeleton className="h-7 w-24 mb-2 rounded" shimmer />
          <Skeleton className="h-2.5 w-20 rounded" shimmer />
        </div>
      ))}
    </div>
  )
}

/** Table-shaped skeleton with header and row placeholders. @param rows - number of row skeletons to render (default 5). */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <Panel className="p-4">
      <Skeleton className="h-4 w-28 mb-4 rounded" shimmer />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-full rounded" shimmer />
        ))}
      </div>
    </Panel>
  )
}
