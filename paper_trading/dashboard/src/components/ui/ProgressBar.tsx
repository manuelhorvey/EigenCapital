import type { ReactNode } from 'react'

interface BarRowProps {
  /** Label shown on the left, in mono caption colour. e.g. "TP" */
  label: ReactNode
  /** 0..1, displayed as 0..100% on the right cap */
  value: number
  /** Tailwind bg-* class or CSS color value controlling filled segment colour.
   *  Accepts Tailwind classes like 'bg-gov-green' or CSS values like 'var(--color-accent-blue)'. */
  color: string
  /** When true, 'color' is treated as a CSS value (via style.backgroundColor) rather than a Tailwind class. */
  cssColor?: boolean
  /** Override the default 8px track height */
  height?: string
  className?: string
}

/** Single labeled progress row showing label → filled track → percentage. @param color - Tailwind bg class or CSS color value for the fill. */
export function BarRow({ label, value, color, cssColor = false, height = 'h-2', className = '' }: BarRowProps) {
  const pct = Math.min(Math.max(value, 0), 1)
  const widthPct = pct * 100
  const showPct = Math.round(widthPct)

  return (
    <div className={`flex items-center gap-1.5 w-full ${className}`}>
      <span className="w-4 text-[10px] text-tertiary text-right shrink-0">{label}</span>
      <div className={`flex-1 ${height} bg-panel rounded-full overflow-hidden`}>
        <div
          className={`h-full rounded-full transition-all duration-500 ${cssColor ? '' : color}`}
          style={{ width: `${widthPct}%`, ...(cssColor ? { backgroundColor: color } : {}) }}
        />
      </div>
      <span className="w-[38px] text-[10px] font-mono text-right tabular-nums shrink-0">{showPct}%</span>
    </div>
  )
}

interface ProgressBarProps {
  value: number
  max?: number
  color?: string
  className?: string
  barClassName?: string
  height?: string
  showLabel?: boolean
  label?: string
}

function resolveColor(v: number, max: number): string {
  const pct = (v / max) * 100
  if (pct >= 80) return 'bg-gov-green'
  if (pct >= 50) return 'bg-gov-yellow'
  return 'bg-gov-red'
}

/** Standalone progress bar with optional label and auto color (green/yellow/red by threshold). */
export default function ProgressBar({
  value,
  max = 100,
  color,
  className = '',
  barClassName = '',
  height = 'h-1.5',
  showLabel = false,
  label,
}: ProgressBarProps) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100)
  const barColor = color ?? resolveColor(value, max)

  return (
    <div className={className}>
      {showLabel && (
        <div className="flex items-center justify-between mb-1">
          {label && <span className="text-2xs text-tertiary font-medium">{label}</span>}
          <span className="text-2xs font-mono tabular-nums text-tertiary">{pct.toFixed(0)}%</span>
        </div>
      )}
      <div className={`w-full ${height} bg-panel rounded-full overflow-hidden`}>
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor} ${barClassName}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
