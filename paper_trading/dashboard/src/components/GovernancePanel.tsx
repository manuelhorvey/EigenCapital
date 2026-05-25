import GovernanceRow from './GovernanceRow'
import { usePortfolioState } from '../hooks/usePortfolioState'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'

function hasTrades(state: { metrics?: { trade_log?: unknown[] } }): boolean {
  return (state.metrics?.trade_log?.length ?? 0) > 0
}

export default function GovernancePanel() {
  const { data, isPending, isError } = usePortfolioState()
  const assets = data?.assets ?? {}

  if (isPending) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Calibration Governance" accent="indigo" />
        <div className="grid grid-cols-1 gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-panel/80 border border-default rounded-lg px-3 py-2.5 animate-pulse">
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="h-4 w-16 bg-panel rounded" />
                <div className="h-3 w-20 bg-panel rounded" />
              </div>
              <div className="flex gap-4">
                {Array.from({ length: 4 }).map((_, j) => (
                  <div key={j} className="h-3 w-24 bg-panel rounded" />
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    )
  }

  if (isError) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Calibration Governance" accent="indigo" />
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <span className="text-xs text-gov-red/80">Failed to load governance panel</span>
        </div>
      </Panel>
    )
  }

  const entries = Object.entries(assets).sort(([a], [b]) => {
    if (a === '^DJI' || a === 'DJI') return -1
    if (b === '^DJI' || b === 'DJI') return 1
    return a.localeCompare(b)
  })

  const active = entries.filter(([, s]) => hasTrades(s))
  const init = entries.filter(([, s]) => !hasTrades(s))

  if (entries.length === 0) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Calibration Governance" accent="indigo" />
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <span className="text-xs text-tertiary">No asset data available yet</span>
        </div>
      </Panel>
    )
  }

  return (
    <Panel className="p-4">
      <SectionHeader
        title="Calibration Governance"
        subtitle="Per-asset Jaccard stability, meta-label decisions, SL/TP alignment, premature stop rate"
        accent="indigo"
        meta={
          <span className="text-[10px] text-tertiary font-mono bg-panel px-2 py-0.5 rounded border border-default tabular-nums">
            {active.length} active · {init.length} init
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-2">
        {active.map(([name, state]) => (
          <GovernanceRow key={name} asset={name} state={state} />
        ))}
      </div>

      {init.length > 0 && (
        <details className="mt-3 group">
          <summary className="cursor-pointer text-[11px] text-tertiary font-mono px-2 py-1.5 rounded-md hover:bg-panel hover:text-secondary transition-colors select-none list-none flex items-center gap-1">
            <span className="text-muted group-open:rotate-90 transition-transform inline-block">▸</span>
            {init.length} asset{init.length > 1 ? 's' : ''} with no trades
          </summary>
          <div className="grid grid-cols-1 gap-2 mt-2">
            {init.map(([name, state]) => (
              <GovernanceRow key={name} asset={name} state={state} />
            ))}
          </div>
        </details>
      )}
    </Panel>
  )
}
