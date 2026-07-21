import { useMemo } from 'react'
import { TrendingUp } from 'lucide-react'

interface TradePoint {
  side?: string | null
  entry_date?: string | null
  return?: number | null
  mae?: number | null
  mfe?: number | null
  entry?: number | null
  exit?: number | null
  reason?: string | null
  exit_date?: string | null
}

export default function MaeMfeScatter({ trades }: { trades: TradePoint[] }) {
  const scatterGlobalMax = useMemo(() => {
    if (trades.length === 0) return 1
    const mae = trades.map(t => Math.abs(t.mae ?? 0))
    const mfe = trades.map(t => Math.abs(t.mfe ?? 0))
    return Math.max(1, ...mae, ...mfe)
  }, [trades])

  return (
    <div className="bg-panel rounded-lg border border-default p-4 xl:col-span-2">
      <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
        <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
        MAE / MFE Scatter
      </h3>
      {trades.length === 0 ? (
        <div className="text-xs text-tertiary text-center py-8">No trades yet</div>
      ) : (
        <>
          <div className="relative h-64 w-full">
            <svg viewBox="0 0 400 400" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
              <line x1="50" y1="350" x2="350" y2="350" stroke="var(--color-border)" strokeWidth="1" />
              <line x1="50" y1="50" x2="50" y2="350" stroke="var(--color-border)" strokeWidth="1" />
              <line x1="50" y1="350" x2="350" y2="50" stroke="var(--color-signal-long)" strokeWidth="0.5" strokeDasharray="4 4" opacity="0.3" />
              {trades.map((t, i) => {
                const mae = Math.abs(t.mae ?? 0)
                const mfe = Math.abs(t.mfe ?? 0)
                const x = 50 + ((mae / scatterGlobalMax) * 280)
                const y = 350 - ((mfe / scatterGlobalMax) * 280)
                const isWin = (t.return ?? 0) > 0
                return (
                  <g key={i}>
                    <circle cx={x} cy={y} r="5" fill={isWin ? 'var(--color-signal-long)' : 'var(--color-signal-short)'} opacity="0.7">
                      <title>{`${t.side} ${t.entry_date}: MAE=${mae.toFixed(1)}% MFE=${mfe.toFixed(1)}% R=${t.return?.toFixed(2) ?? '?'}`}</title>
                    </circle>
                  </g>
                )
              })}
              <text x="200" y="380" textAnchor="middle" fill="var(--color-text-tertiary)" fontSize="10" fontFamily="var(--font-mono)">MAE (adverse excursion %)</text>
              <text x="20" y="200" textAnchor="middle" fill="var(--color-text-tertiary)" fontSize="10" fontFamily="var(--font-mono)" transform="rotate(-90, 20, 200)">MFE (favorable excursion %)</text>
            </svg>
          </div>
          <div className="flex items-center gap-4 mt-2 text-2xs text-tertiary">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-signal-long inline-block" /> Win</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-signal-short inline-block" /> Loss</span>
            <span className="text-muted">|</span>
            <span>{trades.length} trades</span>
          </div>
        </>
      )}
    </div>
  )
}