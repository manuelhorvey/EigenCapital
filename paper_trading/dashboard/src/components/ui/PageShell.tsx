import { useState, useEffect, type ReactNode } from 'react'
import Panel from './Panel'

interface PageShellProps {
  isPending: boolean
  isError: boolean
  error: Error | null
  hasData: boolean
  skeleton: ReactNode
  children: ReactNode
  /** ISO timestamp from the last successful server response, for stale-data indicator. */
  serverTime?: string
}

function formatAge(now: number, ts: number): string {
  const s = Math.floor((now - ts) / 1000)
  if (s < 0 || s < 5) return 'just now'
  return `${s}s ago`
}

/** Gating wrapper that shows an error panel or a skeleton while the initial
 *  page data is loading. After first successful load, passes through to
 *  children (background refetches are masked by keepPreviousData). */
export default function PageShell({ isPending, isError, error, hasData, skeleton, children, serverTime }: PageShellProps) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!serverTime) return
    const id = setInterval(() => setNow(Date.now()), 5_000)
    return () => clearInterval(id)
  }, [serverTime])

  if (isError && !hasData) {
    return (
      <Panel padding="md">
        <div className="flex items-center gap-3 text-gov-red" role="alert">
          <span className="text-xs font-semibold uppercase tracking-wider">Engine unavailable</span>
          <span className="text-xs text-tertiary">
            {error instanceof Error ? error.message : 'Failed to load engine data'}
          </span>
        </div>
      </Panel>
    )
  }

  if (isPending && !hasData) {
    return <div aria-busy="true">{skeleton}</div>
  }

  const serverTimeDisplay = serverTime
    ? (() => {
        const ts = new Date(serverTime).getTime()
        return isNaN(ts) ? serverTime : formatAge(now, ts)
      })()
    : null

  return (
    <>
      {serverTimeDisplay && (
        <div className="flex justify-end mb-2.5">
          <span className="text-[10px] text-tertiary font-mono tabular-nums">
            updated {serverTimeDisplay}
          </span>
        </div>
      )}
      {children}
    </>
  )
}