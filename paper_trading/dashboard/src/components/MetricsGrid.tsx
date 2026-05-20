import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'

export default function MetricsGrid() {
  const { data } = usePortfolioState()
  const cards = useMemo(() => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, asset]) => {
        const m = asset.metrics
        return {
          name,
          nTrades: m.n_trades ?? 0,
          profitFactor: m.profit_factor,
          winRate: m.win_rate ?? 0,
          meanConf: m.mean_confidence ?? 0,
          meanProbLong: m.mean_prob_long ?? 0,
          meanProbShort: m.mean_prob_short ?? 0,
          monthlyPf: m.monthly_pf,
          signalDist: m.signal_distribution,
        }
      })
  }, [data])

  if (cards.length === 0) return null

  const pfColor = (v: number | null | undefined) =>
    v != null && !isNaN(v) && v !== Infinity ? (v >= 1 ? 'text-emerald-400' : 'text-amber-400') : 'text-tertiary'

  const monthlyPfColor = (v: number | null | undefined) =>
    v != null && !isNaN(v) && v !== Infinity ? (v >= 0.7 ? 'text-emerald-400' : 'text-amber-400') : 'text-tertiary'

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {cards.map(c => (
        <div key={c.name} className="card-gradient card-border rounded-xl p-4 hover-lift">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-primary">{c.name}</span>
              <span className="text-[10px] text-tertiary bg-panel px-1.5 py-0.5 rounded-full">{c.nTrades} trades</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">Profit Factor</div>
              <div className={`font-mono text-sm font-medium ${pfColor(c.profitFactor)}`}>
                {c.profitFactor != null && !isNaN(c.profitFactor) && c.profitFactor !== Infinity ? c.profitFactor.toFixed(2) : '—'}
              </div>
              <div className="mt-1 w-full h-0.5 bg-panel rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${c.profitFactor != null && c.profitFactor >= 1 ? 'bg-emerald-500' : 'bg-amber-500'}`}
                  style={{ width: `${Math.min((c.profitFactor ?? 0) / 2 * 100, 100)}%` }}
                />
              </div>
            </div>

            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">Win Rate</div>
              <div className="font-mono text-sm font-medium text-primary">{c.winRate.toFixed(1)}%</div>
              <div className="mt-1 w-full h-0.5 bg-panel rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-emerald-500/50" style={{ width: `${c.winRate}%` }} />
              </div>
            </div>

            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">Mean Confidence</div>
              <div className="font-mono text-sm font-medium text-primary">{c.meanConf.toFixed(1)}%</div>
              <div className="mt-1 w-full h-0.5 bg-panel rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${c.meanConf >= 60 ? 'bg-emerald-500' : c.meanConf >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                  style={{ width: `${c.meanConf}%` }}
                />
              </div>
            </div>

            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">P(Long) / P(Short)</div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-sm font-medium text-emerald-400">{c.meanProbLong.toFixed(1)}%</span>
                <span className="text-tertiary">/</span>
                <span className="font-mono text-sm font-medium text-red-400">{c.meanProbShort.toFixed(1)}%</span>
              </div>
              <div className="mt-1.5 flex h-0.5 bg-panel rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500/50" style={{ width: `${c.meanProbLong}%` }} />
                <div className="h-full bg-red-500/50" style={{ width: `${c.meanProbShort}%` }} />
              </div>
            </div>

            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">Monthly PF</div>
              <div className={`font-mono text-sm font-medium ${monthlyPfColor(c.monthlyPf)}`}>
                {c.monthlyPf != null && !isNaN(c.monthlyPf) && c.monthlyPf !== Infinity ? c.monthlyPf.toFixed(2) : '—'}
              </div>
            </div>

            <div className="bg-panel rounded-lg p-2.5">
              <div className="text-[10px] text-tertiary mb-1">Signal Distribution</div>
              <div className="flex gap-2 text-xs mt-1">
                {c.signalDist ? (
                  <>
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      <span className="font-mono text-secondary">{c.signalDist.BUY ?? 0}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                      <span className="font-mono text-secondary">{c.signalDist.SELL ?? 0}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                      <span className="font-mono text-secondary">{c.signalDist.FLAT ?? 0}</span>
                    </span>
                  </>
                ) : (
                  <span className="text-tertiary">—</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
