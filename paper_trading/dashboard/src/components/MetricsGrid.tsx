import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

function pfColor(v: number | null | undefined): string {
  if (v != null && !isNaN(v) && v !== Infinity) return v >= 1 ? 'text-gov-green' : 'text-gov-yellow'
  return 'text-muted'
}

function monthlyPfColor(v: number | null | undefined): string {
  if (v != null && !isNaN(v) && v !== Infinity) return v >= 0.7 ? 'text-gov-green' : 'text-gov-yellow'
  return 'text-muted'
}

export default function MetricsGrid() {
  const { data, isPending } = usePortfolioState()
  const cards = useMemo(() => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, asset]) => {
        const m = asset.metrics
        const sd = m.signal_distribution ?? {}
        const total = (sd.BUY ?? 0) + (sd.SELL ?? 0) + (sd.FLAT ?? 0)
        return {
          name,
          nTrades: m.n_trades ?? 0,
          profitFactor: m.profit_factor,
          winRate: m.win_rate ?? 0,
          meanConf: m.mean_confidence ?? 0,
          meanProbLong: m.mean_prob_long ?? 0,
          meanProbShort: m.mean_prob_short ?? 0,
          monthlyPf: m.monthly_pf,
          sigBuy: sd.BUY ?? 0,
          sigSell: sd.SELL ?? 0,
          sigFlat: sd.FLAT ?? 0,
          sigTotal: total,
        }
      })
  }, [data])

  if (isPending) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-36 rounded-lg" />
        ))}
      </div>
    )
  }

  if (cards.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Asset Metrics" accent="blue" />
        <EmptyState message="No metric data available" compact />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {cards.map(c => (
        <Panel key={c.name} padding="none" className="px-3.5 py-3 panel-hover">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-sm font-semibold text-primary font-mono">{c.name}</span>
            <span className="text-2xs text-tertiary font-mono bg-panel px-1.5 py-0.5 rounded border border-default tabular-nums">
              {c.nTrades} trds
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-tertiary">PF</span>
              <span className={`font-mono tabular-nums ${pfColor(c.profitFactor)}`}>
                {c.profitFactor != null && !isNaN(c.profitFactor) && c.profitFactor !== Infinity
                  ? c.profitFactor.toFixed(2)
                  : '—'}
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-tertiary">Win Rate</span>
              <span className="font-mono tabular-nums text-primary">{c.winRate.toFixed(1)}%</span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-tertiary">Conf</span>
              <span className="font-mono tabular-nums text-primary">{c.meanConf.toFixed(1)}%</span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-tertiary">MoPF</span>
              <span className={`font-mono tabular-nums ${monthlyPfColor(c.monthlyPf)}`}>
                {c.monthlyPf != null && !isNaN(c.monthlyPf) && c.monthlyPf !== Infinity
                  ? c.monthlyPf.toFixed(2)
                  : '—'}
              </span>
            </div>
            <div className="col-span-2 flex items-baseline justify-between gap-2">
              <span className="text-tertiary">L/S</span>
              <span className="font-mono tabular-nums text-secondary">
                {c.meanProbLong.toFixed(0)}
                <span className="text-muted mx-0.5">/</span>
                {c.meanProbShort.toFixed(0)}%
              </span>
            </div>
            <div className="col-span-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-tertiary">Signal Dist</span>
                <span className="font-mono text-2xs text-muted tabular-nums">
                  {c.sigBuy}/{c.sigSell}/{c.sigFlat}
                </span>
              </div>
              {c.sigTotal > 0 && (
                <div className="flex h-1.5 bg-panel rounded-full overflow-hidden border border-default/50">
                  <div className="h-full bg-gov-green transition-all" style={{ width: `${(c.sigBuy / c.sigTotal) * 100}%` }} />
                  <div className="h-full bg-gov-red transition-all" style={{ width: `${(c.sigSell / c.sigTotal) * 100}%` }} />
                  <div className="h-full bg-gov-yellow transition-all" style={{ width: `${(c.sigFlat / c.sigTotal) * 100}%` }} />
                </div>
              )}
            </div>
          </div>
        </Panel>
      ))}
    </div>
  )
}
