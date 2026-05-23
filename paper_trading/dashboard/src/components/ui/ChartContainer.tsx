import type { ReactNode } from 'react'
import Panel from './Panel'
import SectionHeader from './SectionHeader'
import EmptyState from './EmptyState'
import { Skeleton } from './Skeleton'

interface ChartContainerProps {
  title: string
  accent?: 'emerald' | 'blue' | 'purple' | 'amber'
  meta?: ReactNode
  toolbar?: ReactNode
  children: ReactNode
  height?: string
  isPending?: boolean
  isEmpty?: boolean
  emptyMessage?: string
  className?: string
}

export default function ChartContainer({
  title,
  accent = 'emerald',
  meta,
  toolbar,
  children,
  height = 'h-64',
  isPending,
  isEmpty,
  emptyMessage = 'Waiting for data…',
  className = '',
}: ChartContainerProps) {
  return (
    <Panel className={`p-4 ${className}`}>
      <SectionHeader title={title} accent={accent} meta={meta} />
      {toolbar}
      {isPending ? (
        <Skeleton className={`${height} w-full rounded-md`} />
      ) : isEmpty ? (
        <EmptyState message={emptyMessage} compact />
      ) : (
        <div className={`${height} w-full min-w-0 chart-surface rounded-md`}>{children}</div>
      )}
    </Panel>
  )
}
