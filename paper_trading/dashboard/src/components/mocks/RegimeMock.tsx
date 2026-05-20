import { useMemo } from 'react'

interface Props {
  hovered?: boolean
}

const regimes = [
  { label: 'TREND', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  { label: 'RANGE', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
  { label: 'VOLATILE', color: 'bg-red-500/20 text-red-400 border-red-500/30' },
]

export default function RegimeMock({ hovered }: Props) {
  const needleDeg = useMemo(() => hovered ? 30 + Math.random() * 60 : 50, [hovered])

  return (
    <div className="space-y-3">
      <div className="flex gap-1.5">
        {regimes.map((r, i) => (
          <span
            key={r.label}
            className={`px-2 py-0.5 rounded text-[10px] font-semibold border transition-all duration-500 ${r.color} ${
              hovered && i === 0 ? 'animate-pulse' : ''
            }`}
          >
            {r.label}
          </span>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <span className="text-[10px] text-gray-500 w-12">Hurst</span>
        <div className="relative flex-1 h-6">
          <div className="absolute inset-0 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full w-full rounded-full transition-all duration-700 ease-out"
              style={{
                background: `conic-gradient(from 0deg, transparent 0%, #6b7280 ${needleDeg}%, transparent ${needleDeg + 2}%)`,
                transform: 'rotate(-90deg)',
              }}
            />
          </div>
          <div className="absolute inset-0 flex items-center justify-center">
            <div
              className="w-0.5 h-4 bg-gray-300 rounded transition-all duration-700 ease-out"
              style={{ transform: `rotate(${needleDeg - 90}deg)`, transformOrigin: 'bottom center' }}
            />
          </div>
          <div className="absolute -bottom-4 left-0 right-0 flex justify-between text-[8px] text-gray-600">
            <span>0</span>
            <span>0.5</span>
            <span>1</span>
          </div>
        </div>
        <span className="text-[10px] text-gray-400 font-mono w-8 text-right">{needleDeg > 50 ? '0.72' : '0.48'}</span>
      </div>
    </div>
  )
}
