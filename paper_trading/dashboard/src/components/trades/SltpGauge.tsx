import { BarRow } from '../ui/ProgressBar'

interface SltpGaugeProps {
  tpRate: number
  slRate: number
  flipRate: number
}

/** Compact TP / SL / Flip rate gauge using BarRow segments, each auto-colored by threshold. */
export default function SltpGauge({ tpRate, slRate, flipRate }: SltpGaugeProps) {
  // TP high is good; SL high and FLIP high are bad — each metric routes
  // through its own threshold bands and gets a coloured bar.
  const tpColor = tpRate >= 0.25 ? 'bg-signal-long' : tpRate >= 0.15 ? 'bg-signal-warn' : 'bg-signal-short'
  const slColor = slRate <= 0.5 ? 'bg-signal-long' : slRate <= 0.7 ? 'bg-signal-warn' : 'bg-signal-short'
  const flipColor = flipRate <= 0.15 ? 'bg-signal-long' : flipRate <= 0.3 ? 'bg-signal-warn' : 'bg-signal-short'

  return (
    <div className="flex flex-col gap-0.5 min-w-[130px]">
      <BarRow label="TP" value={tpRate} color={tpColor} />
      <BarRow label="SL" value={slRate} color={slColor} />
      <BarRow label="FL" value={flipRate} color={flipColor} />
    </div>
  )
}
