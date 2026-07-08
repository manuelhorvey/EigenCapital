import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'

/** Aggregated gate-blocking breakdown showing which gates blocked how many assets this cycle. */
export default function GateAggregationPanel() {
  const { data: assets } = useSystemSnapshot(systemSelectors.assets)

  const gateBlocks = useMemo(() => {
    if (!assets) return null

    const counts: Record<string, number> = {}
    let totalAssets = 0

    for (const [, state] of Object.entries(assets)) {
      totalAssets++

      // A blocked asset has final_signal == null and execution_state != 'open'
      const wasBlocked = state.final_signal == null && state.execution_state !== 'open'
      if (!wasBlocked) continue

      // Since gates_trace is no longer emitted, infer which gate blocked
      // from the halt state and signal availability
      if (state.halt?.halted) {
        const reasons = state.halt.reasons ?? ['unknown']
        for (const reason of reasons) {
          counts[reason] = (counts[reason] || 0) + 1
        }
      } else {
        counts['signal_aborted'] = (counts['signal_aborted'] || 0) + 1
      }
    }

    if (Object.keys(counts).length === 0) return null

    return {
      counts,
      totalBlocked: Object.values(counts).reduce((a, b) => a + b, 0),
      totalAssets,
    }
  }, [assets])

  if (!gateBlocks) {
    return (
      <Panel padding="md">
        <EmptyState message="No assets blocked by gates this cycle" compact />
      </Panel>
    )
  }

  const sorted = Object.entries(gateBlocks.counts).sort((a, b) => b[1] - a[1])

  return (
    <Panel padding="md">
      <div className="space-y-2">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">
          Gate Blocking — {gateBlocks.totalBlocked}/{gateBlocks.totalAssets} assets blocked
        </span>
        <div className="space-y-1">
          {sorted.map(([gate, count]) => {
            const pct = (count / gateBlocks.totalAssets) * 100
            return (
              <div key={gate} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-tertiary w-2/5 truncate" title={gate}>
                  {gate}
                </span>
                <div className="flex-1 h-4 bg-panel rounded overflow-hidden">
                  <div
                    className="h-full rounded bg-gov-red/60 transition-all duration-300"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="font-mono text-primary w-12 text-right">{count}</span>
              </div>
            )
          })}
        </div>
      </div>
    </Panel>
  )
}
