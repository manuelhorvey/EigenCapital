import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import type { VolRegime } from '../types/portfolio'

const VOL_BASELINES: Record<string, number> = {
  BTC: 0.038705,
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
}

function volStatus(ratio: number): VolRegime['status'] {
  if (ratio >= 0.8 && ratio <= 1.2) return 'green'
  if ((ratio >= 0.7 && ratio < 0.8) || (ratio > 1.2 && ratio <= 1.3)) return 'amber'
  return 'red'
}

const statusConfig = {
  green: { label: 'NORMAL', bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20', bar: 'bg-emerald-500' },
  amber: { label: 'WATCH', bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20', bar: 'bg-amber-500' },
  red: { label: 'ELEVATED', bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/20', bar: 'bg-red-500' },
}

export default function VolRegimePanel() {
  const { data } = usePortfolioState()

  const regimes = useMemo((): VolRegime[] => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .map(([name, asset]) => {
        const trainingVol = VOL_BASELINES[name]
        const currentVol = asset.metrics?.position?.current_vol
        if (trainingVol == null || currentVol == null) return null
        const ratio = trainingVol > 0 ? currentVol / trainingVol : 1
        return { asset: name, training_vol: trainingVol, current_vol: currentVol, ratio, status: volStatus(ratio) }
      })
      .filter((r): r is VolRegime => r !== null)
      .sort((a, b) => a.asset.localeCompare(b.asset))
  }, [data])

  return (
    <div className="card-gradient card-border rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-2 h-2 rounded-full bg-amber-500/50" />
        <h2 className="text-sm font-semibold text-primary">Vol Regime</h2>
      </div>
      {regimes.length === 0 ? (
        <div className="text-xs text-tertiary text-center py-8">No position data yet</div>
      ) : (
        <div className="space-y-2">
          {regimes.map(r => {
            const cfg = statusConfig[r.status]
            const barWidth = Math.min((r.ratio / 1.5) * 100, 100)
            return (
              <div key={r.asset} className="bg-panel rounded-lg p-3 transition-colors hover:bg-panel/80">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-primary">{r.asset}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
                    {cfg.label}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px] mb-1.5">
                  <span className="text-tertiary">Current</span>
                  <span className="font-mono text-secondary">{r.current_vol.toFixed(4)}</span>
                  <span className="text-tertiary">/ Baseline</span>
                  <span className="font-mono text-tertiary">{r.training_vol.toFixed(4)}</span>
                  <span className={`font-mono ml-auto ${cfg.text}`}>{r.ratio.toFixed(2)}x</span>
                </div>
                <div className="w-full h-1 bg-panel rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${cfg.bar}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
