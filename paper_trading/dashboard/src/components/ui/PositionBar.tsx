import { memo } from 'react'

interface PositionBarProps {
  sl: number | null | undefined
  tp: number | null | undefined
  entry: number | null | undefined
  current: number | null | undefined
  side: 'long' | 'short' | string | null | undefined
}

/**
 * Terminal-style position axis: a single line from SL (left) to TP (right)
 * with an entry tick and a current-price marker. The segment between entry
 * and current is filled green when in profit, red when in drawdown.
 *
 * Blooms: low = progression from stop-loss to take-profit. Degenerate spans
 * (no sl/tp yet, or identical prices) collapse to a centered marker instead of
 * a garbage bar, so the whole Overview keeps one consistent visual language.
 */
function pctAt(span: number, lo: number, v: number): number {
  if (span === 0) return 0.5
  return Math.max(0, Math.min(1, (v - lo) / span))
}

function PositionBar({ sl, tp, entry, current, side }: PositionBarProps) {
  const hasSl = typeof sl === 'number' && isFinite(sl)
  const hasTp = typeof tp === 'number' && isFinite(tp)
  const hasEntry = typeof entry === 'number' && isFinite(entry)
  const hasCur = typeof current === 'number' && isFinite(current)

  const lo = hasSl ? sl : hasTp ? tp : hasEntry ? entry : 0
  const hi = hasTp ? tp : hasSl ? sl : hasEntry ? entry : 1
  const span = hi - lo

  const posSl = hasSl ? pctAt(span, lo, sl) : 0
  const posTp = hasTp ? pctAt(span, lo, tp) : 1
  const posEntry = hasEntry ? pctAt(span, lo, entry) : 0.5
  const posCur = hasCur ? pctAt(span, lo, current) : posEntry

  // Profit region = the segment between entry and current, colored by sign.
  let regionStart = 0
  let regionEnd = 0
  let regionColor = 'var(--color-gov-green)'
  if (hasEntry && hasCur && Math.abs(posCur - posEntry) > 0.002) {
    regionStart = Math.min(posEntry, posCur)
    regionEnd = Math.max(posEntry, posCur)
    const short = side === 'short'
    const profit = short ? current < entry : current > entry
    regionColor = profit ? 'var(--color-gov-green)' : 'var(--color-gov-red)'
  }
  const inProfit = regionColor === 'var(--color-gov-green)'

  return (
    <div className="relative h-4 w-full" role="img" aria-label={`position ${side ?? ''} entry ${entry} current ${current}`}>
      {/* TP / SL end labels (only when both exist) */}
      {hasSl && (
        <span className="absolute -top-0.5 text-[8px] leading-none text-gov-red font-mono" style={{ left: `${posSl * 100}%`, transform: 'translateX(-50%)' }}>
          SL
        </span>
      )}
      {hasTp && (
        <span className="absolute -top-0.5 text-[8px] leading-none text-gov-green font-mono" style={{ right: `${(1 - posTp) * 100}%`, transform: 'translateX(50%)' }}>
          TP
        </span>
      )}

      <div className="absolute inset-x-0 bottom-0 h-1 rounded-full bg-surface overflow-hidden">
        {/* P/L region fill */}
        {regionEnd > regionStart && (
          <div
            className="absolute top-0 h-full transition-all duration-300"
            style={{ left: `${regionStart * 100}%`, width: `${(regionEnd - regionStart) * 100}%`, backgroundColor: regionColor, opacity: 0.5 }}
          />
        )}
        {/* Entry tick */}
        {hasEntry && (
          <span className="absolute top-1/2 -translate-y-1/2 w-px h-2.5 bg-primary/70" style={{ left: `${posEntry * 100}%` }} />
        )}
        {/* Current marker */}
        <span
          className={`absolute -translate-x-1/2 top-1/2 -translate-y-1/2 w-1.5 h-1.5 rotate-45 transition-colors duration-300 ${inProfit ? 'bg-gov-green' : 'bg-gov-red'}`}
          style={{ left: `${posCur * 100}%` }}
        />
      </div>
    </div>
  )
}

export default PositionBar