import { semanticColor } from './semantic'

interface ScoreBarProps {
  label: string
  score: number
  /** Semantic token name (e.g. 'blue') or a raw CSS color. */
  color: string
}

export default function ScoreBar({ label, score, color }: ScoreBarProps) {
  const pct = Math.min(Math.max(score, 0), 1)
  const resolved = semanticColor(color)
  return (
    <div className="flex items-center gap-2">
      <span className="text-2xs text-tertiary w-20 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-default rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct * 100}%`, backgroundColor: resolved }} />
      </div>
      <span className="text-2xs font-mono text-secondary w-8 text-right">{(pct * 100).toFixed(0)}%</span>
    </div>
  )
}