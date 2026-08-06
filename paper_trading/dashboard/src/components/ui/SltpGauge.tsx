import { governanceDot, higherBetterRateToState, lowerBetterRateToState } from './governance'

interface SltpGaugeProps {
  tpRate: number
  slRate: number
  flipRate: number
}

function bar(label: string, pct: number, color: string) {
  const w = Math.min(pct * 100, 100)
  return (
    <div className="flex items-center gap-1.5 w-full">
      <span className="w-4 text-[10px] text-tertiary text-right shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-panel rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="w-[38px] text-[10px] font-mono text-right tabular-nums shrink-0">{(pct * 100).toFixed(0)}%</span>
    </div>
  )
}

export default function SltpGauge({ tpRate, slRate, flipRate }: SltpGaugeProps) {
  const tpColor = governanceDot[higherBetterRateToState(tpRate, 0.25, 0.15)]
  const slColor = governanceDot[lowerBetterRateToState(slRate, 0.5, 0.7)]
  const flipColor = governanceDot[lowerBetterRateToState(flipRate, 0.15, 0.3)]

  return (
    <div className="flex flex-col gap-0.5 min-w-[130px]">
      {bar('TP', tpRate, tpColor)}
      {bar('SL', slRate, slColor)}
      {bar('FL', flipRate, flipColor)}
    </div>
  )
}
