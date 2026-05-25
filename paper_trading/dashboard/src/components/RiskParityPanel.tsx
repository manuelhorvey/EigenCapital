import { useMemo } from 'react'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { useRiskParity } from '../hooks/useRiskParity'
import { useGovernance } from '../hooks/useGovernance'

const GOV_BAR_COLORS: Record<string, string> = {
  RED: 'bg-gov-red',
  YELLOW: 'bg-gov-yellow',
  GREEN: 'bg-gov-green',
}

const GOV_BAR_OPACITY: Record<string, string> = {
  RED: 'opacity-80',
  YELLOW: 'opacity-70',
  GREEN: 'opacity-70',
}

function barColor(asset: string, pct: number, gov: Record<string, string> | null): string {
  if (gov && gov[asset]) {
    return GOV_BAR_COLORS[gov[asset]] ?? 'bg-accent-blue'
  }
  if (pct >= 10) return 'bg-accent-blue'
  if (pct >= 5) return 'bg-accent-emerald'
  return 'bg-accent-purple'
}

function barOpacity(asset: string, gov: Record<string, string> | null): string {
  if (gov && gov[asset]) return GOV_BAR_OPACITY[gov[asset]] ?? 'opacity-70'
  return 'opacity-70'
}

export default function RiskParityPanel() {
  const { data, isPending, isError, error } = useRiskParity()
  const { data: govData } = useGovernance()

  const govStateMap = useMemo(() => {
    if (!govData) return null
    const map: Record<string, string> = {}
    for (const [asset, state] of Object.entries(govData)) {
      map[asset] = state.validity_state
    }
    return map
  }, [govData])

  if (isPending) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Risk Parity Weights" accent="blue" />
        <div className="space-y-1.5 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-3 w-14 bg-panel rounded" />
              <div className="flex-1 h-4 bg-panel rounded-sm" />
              <div className="h-3 w-12 bg-panel rounded" />
            </div>
          ))}
        </div>
      </Panel>
    )
  }

  if (isError) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Risk Parity Weights" accent="blue" />
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <span className="text-xs text-gov-red/80">Failed to load risk parity data</span>
          <span className="text-2xs text-muted font-mono">{error?.message}</span>
        </div>
      </Panel>
    )
  }

  if (!data || !data.weights || Object.keys(data.weights).length === 0) return null

  const entries = Object.entries(data.weights)
    .sort(([, a], [, b]) => b - a)

  const nAssets = entries.length
  const equalWeight = nAssets > 0 ? 100 / nAssets : 0
  const totalPct = entries.reduce((sum, [, w]) => sum + w * 100, 0)

  return (
    <Panel className="p-4">
      <SectionHeader
        title="Risk Parity Weights"
        accent="blue"
        meta={
          <span className="text-[10px] text-tertiary font-mono bg-panel px-2 py-0.5 rounded border border-default tabular-nums">
            {nAssets} assets · {totalPct.toFixed(1)}% allocated
          </span>
        }
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-3 text-2xs text-muted font-mono mb-0.5">
          <span className="w-14 shrink-0" />
          <div className="flex-1 relative h-0">
            <div
              className="absolute top-0 bottom-0 border-l border-dashed border-muted/40"
              style={{ left: `${equalWeight * 4}%` }}
              title={`Equal weight: ${equalWeight.toFixed(1)}%`}
            />
          </div>
          <span className="w-12 text-right">{equalWeight.toFixed(1)}%</span>
          <span className="w-20 text-right text-muted">equal</span>
        </div>

        {entries.map(([name, weight]) => {
          const pct = weight * 100
          const capital = data.capital_allocations?.[name]
          const color = barColor(name, pct, govStateMap)
          const opacity = barOpacity(name, govStateMap)
          return (
            <div key={name} className="flex items-center gap-3 text-[11px]">
              <span className="w-14 font-mono text-primary font-semibold shrink-0">{name}</span>
              <div className="flex-1 h-4 bg-panel rounded-sm overflow-hidden border border-default/50 relative">
                <div
                  className={`h-full rounded-sm transition-all duration-500 ${color} ${opacity}`}
                  style={{ width: `${pct * 4}%` }}
                />
              </div>
              <span className="w-12 text-right font-mono tabular-nums text-secondary">{pct.toFixed(1)}%</span>
              {capital != null && (
                <span className="w-20 text-right font-mono tabular-nums text-tertiary text-2xs">
                  ${capital.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </span>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-3 pt-2 border-t border-default/50 text-2xs text-tertiary font-mono flex justify-between">
        <span>Total value</span>
        <span className="text-secondary">
          ${data.total_value?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? '—'}
        </span>
      </div>
    </Panel>
  )
}
