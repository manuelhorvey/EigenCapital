import { useHaltStatus } from '../hooks/useHaltStatus'
import { usePortfolioState } from '../hooks/usePortfolioState'

function CheckIcon() {
  return (
    <svg className="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg className="w-3 h-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

export default function HaltConditions() {
  const { data } = usePortfolioState()
  const status = useHaltStatus(data)
  if (!data) return null

  const cards = [
    {
      label: 'Max Drawdown',
      value: `${status.maxDrawdown.toFixed(2)}%`,
      threshold: `${status.drawdownTrigger.toFixed(0)}%`,
      pass: status.drawdownPass,
    },
    {
      label: 'Monthly PF',
      value: status.minMonthlyPf === Infinity || isNaN(status.minMonthlyPf) ? '—' : status.minMonthlyPf.toFixed(2),
      threshold: status.monthlyPfTrigger.toFixed(2),
      pass: status.monthlyPfPass,
    },
    {
      label: 'Signal Drought',
      value: '0d',
      threshold: `${data.halt_conditions?.signal_drought ?? 30}d`,
      pass: true,
    },
    {
      label: 'Prob Drift',
      value: `< ${((data.halt_conditions?.prob_drift ?? 0.15) * 100).toFixed(0)}%`,
      threshold: `${((data.halt_conditions?.prob_drift ?? 0.15) * 100).toFixed(0)}%`,
      pass: true,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map(c => (
        <div
          key={c.label}
          className={`rounded-xl p-4 border transition-all duration-200 ${
            c.pass
              ? 'bg-emerald-500/5 border-emerald-500/15'
              : 'bg-red-500/5 border-red-500/15'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-tertiary font-medium tracking-wide">{c.label}</span>
            <div className={`p-0.5 rounded-full ${c.pass ? 'bg-emerald-500/20' : 'bg-red-500/20'}`}>
              {c.pass ? <CheckIcon /> : <XIcon />}
            </div>
          </div>
          <div className={`text-lg font-bold tracking-tight metric-value ${c.pass ? 'text-emerald-400' : 'text-red-400'}`}>
            {c.value}
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-[11px] text-tertiary">Threshold:</span>
            <span className={`text-[11px] font-mono ${c.pass ? 'text-secondary' : 'text-red-400/70'}`}>
              {c.threshold}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
