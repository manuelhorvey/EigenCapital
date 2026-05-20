import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { usePortfolioState } from '../hooks/usePortfolioState'

export default function ConfidenceChart() {
  const { data } = usePortfolioState()

  const liveBuckets = useMemo(() => {
    if (!data?.assets) return []
    const agg: Record<string, number> = {}
    for (const [name, asset] of Object.entries(data.assets)) {
      const conf = asset.last_signal?.confidence ?? 0
      const lo = Math.floor(conf / 10) * 10
      const hi = lo + 10
      const key = `${lo}-${hi}`
      agg[key] = (agg[key] ?? 0) + 1
    }
    return Object.entries(agg)
      .sort(([a], [b]) => parseInt(a) - parseInt(b))
      .map(([range, count]) => ({ range, count }))
  }, [data])

  return (
    <div className="card-gradient card-border rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-2 h-2 rounded-full bg-emerald-500/50" />
        <h2 className="text-sm font-semibold text-primary">Confidence Distribution</h2>
      </div>
      {liveBuckets.length === 0 ? (
        <div className="text-xs text-tertiary text-center py-8">No signal data yet</div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={liveBuckets} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-panel)" />
              <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} axisLine={{ stroke: 'var(--color-border)' }} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} allowDecimals={false} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-card)',
                  border: '1px solid var(--color-border)',
                  borderRadius: '8px',
                  fontSize: '12px',
                  boxShadow: 'var(--shadow-lift)',
                }}
                labelStyle={{ color: 'var(--color-text-tertiary)' }}
              />
              <Bar dataKey="count" fill="#34d399" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
