import type { ReactNode } from 'react'

/**
 * <StatCell /> — single-cell unit of the quick-stats row on the
 * operator console. One mono headline + one uppercase tracking-wide
 * label, no card background, no shadow, no decoration.
 *
 * ── Token usage ──────────────────────────────────────────────────────
 *
 *   background : transparent   (the parent row owns the surface)
 *   text-dim   : label colour
 *   text-primary / text-signal-long|-warn|-short : value colour
 *
 * ── Tailwind binding ────────────────────────────────────────────────
 *
 * The design-system layer (Deliverable A) names the token surface
 * as 'signal-long' / 'signal-warn' / 'signal-short'. The Tailwind
 * registry today binds these to text-gov-green / text-gov-yellow /
 * text-gov-red respectively. When the registry is updated to
 * include the signal-* keys, this component's className map
 * changes but renders identically.
 *
 * Mapping:
 *   tone="good" -> gov-green  -> semantic: long / positive
 *   tone="warn" -> gov-yellow -> semantic: watch / monitor
 *   tone="bad"  -> gov-red    -> semantic: short / negative
 *   tone absent  -> text-primary
 *
 * ── Props ────────────────────────────────────────────────────────────
 *
 *   label : uppercase caption (mono caption weight)
 *   value : mono headline (string or ReactNode)
 *   tone  : optional. absent => primary
 *   sub   : optional smaller line under value
 *
 * ── Spacing/padding ──────────────────────────────────────────────────
 *
 *   px-3 (12 px space-3) inside cell
 *   py-2 (8 px space-2 between cell rows)
 *
 * Touch target: not applicable. Cell is read-only state; tap
 * target concern belongs to whatever interactive element surrounds
 * the cell at the parent row.
 */

type Tone = 'good' | 'warn' | 'bad' | undefined

const TONE_TO_CLASS: Record<Exclude<Tone, undefined>, string> = {
  good: 'text-gov-green',
  warn: 'text-gov-yellow',
  bad:  'text-gov-red',
}

export interface StatCellProps {
  label: ReactNode
  value: ReactNode
  tone?: Tone
  sub?: ReactNode
  className?: string
}

export default function StatCell({
  label,
  value,
  tone,
  sub,
  className = '',
}: StatCellProps) {
  const valueClass = tone ? TONE_TO_CLASS[tone] : 'text-primary'

  return (
    <div className={`px-3 py-2 min-w-0 ${className}`}>
      <p className="text-2xs text-tertiary font-medium uppercase tracking-wider truncate">
        {label}
      </p>
      <p className={`text-base font-bold font-mono tabular-nums ${valueClass} mt-0.5 truncate`}>
        {value}
      </p>
      {sub != null && (
        <p className="text-2xs text-tertiary font-mono tabular-nums mt-0.5 truncate">
          {sub}
        </p>
      )}
    </div>
  )
}
