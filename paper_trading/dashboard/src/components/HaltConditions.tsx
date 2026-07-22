import { useMemo } from 'react'
import { Check, X, AlertTriangle } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { MetricCardSkeleton } from './ui/Skeleton'
import { signalDot, signalText } from './ui/governance'
import { gridMetric4, GRID_GAP } from '../design/grid'

/** Halt condition monitors: max drawdown, monthly PF, signal drought, and probability drift. */
export default function HaltConditions() {
  const { data, isPending } = useSystemSnapshot(systemSelectors.snapshot)

  const status = useMemo(() => {
    const hc = data?.halt_conditions
    const portfolio = data?.portfolio
    const assets = data?.assets ?? {}
    // Portfolio drawdown (stored as fraction upstream, convert to percent).
    // This is the canonical metric — per-asset drawdown can exceed -100% on
    // over-loss assets and would give a misleading "Max Drawdown" when min()-ed.
    const portfolioDD = (portfolio?.portfolio_drawdown ?? 0) * 100
    let minPF = Infinity
    for (const name in assets) {
      const m = assets[name].metrics
      if (m) {
        if (m.monthly_pf != null && m.monthly_pf < minPF) minPF = m.monthly_pf
      }
    }
    const ddTrigger = (hc?.drawdown ?? -0.08) * 100
    const pfTrigger = hc?.monthly_pf ?? 0.7
    const hasMonthlyPf = minPF !== Infinity
    return {
      maxDrawdown: portfolioDD,
      minMonthlyPf: hasMonthlyPf ? minPF : null,
      drawdownTrigger: ddTrigger,
      monthlyPfTrigger: pfTrigger,
      drawdownPass: portfolioDD > ddTrigger,
      monthlyPfPass: hasMonthlyPf ? minPF >= pfTrigger : true,
      anyTriggered: portfolioDD <= ddTrigger || (hasMonthlyPf && minPF < pfTrigger),
    }
  }, [data])

  if (isPending) {
    return <MetricCardSkeleton count={4} />
  }

  if (!data) return null

  const assets = data?.assets ?? {}
  let haltedAny = false
  let haltedCount = 0
  let droughtAny = false
  let driftAny = false
  for (const name in assets) {
    const ah = assets[name].halt
    if (ah?.halted) {
      haltedAny = true
      haltedCount++
      for (const r of ah.reasons ?? []) {
        if (r.toLowerCase().includes('drought')) droughtAny = true
        if (r.toLowerCase().includes('drift')) driftAny = true
      }
    }
  }

  const cards = [
    {
      label: 'Max Drawdown',
      value: `${status.maxDrawdown.toFixed(2)}%`,
      threshold: `${status.drawdownTrigger.toFixed(0)}%`,
      pass: status.drawdownPass,
    },
    {
      label: 'Monthly PF',
      value: status.minMonthlyPf == null ? '—' : status.minMonthlyPf.toFixed(2),
      threshold: status.monthlyPfTrigger.toFixed(2),
      pass: status.monthlyPfPass,
    },
    {
      label: 'Signal Drought',
      value: droughtAny ? 'Halted' : 'OK',
      threshold: `${data.halt_conditions?.signal_drought ?? 30}d`,
      pass: !droughtAny,
    },
    {
      label: 'Prob Drift',
      value: driftAny ? 'Halted' : 'OK',
      threshold: `${((data.halt_conditions?.prob_drift ?? 0.15) * 100).toFixed(0)}%`,
      pass: !driftAny,
    },
  ]

  return (
    <div>
      <div className={`${gridMetric4()} ${GRID_GAP}`}>
        {cards.map(c => {
          const state = c.pass ? 'LONG' : 'SHORT'
          return (
            <div
              key={c.label}
              className={`rounded-lg px-3.5 py-3 border transition-colors duration-200 ${
                c.pass
                  ? 'bg-panel border-default'
                  : 'bg-signal-short/[0.04] border-signal-short/15'
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="metric-label">{c.label}</span>
                <div className={`p-0.5 rounded-full ${signalDot[state]}/20`}>
                  {c.pass ? (
                    <Check className={`w-3 h-3 ${signalText.LONG}`} strokeWidth={2.5} />
                  ) : (
                    <X className={`w-3 h-3 ${signalText.SHORT}`} strokeWidth={2.5} />
                  )}
                </div>
              </div>
              <div className={`text-lg font-semibold tracking-tight metric-value ${signalText[state]}`}>
                {c.value}
              </div>
              <div className="flex items-center gap-1 mt-1">
                <span className="text-2xs text-muted">Threshold</span>
                <span className={`text-2xs font-mono tabular-nums ${c.pass ? 'text-secondary' : signalText.SHORT + '/80'}`}>
                  {c.threshold}
                </span>
              </div>
            </div>
          )
        })}
      </div>
      {haltedAny && (
        <div aria-live="polite" className="mt-2.5 flex items-center gap-2 px-3 py-2 rounded-lg bg-signal-short-muted border border-signal-short/20 text-[11px] text-signal-short">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
          <span className="font-medium">
            {haltedCount} asset{haltedCount > 1 ? 's' : ''} halted
          </span>
        </div>
      )}
    </div>
  )
}
