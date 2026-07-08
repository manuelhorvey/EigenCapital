import React, { useMemo, useState } from 'react'
import { Ban, CheckCircle, XCircle } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import Badge, { signalToBadge } from './ui/Badge'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import { formatTimeAgo } from '../utils/format'

interface CycleEvent {
  asset: string
  timestamp: string
  signal: string
  confidence: number
  gatesResult: string
  size: string | null
  halted: boolean
  abortedGate: string | null
}

/** Last-cycle execution feed showing per-asset signal, confidence, gate result, and size. */
const ExecutionFeed = /*#__PURE__*/ React.memo(function ExecutionFeed() {
  const { data, isPending } = useSystemSnapshot(systemSelectors.snapshot)
  const { setSelectedAsset } = useSelectedAsset()
  const [showAll, setShowAll] = useState(false)

  const cycles = useMemo(() => {
    if (!data?.assets || !data?.portfolio) return []
    const events: CycleEvent[] = []
    const ts = data.timestamp ?? new Date().toISOString()

    for (const [name, asset] of Object.entries(data.assets)) {
      if (!(name in (data.portfolio?.allocations ?? {}))) continue

      const sig = asset.last_signal
      let abortedGate: string | null = null
      let gatesResult = 'PASS'

      if (asset.halt?.halted) {
        gatesResult = 'HALTED'
        abortedGate = (asset.halt.reasons ?? ['unknown']).join('; ')
      } else if (asset.final_signal == null && sig?.signal) {
        gatesResult = 'BLOCKED'
        abortedGate = 'gate_aborted'
      }

      const sc = asset.sizing_chain
      const size = sc?.final_pct != null ? `${(Number(sc.final_pct) * 100).toFixed(1)}%` : null

      events.push({
        asset: name,
        timestamp: sig?.date ?? ts,
        signal: asset.final_signal ?? sig?.signal ?? 'FLAT',
        confidence: sig?.confidence ?? 0,
        gatesResult,
        size,
        halted: asset.halt?.halted ?? false,
        abortedGate,
      })
    }

    events.sort((a, b) => b.asset.localeCompare(a.asset))
    return events
  }, [data])

  const displayed = showAll ? cycles : cycles.slice(0, 18)

  if (isPending) return <Skeleton className="h-32 rounded-lg" />
  if (cycles.length === 0) return <Panel><EmptyState message="Waiting for execution data…" compact /></Panel>

  const blockedCount = cycles.filter(c => c.gatesResult !== 'PASS').length

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Last Cycle — Execution Feed"
        accent="emerald"
        meta={
          <div className="flex items-center gap-2 text-[10px] text-tertiary font-mono">
            {blockedCount > 0 && (
              <span className="text-gov-yellow font-semibold">{blockedCount} blocked</span>
            )}
            <span>{data?.timestamp ? formatTimeAgo(data.timestamp) : ''}</span>
          </div>
        }
      />
      <div className="overflow-x-auto" role="log" aria-live="polite">
        <table className="w-full text-xs min-w-[500px]">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-1.5 pr-2">Asset</th>
              <th className="table-header text-left py-1.5 pr-2">Signal</th>
              <th className="table-header text-right py-1.5 pr-2">Conf</th>
              <th className="table-header text-left py-1.5 pr-2">Gates</th>
              <th className="table-header text-right py-1.5 pr-2">Size</th>
              <th className="table-header text-left py-1.5">Detail</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map(c => {
              const { variant } = signalToBadge(c.signal)
              const isPass = c.gatesResult === 'PASS'
              return (
                <tr
                  key={c.asset}
                  onClick={() => setSelectedAsset(c.asset)}
                  className="border-b border-default/30 table-row-hover cursor-pointer"
                >
                  <td className="py-1.5 pr-2 font-medium font-mono text-primary">{c.asset}</td>
                  <td className="py-1.5 pr-2">
                    <Badge variant={variant} size="sm">
                      {c.signal === 'BUY' ? 'LONG' : c.signal === 'SELL' ? 'SHORT' : 'FLAT'}
                    </Badge>
                  </td>
                  <td className="text-right py-1.5 pr-2 font-mono tabular-nums">
                    {(c.confidence * 100).toFixed(0)}
                  </td>
                  <td className="py-1.5 pr-2">
                    {c.halted ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gov-red">
                        <Ban className="w-3 h-3" strokeWidth={2} />
                        HALTED
                      </span>
                    ) : isPass ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gov-green">
                        <CheckCircle className="w-3 h-3" strokeWidth={2} />
                        PASS
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gov-yellow">
                        <XCircle className="w-3 h-3" strokeWidth={2} />
                        {c.gatesResult}
                      </span>
                    )}
                  </td>
                  <td className="text-right py-1.5 pr-2 font-mono tabular-nums text-primary">
                    {c.size ?? '—'}
                  </td>
                  <td className="py-1.5 text-[10px] text-tertiary">
                    {c.abortedGate ?? '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {cycles.length > 18 && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          className="w-full text-center py-2 text-[10px] font-medium text-tertiary hover:text-secondary border-t border-default transition-colors"
        >
          {showAll ? 'Show fewer' : `Show all ${cycles.length} assets`}
        </button>
      )}
    </Panel>
  )
})

export default ExecutionFeed