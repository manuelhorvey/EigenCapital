import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'

export default function GateAggregationPanel() {
  const { data: assets } = useSystemSnapshot(systemSelectors.assets)

  const gateBlocks = useMemo(() => {
    if (!assets) return null

    const counts: Record<string, number> = {}
    let totalAssets = 0

    for (const [name, state] of Object.entries(assets)) {
      const trace = state.gates_trace
      if (!trace) continue
      totalAssets++

      // Find the last gate in the trace — if it differs from the total stages,
      // that gate blocked. Since the trace records True before running,
      // the blocking gate is the last key in the trace.
      const gateNames = Object.keys(trace)
      if (gateNames.length === 0) continue

      // The final signal column tells us if a signal was produced
      const wasBlocked = state.final_signal == null && state.execution_state !== 'open'
      if (!wasBlocked) continue

      // The blocking gate is the last one in the trace
      const blockingGate = gateNames[gateNames.length - 1]
      counts[blockingGate] = (counts[blockingGate] || 0) + 1
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
