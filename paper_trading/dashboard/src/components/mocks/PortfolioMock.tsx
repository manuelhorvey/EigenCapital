import { useMemo } from 'react'

interface Props {
  hovered?: boolean
}

const assets = [
  { name: 'XLF', signal: 'BUY', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
  { name: 'BTC', signal: 'SELL', color: 'text-red-400 bg-red-500/10 border-red-500/30' },
  { name: 'NZDJPY', signal: 'FLAT', color: 'text-amber-400 bg-amber-500/10 border-amber-500/30' },
]

const baseMatrix = [
  [1.0, 0.12, -0.08],
  [0.12, 1.0, -0.21],
  [-0.08, -0.21, 1.0],
]

function cellColor(v: number): string {
  if (v === 1.0) return 'bg-gray-500/40'
  if (v > 0) return 'bg-blue-500/30'
  if (v < 0) return 'bg-red-500/30'
  return 'bg-gray-500/20'
}

export default function PortfolioMock({ hovered }: Props) {
  const rows = useMemo(
    () =>
      baseMatrix.map((row, i) =>
        row.map((v, j) => ({
          v,
          color: cellColor(v),
          delay: hovered ? (i * 3 + j) * 50 : 0,
        })),
      ),
    [hovered],
  )

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {assets.map((a) => (
          <div key={a.name} className="flex items-center justify-between">
            <span className="text-[11px] text-gray-400 font-mono">{a.name}</span>
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold border ${a.color}`}>
              {a.signal}
            </span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-0.5 w-24 mx-auto">
        {rows.map((row, i) =>
          row.map((cell, j) => (
            <div
              key={`${i}-${j}`}
              className={`w-7 h-7 rounded ${cell.color} transition-all duration-300`}
              style={{
                opacity: hovered ? 1 : 0.3,
                transitionDelay: hovered ? `${cell.delay}ms` : '0ms',
              }}
            />
          )),
        )}
      </div>
    </div>
  )
}
