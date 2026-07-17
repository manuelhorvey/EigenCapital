interface GaugeProps {
  label: string
  value: number
  size?: number
  color?: string
  className?: string
}

function valueColor(pct: number): string {
  if (pct >= 0.8) return 'var(--color-gov-green)'
  if (pct >= 0.5) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-red)'
}

/** Circular SVG gauge with animated arc, auto-colored by value threshold (green/yellow/red). */
export default function Gauge({
  label,
  value,
  size = 80,
  color,
  className = '',
}: GaugeProps) {
  const pct = Math.min(Math.max(value, 0), 1)
  const strokeColor = color ?? valueColor(pct)
  const r = size * 0.35
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct)

  const uniqueId = `gauge-track-${label.replace(/\s/g, '')}`

  return (
    <div
      className={`flex flex-col items-center gap-1 ${className}`}
      role="meter"
      aria-label={label}
      aria-valuenow={Math.round(pct * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={`${label}: ${(pct * 100).toFixed(0)}%`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id={uniqueId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-border-strong)" />
            <stop offset="100%" stopColor="var(--color-border)" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${uniqueId})`} strokeWidth={6} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={strokeColor}
          strokeWidth={6}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.6s ease-out' }}
        />
        <text
          x={size / 2}
          y={size / 2}
          textAnchor="middle"
          dominantBaseline="central"
          fill="currentColor"
          fontSize={size * 0.18}
          fontWeight={600}
          className="text-secondary font-mono"
        >
          {(pct * 100).toFixed(0)}%
        </text>
      </svg>
      <span className="text-2xs text-tertiary">{label}</span>
    </div>
  )
}
