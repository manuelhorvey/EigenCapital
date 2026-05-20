import { useMemo } from 'react'

interface Props {
  hovered?: boolean
}

const points = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110]
const tp = 112
const sl = 96

export default function BarrierMock({ hovered }: Props) {
  const min = Math.min(...points, sl)
  const max = Math.max(...points, tp)
  const range = max - min || 1

  const pathD = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * 100
      const y = ((max - p) / range) * 60
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`
    })
    .join(' ')

  const animProgress = useMemo(() => (hovered ? 100 : 0), [hovered])

  return (
    <div className="space-y-2">
      <svg viewBox="0 0 100 70" className="w-full h-16" preserveAspectRatio="none">
        <line x1="0" y1={((max - tp) / range) * 60} x2="100" y2={((max - tp) / range) * 60} stroke="#10b981" strokeWidth="0.5" strokeDasharray="2 1" opacity={0.7} />
        <line x1="0" y1={((max - sl) / range) * 60} x2="100" y2={((max - sl) / range) * 60} stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2 1" opacity={0.7} />

        <path d={pathD} fill="none" stroke="#6b7280" strokeWidth="0.8" opacity={0.5} />

        <circle cx={0} cy={((max - points[0]) / range) * 60} r="1.5" fill="#6b7280" opacity={0.6} />

        {hovered && (
          <>
            <circle
              r="2"
              fill="#10b981"
              className="transition-all duration-[1200ms] ease-linear"
              style={{
                cx: animProgress,
                cy: (() => {
                  const idx = Math.min(Math.floor(animProgress / (100 / (points.length - 1))), points.length - 2)
                  const frac = (animProgress % (100 / (points.length - 1))) / (100 / (points.length - 1))
                  const y0 = (max - points[idx]) / range * 60
                  const y1 = (max - points[idx + 1]) / range * 60
                  return y0 + (y1 - y0) * frac
                })(),
                opacity: animProgress >= 95 ? 0 : 1,
              }}
            />
            {animProgress >= 95 && (
              <circle
                r="3"
                fill="#10b981"
                opacity={0.6}
                className="animate-ping"
                style={{ cx: 100, cy: ((max - points[points.length - 1]) / range) * 60 }}
              />
            )}
          </>
        )}
      </svg>

      <div className="flex justify-between text-[8px] text-gray-600">
        <span>SL 96</span>
        <span>TP 112</span>
      </div>
    </div>
  )
}
