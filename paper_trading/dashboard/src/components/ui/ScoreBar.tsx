/**
 * <ScoreBar /> — horisontal bar with label, track, and percentage.
 *
 * Shares the attribution-panel visual vocabulary (80px label, 10px font,
 * inline color). Accepts CSS variable references or hex values.
 */
interface ScoreBarProps {
  label: string
  /** 0..1 score displayed as 0..100% on the right cap */
  score: number
  /** CSS color value (e.g. 'var(--color-gov-green)' or '#22c55e') */
  color: string
}

export default function ScoreBar({ label, score, color }: ScoreBarProps) {
  const pct = Math.min(Math.max(score, 0), 1)
  return (
    <div className="flex items-center gap-2">
      <span className="text-2xs text-tertiary w-20 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-default rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct * 100}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-2xs font-mono text-secondary w-8 text-right">
        {(pct * 100).toFixed(0)}%
      </span>
    </div>
  )
}
