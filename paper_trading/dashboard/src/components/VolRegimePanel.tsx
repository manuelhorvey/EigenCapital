import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import type { VolRegime } from '../types/portfolio'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

const VOL_BASELINES: Record<string, number> = {
  GC: 0.009129,
  NZDJPY: 0.006581,
  CADJPY: 0.005989,
  USDCAD: 0.004463,
  EURAUD: 0.005026,
  AUDJPY: 0.006759,
  GBPJPY: 0.006138,
  USDJPY: 0.004498,
  USDCHF: 0.004307,
  GBPUSD: 0.005595,
  CHFJPY: 0.004780,
  EURCAD: 0.003476,
  DJI: 0.008061,
}

function volStatus(ratio: number): VolRegime['status'] {
  if (ratio >= 0.8 && ratio <= 1.2) return 'green'
  if ((ratio >= 0.7 && ratio < 0.8) || (ratio > 1.2 && ratio <= 1.3)) return 'amber'
  return 'red'
}

const statusConfig = {
  green: {
    label: 'OK',
    badge: 'bg-gov-green-muted text-gov-green border-gov-green/25',
    ratioText: 'text-gov-green',
    bar: 'bg-gov-green',
  },
  amber: {
    label: 'WATCH',
    badge: 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/25',
    ratioText: 'text-gov-yellow',
    bar: 'bg-gov-yellow',
  },
  red: {
    label: 'HIGH',
    badge: 'bg-gov-red-muted text-gov-red border-gov-red/25',
    ratioText: 'text-gov-red',
    bar: 'bg-gov-red',
  },
}

export default function VolRegimePanel() {
  const { data, isPending } = usePortfolioState()

  const regimes = useMemo((): VolRegime[] => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .map(([name, asset]) => {
        const trainingVol = VOL_BASELINES[name]
        const currentVol = asset.metrics?.position?.current_vol
        if (trainingVol == null || currentVol == null) return null
        if (isNaN(trainingVol) || isNaN(currentVol) || !isFinite(trainingVol)) return null
        const ratio = trainingVol > 0 ? currentVol / trainingVol : 1
        return { asset: name, training_vol: trainingVol, current_vol: currentVol, ratio, status: volStatus(ratio) }
      })
      .filter((r): r is VolRegime => r !== null)
      .sort((a, b) => a.asset.localeCompare(b.asset))
  }, [data])

  if (isPending) {
    return (
      <Panel className="p-4">
        <Skeleton className="h-4 w-24 mb-3 rounded" />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-8 rounded" />
          ))}
        </div>
      </Panel>
    )
  }

  return (
    <Panel padding="md">
      <SectionHeader title="Vol Regime" accent="amber" />
      {regimes.length === 0 ? (
        <EmptyState message="No position data yet" compact />
      ) : (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-[11px] min-w-[280px]">
            <thead>
              <tr className="border-b border-default">
                <th className="table-header text-left py-1.5 pr-2">Asset</th>
                <th className="table-header text-right py-1.5 pr-2">Curr</th>
                <th className="table-header text-right py-1.5 pr-2">Base</th>
                <th className="table-header text-right py-1.5 pr-2">Ratio</th>
                <th className="table-header text-right py-1.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {regimes.map((r, i) => {
                const cfg = statusConfig[r.status]
                const barWidth = Math.min(Math.max((r.ratio / 1.5) * 100, 0), 100)
                return (
                  <tr
                    key={r.asset}
                    className={`border-b border-default/30 table-row-hover ${
                      i % 2 === 1 ? 'bg-panel/30' : ''
                    }`}
                  >
                    <td className="py-1.5 pr-2">
                      <span className="text-xs font-semibold text-primary font-mono">{r.asset}</span>
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-secondary tabular-nums">
                      {r.current_vol.toFixed(4)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-muted tabular-nums">
                      {r.training_vol.toFixed(4)}
                    </td>
                    <td className={`py-1.5 pr-2 text-right font-mono tabular-nums ${cfg.ratioText}`}>
                      {r.ratio.toFixed(2)}x
                    </td>
                    <td className="py-1.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <div className="w-12 h-1 bg-panel rounded-full overflow-hidden border border-default/50">
                          <div className={`h-full rounded-full ${cfg.bar}`} style={{ width: `${barWidth}%` }} />
                        </div>
                        <span className={`px-1 py-0.5 rounded border text-2xs font-bold tracking-wide ${cfg.badge}`}>
                          {cfg.label}
                        </span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
