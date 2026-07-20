import type { ReactNode } from 'react'
import EmptyState from './EmptyState'
import Skeleton from './Skeleton'

interface DataPanelProps {
  loading?: boolean
  error?: string | null
  empty?: boolean
  emptyMessage?: string
  emptyHint?: string
  filtered?: boolean
  children?: ReactNode
  className?: string
}

export default function DataPanel({
  loading, error, empty = false,
  emptyMessage = 'No data', emptyHint, filtered = false,
  children, className = '',
}: DataPanelProps) {
  if (loading) {
    return <div className={className}><Skeleton className="h-32 rounded-lg" shimmer /></div>
  }

  if (error) {
    return (
      <div className={className}>
        <EmptyState
          message={error}
          icon="warning"
          compact
        />
      </div>
    )
  }

  if (empty) {
    return (
      <div className={className}>
        <EmptyState
          message={emptyMessage}
          hint={emptyHint}
          filtered={filtered}
          compact
        />
      </div>
    )
  }

  return <>{children}</>
}
