import { useId } from 'react'
import { scoreFillColor } from './governance'

interface GaugeProps {
  label: string
  value: number
  size?: number
  color?: string
  className?: string
}

export default function Gauge({
  label,
  value,
  size = 80,
  color,
  className = '',
}: GaugeProps) {
  const gradientId = useId()
  const pct = Math.min(Math.max(value, 0), 1)
  const strokeColor = color ?? scoreFillColor(pct)
  const r = size * 0.35
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct)

  return (
    <div className={`flex flex-col items-center gap-1 ${className}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label}: ${(pct * 100).toFixed(0)}%`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-border-strong)" />
            <stop offset="100%" stopColor="var(--color-border)" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${gradientId})`} strokeWidth={6} />
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
