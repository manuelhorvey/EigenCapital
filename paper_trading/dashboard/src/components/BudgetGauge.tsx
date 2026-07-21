import { BarRow } from './ui/ProgressBar'

interface BudgetGaugeProps {
  /** PEK budget utilization ratio. 1.0 = at budget, >1.0 = overrun (triggers backfeed). */
  utilization: number | undefined
}

function budgetColor(ratio: number): string {
  // >1.0 means over budget → red; >0.8 → yellow; otherwise green
  if (ratio >= 1.0) return 'var(--color-signal-short)'
  if (ratio >= 0.8) return 'var(--color-signal-warn)'
  return 'var(--color-signal-long)'
}

/** Color-coded horizontal bar showing PEK budget utilization with backfeed status. */
export default function BudgetGauge({ utilization }: BudgetGaugeProps) {
  if (utilization === undefined) return null

  const clamped = Math.min(utilization, 1.25) // cap at 125% for visual clarity
  const color = budgetColor(utilization)
  const pct = Math.round(utilization * 100)
  const overrun = utilization > 1.0

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">
          Budget Utilization
        </span>
        {overrun ? (
          <span className="text-[10px] font-mono font-semibold text-signal-short tabular-nums">
            {pct}% <span className="text-signal-short/70">(backfeed active)</span>
          </span>
        ) : (
          <span
            className="text-[10px] font-mono font-semibold tabular-nums"
            style={{ color }}
          >
            {pct}%
          </span>
        )}
      </div>
      <BarRow
        label="PEK"
        value={clamped}
        color={color}
        cssColor
        height="h-2.5"
      />
      <div className="flex justify-between text-[10px] text-tertiary/60 font-mono">
        <span>0%</span>
        <span>80%</span>
        <span>100%</span>
      </div>
    </div>
  )
}
