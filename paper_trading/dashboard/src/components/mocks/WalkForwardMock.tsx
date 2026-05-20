import { useMemo } from 'react'

interface Props {
  hovered?: boolean
}

const bars = [
  { year: '2021', pf: 1.02, color: 'bg-emerald-500' },
  { year: '2022', pf: 0.89, color: 'bg-amber-500' },
  { year: '2023', pf: 1.12, color: 'bg-emerald-500' },
  { year: '2024', pf: 1.23, color: 'bg-emerald-500' },
  { year: '2025', pf: 1.34, color: 'bg-emerald-500' },
  { year: '2026', pf: 1.41, color: 'bg-emerald-500' },
]

export default function WalkForwardMock({ hovered }: Props) {
  const heights = bars.map(() => 30 + Math.random() * 40)

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-center gap-1.5 h-24">
        {bars.map((b, i) => (
          <div key={b.year} className="flex flex-col items-center gap-1">
            <span className="text-[8px] text-gray-500 font-mono">{b.pf.toFixed(2)}</span>
            <div
              className={`w-6 rounded-t ${b.color} transition-all duration-500 ease-out`}
              style={{
                height: hovered ? `${heights[i]}px` : '0px',
                transitionDelay: hovered ? `${i * 60}ms` : '0ms',
              }}
            />
            <span className="text-[8px] text-gray-600">{b.year.slice(2)}</span>
          </div>
        ))}
      </div>

      <div className="flex justify-center">
        <span className="px-2 py-0.5 rounded text-[9px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
          Avg Sharpe 1.30
        </span>
      </div>
    </div>
  )
}
