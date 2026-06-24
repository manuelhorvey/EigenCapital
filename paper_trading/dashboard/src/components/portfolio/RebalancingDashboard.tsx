import { useMemo, useState } from 'react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { Skeleton } from '../ui/Skeleton'
import AllocationBar from './AllocationBar'
import Badge from '../ui/Badge'

interface Allocation {
  asset: string
  pct: number
}

function computeDrift(current: Allocation[], target: Allocation[]): number {
  let totalDrift = 0
  for (const t of target) {
    const cur = current.find(c => c.asset === t.asset)?.pct ?? 0
    totalDrift += Math.abs(cur - t.pct)
  }
  return totalDrift / 2
}

function estimateTrades(current: Allocation[], target: Allocation[], threshold = 0.02): number {
  let trades = 0
  for (const t of target) {
    const cur = current.find(c => c.asset === t.asset)?.pct ?? 0
    if (Math.abs(cur - t.pct) > threshold) trades++
  }
  return trades
}

export default function RebalancingDashboard() {
  const { data: bundle } = useSystemSnapshot()
  const state = bundle?.snapshot
  const portfolio = state?.portfolio

  const allocations: Allocation[] = useMemo(() => {
    if (!portfolio?.allocations) return []
    return Object.entries(portfolio.allocations).map(([asset, pct]) => ({
      asset,
      pct: typeof pct === 'number' ? pct : 0,
    }))
  }, [portfolio])

  // Target: equal-weight by default
  const targetAllocs: Allocation[] = useMemo(() => {
    if (allocations.length === 0) return []
    const equal = 1 / allocations.length
    return allocations.map(a => ({ asset: a.asset, pct: equal }))
  }, [allocations])

  const [proposed, setProposed] = useState<Allocation[]>(allocations)
  const [editing, setEditing] = useState(false)

  const currentDrift = computeDrift(allocations, targetAllocs)
  const proposedDrift = computeDrift(proposed, targetAllocs)
  const estimatedTrades = estimateTrades(allocations, proposed)

  if (allocations.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Risk Parity Rebalancing" accent="emerald" />
        <Skeleton className="h-24 w-full rounded" />
      </Panel>
    )
  }

  return (
    <Panel padding="lg">
      <SectionHeader
        title="Risk Parity Rebalancing"
        accent="emerald"
        meta={
          <button
            onClick={() => setEditing(!editing)}
            className="text-2xs font-medium text-accent-emerald hover:underline"
          >
            {editing ? 'Done' : 'Adjust'}
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <AllocationBar title="Current" allocations={allocations} variant="current" />
        <AllocationBar title="Target (Equal Risk)" allocations={targetAllocs} variant="target" />
        <AllocationBar
          title={editing ? 'Proposed (editing)' : 'Proposed'}
          allocations={editing ? proposed : allocations}
          variant={editing ? 'proposed' : 'current'}
        />
      </div>

      {/* Drift metrics */}
      <div className="grid grid-cols-3 gap-3 mt-4">
        <div className="border border-default rounded-lg px-3 py-2">
          <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Current Drift</p>
          <p className="text-sm font-bold font-mono tabular-nums mt-0.5">
            {(currentDrift * 100).toFixed(1)}%
          </p>
          <Badge variant={currentDrift < 0.1 ? 'success' : currentDrift < 0.2 ? 'warning' : 'error'} size="sm" dot>
            {currentDrift < 0.1 ? 'Balanced' : currentDrift < 0.2 ? 'Moderate' : 'Drifted'}
          </Badge>
        </div>
        <div className="border border-default rounded-lg px-3 py-2">
          <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Proposed Drift</p>
          <p className="text-sm font-bold font-mono tabular-nums mt-0.5">
            {(proposedDrift * 100).toFixed(1)}%
          </p>
          <Badge variant={proposedDrift < 0.1 ? 'success' : 'warning'} size="sm" dot>
            {proposedDrift < 0.1 ? 'Balanced' : 'Moderate'}
          </Badge>
        </div>
        <div className="border border-default rounded-lg px-3 py-2">
          <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Est. Trades Needed</p>
          <p className="text-sm font-bold font-mono tabular-nums mt-0.5">{estimatedTrades}</p>
          <p className="text-2xs text-tertiary mt-0.5">
            {estimatedTrades === 0 ? 'No rebalance needed' : `${estimatedTrades} asset(s) above threshold`}
          </p>
        </div>
      </div>

      {/* Interactive sliders */}
      {editing && (
        <div className="mt-4 space-y-2 pt-3 border-t border-default">
          <p className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Adjust Allocations</p>
          {proposed.map(alloc => (
            <div key={alloc.asset} className="flex items-center gap-3">
              <span className="text-xs font-mono text-primary w-16 shrink-0">{alloc.asset}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={alloc.pct}
                onChange={e => {
                  const val = parseFloat(e.target.value)
                  setProposed(prev =>
                    prev.map(a => a.asset === alloc.asset ? { ...a, pct: val } : a),
                  )
                }}
                className="flex-1 h-1.5 bg-default rounded-full appearance-none cursor-pointer accent-accent-emerald"
              />
              <span className="text-xs font-mono text-secondary tabular-nums w-14 text-right">
                {(alloc.pct * 100).toFixed(1)}%
              </span>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-2 text-2xs text-tertiary">
            <span>Total: {proposed.reduce((s, a) => s + a.pct, 0).toFixed(2)}</span>
            <span>·</span>
            <button
              onClick={() => {
                const even = 1 / proposed.length
                setProposed(proposed.map(a => ({ ...a, pct: even })))
              }}
              className="text-accent-emerald hover:underline"
            >
              Reset to equal weight
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}
