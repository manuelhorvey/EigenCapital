interface ProgressStackSegment {
  label: string
  value: number
  color: string
}

interface ProgressStackProps {
  segments: ProgressStackSegment[]
  total?: number
  height?: string
  showLabels?: boolean
  className?: string
}

export default function ProgressStack({
  segments, total, height = 'h-2', showLabels = true, className = '',
}: ProgressStackProps) {
  const sum = total ?? segments.reduce((a, s) => a + s.value, 0)
  if (sum === 0) return null

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className={`flex w-full rounded-full overflow-hidden ${height} bg-panel`}>
        {segments.map(s => {
          const pct = (s.value / sum) * 100
          if (pct < 0.5) return null
          return (
            <div
              key={s.label}
              className="transition-all duration-500"
              style={{ width: `${pct}%`, backgroundColor: s.color }}
              title={`${s.label}: ${s.value.toFixed(2)} (${pct.toFixed(1)}%)`}
            />
          )
        })}
      </div>
      {showLabels && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          {segments.map(s => {
            const pct = (s.value / sum) * 100
            if (pct < 1) return null
            return (
              <span key={s.label} className="inline-flex items-center gap-1 text-[10px] text-tertiary font-mono">
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                {s.label} {pct.toFixed(0)}%
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
