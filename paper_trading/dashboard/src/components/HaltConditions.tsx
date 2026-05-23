import { Check, X, AlertTriangle } from 'lucide-react'
import { useHaltStatus } from '../hooks/useHaltStatus'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { MetricCardSkeleton } from './ui/Skeleton'

export default function HaltConditions() {
  const { data, isPending } = usePortfolioState()
  const status = useHaltStatus(data)

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
      value:
        status.minMonthlyPf === Infinity || isNaN(status.minMonthlyPf)
          ? '—'
          : status.minMonthlyPf.toFixed(2),
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map(c => (
          <div
            key={c.label}
            className={`rounded-lg px-3.5 py-3 border transition-colors duration-200 ${
              c.pass ? 'halt-pass' : 'halt-fail'
            }`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <span className="metric-label">{c.label}</span>
              <div
                className={`p-0.5 rounded-full ${c.pass ? 'bg-gov-green/20' : 'bg-gov-red/20'}`}
              >
                {c.pass ? (
                  <Check className="w-3 h-3 text-gov-green" strokeWidth={2.5} />
                ) : (
                  <X className="w-3 h-3 text-gov-red" strokeWidth={2.5} />
                )}
              </div>
            </div>
            <div
              className={`text-lg font-semibold tracking-tight metric-value ${
                c.pass ? 'text-gov-green' : 'text-gov-red'
              }`}
            >
              {c.value}
            </div>
            <div className="flex items-center gap-1 mt-1">
              <span className="text-2xs text-muted">Threshold</span>
              <span
                className={`text-2xs font-mono tabular-nums ${
                  c.pass ? 'text-secondary' : 'text-gov-red/80'
                }`}
              >
                {c.threshold}
              </span>
            </div>
          </div>
        ))}
      </div>
      {haltedAny && (
        <div className="mt-2.5 flex items-center gap-2 px-3 py-2 rounded-lg bg-gov-red-muted border border-gov-red/20 text-[11px] text-gov-red">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
          <span className="font-medium">
            {haltedCount} asset{haltedCount > 1 ? 's' : ''} halted
          </span>
        </div>
      )}
    </div>
  )
}
