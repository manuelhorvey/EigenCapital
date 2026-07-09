import type { ReactNode } from 'react'
import Panel from './Panel'

interface PageShellProps {
  isPending: boolean
  isError: boolean
  error: Error | null
  hasData: boolean
  skeleton: ReactNode
  children: ReactNode
}

/** Gating wrapper that shows an error panel or a skeleton while the initial
 *  page data is loading. After first successful load, passes through to
 *  children (background refetches are masked by keepPreviousData). */
export default function PageShell({ isPending, isError, error, hasData, skeleton, children }: PageShellProps) {
  if (isError && !hasData) {
    return (
      <Panel padding="md">
        <div className="flex items-center gap-3 text-gov-red">
          <span className="text-xs font-semibold uppercase tracking-wider">Engine unavailable</span>
          <span className="text-xs text-tertiary">
            {error instanceof Error ? error.message : 'Failed to load engine data'}
          </span>
        </div>
      </Panel>
    )
  }

  if (isPending && !hasData) {
    return <>{skeleton}</>
  }

  return <>{children}</>
}