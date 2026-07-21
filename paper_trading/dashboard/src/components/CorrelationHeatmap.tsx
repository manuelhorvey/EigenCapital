import { memo, useMemo, useState } from 'react'
import { useEquityHistory } from '../hooks/useEquityHistory'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

interface CorrelationRow {
  asset: string
  correlations: { target: string; value: number }[]
  maxCorr: number
}

/** Compute pairwise Pearson correlation between assets from equity history data. */
function computeCorrelations(history: { assets: Record<string, number> }[]): CorrelationRow[] {
  if (history.length < 10) return []

  // Build aligned time series for each asset
  const series = new Map<string, number[]>()
  for (const point of history) {
    for (const [name, value] of Object.entries(point.assets ?? {})) {
      if (!series.has(name)) series.set(name, [])
      series.get(name)!.push(value)
    }
  }

  const assetNames = [...series.keys()].sort()
  if (assetNames.length < 2) return []

  const results: CorrelationRow[] = []
  for (const a of assetNames) {
    const aVals = series.get(a)!
    const correlations: { target: string; value: number }[] = []
    for (const b of assetNames) {
      if (a === b) continue
      const bVals = series.get(b)!
      const minLen = Math.min(aVals.length, bVals.length)
      const aSlice = aVals.slice(0, minLen)
      const bSlice = bVals.slice(0, minLen)
      const corr = pearsonCorrelation(aSlice, bSlice)
      correlations.push({ target: b, value: corr })
    }
    correlations.sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    results.push({
      asset: a,
      correlations,
      maxCorr: correlations.length > 0 ? Math.abs(correlations[0].value) : 0,
    })
  }

  return results.sort((a, b) => b.maxCorr - a.maxCorr)
}

export function pearsonCorrelation(x: number[], y: number[]): number {
  const n = x.length
  if (n < 3) return 0

  const sumX = x.reduce((a, b) => a + b, 0)
  const sumY = y.reduce((a, b) => a + b, 0)
  const sumX2 = x.reduce((a, b) => a + b * b, 0)
  const sumY2 = y.reduce((a, b) => a + b * b, 0)
  const sumXY = x.reduce((a, b, i) => a + b * y[i], 0)

  const num = n * sumXY - sumX * sumY
  const den = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY))
  return den === 0 ? 0 : num / den
}

function corrColor(value: number): string {
  const abs = Math.abs(value)
  if (abs < 0.3) return 'var(--color-signal-long)'
  if (abs < 0.5) return 'var(--color-signal-warn)'
  if (abs < 0.7) return 'var(--color-chart-7)'
  return 'var(--color-signal-short)'
}

function corrBg(value: number, max: number): string {
  const abs = Math.abs(value)
  const intensity = max > 0 ? abs / max : 0
  const alpha = Math.min(0.15 + intensity * 0.35, 0.5).toFixed(2)
  if (value > 0) return `rgba(37, 208, 101, ${alpha})`
  return `rgba(240, 68, 68, ${alpha})`
}

/** Cross-asset correlation heatmap showing pairwise return correlations from equity history. */
const CorrelationHeatmap = memo(function CorrelationHeatmap() {
  const { data: history, isPending } = useEquityHistory()
  const [showAll, setShowAll] = useState(false)

  const correlations = useMemo(() => {
    if (!history) return []
    const all = computeCorrelations(history)
    return showAll ? all : all.slice(0, 8)
  }, [history, showAll])

  if (isPending) {
    return (
      <Panel padding="md">
        <SectionHeader title="Correlation Matrix" accent="emerald" />
        <Skeleton className="h-48 w-full rounded" shimmer />
      </Panel>
    )
  }

  if (correlations.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Correlation Matrix" accent="emerald" />
        <EmptyState
          message={!history || history.length < 10 ? 'Need ≥10 data points for correlations' : 'Insufficient asset history'}
          compact
        />
      </Panel>
    )
  }

  const assets = correlations.map(c => c.asset)
  const maxCorr = Math.max(...correlations.map(c => c.maxCorr), 0.01)

  return (
    <Panel padding="md">
      <SectionHeader
        title="Correlation Matrix"
        accent="emerald"
        meta={
          <span className="text-2xs text-tertiary font-mono">
            {assets.length} assets
          </span>
        }
      />
      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr>
              <th className="table-header text-left py-1 pr-2 sticky left-0 bg-app z-10" />
              {assets.map(a => (
                <th key={a} className="table-header text-right py-1 px-1 font-mono" title={a}>
                  {a.length > 6 ? a.slice(0, 5) + '…' : a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {correlations.map(row => (
              <tr key={row.asset}>
                <td className="py-1 pr-2 font-semibold text-primary font-mono sticky left-0 bg-app z-10">
                  {row.asset}
                  {row.maxCorr > 0.7 && (
                    <span className="ml-1 text-signal-short text-[8px]">⚠</span>
                  )}
                </td>
                {assets.map(target => {
                  const corr = row.correlations.find(c => c.target === target)
                  const v = corr?.value ?? 0
                  const isSelf = row.asset === target
                  return (
                    <td
                      key={target}
                      className="text-right py-1 px-1 font-mono tabular-nums rounded"
                      style={{
                        backgroundColor: isSelf ? 'var(--color-panel)' : corrBg(v, maxCorr),
                        color: isSelf ? 'var(--color-text-muted)' : corrColor(v),
                      }}
                      title={isSelf ? '' : `${row.asset} / ${target}: ${v.toFixed(3)}`}
                    >
                      {isSelf ? '—' : v.toFixed(2)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {correlations.length >= 8 && !showAll && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="w-full text-center py-1.5 text-[10px] font-medium text-tertiary hover:text-secondary border-t border-default mt-2 transition-colors"
        >
          Show all {correlations.length} assets
        </button>
      )}
      {showAll && (
        <button
          type="button"
          onClick={() => setShowAll(false)}
          className="w-full text-center py-1.5 text-[10px] font-medium text-tertiary hover:text-secondary border-t border-default mt-2 transition-colors"
        >
          Show fewer
        </button>
      )}
    </Panel>
  )
})
CorrelationHeatmap.displayName = 'CorrelationHeatmap'

export default CorrelationHeatmap
