import { BarRow } from './ProgressBar'

interface SltpGaugeProps {
  tpRate: number
  slRate: number
  flipRate: number
}

export default function SltpGauge({ tpRate, slRate, flipRate }: SltpGaugeProps) {
  // TP high is good; SL high and FLIP high are bad — each metric routes
  // through its own threshold bands and gets a coloured bar.
  const tpColor = tpRate >= 0.25 ? 'bg-gov-green' : tpRate >= 0.15 ? 'bg-gov-yellow' : 'bg-gov-red'
  const slColor = slRate <= 0.5 ? 'bg-gov-green' : slRate <= 0.7 ? 'bg-gov-yellow' : 'bg-gov-red'
  const flipColor = flipRate <= 0.15 ? 'bg-gov-green' : flipRate <= 0.3 ? 'bg-gov-yellow' : 'bg-gov-red'

  return (
    <div className="flex flex-col gap-0.5 min-w-[130px]">
      <BarRow label="TP" value={tpRate} color={tpColor} />
      <BarRow label="SL" value={slRate} color={slColor} />
      <BarRow label="FL" value={flipRate} color={flipColor} />
    </div>
  )
}
