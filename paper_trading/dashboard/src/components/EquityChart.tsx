import { useMemo, useState, useEffect } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import type { EquityHistoryPoint } from '../types/portfolio'

async function fetchEquity(): Promise<EquityHistoryPoint[]> {
  const res = await fetch('/equity_history.json')
  if (!res.ok) return []
  return res.json()
}

const COLORS = ['#34d399', '#f87171', '#fbbf24', '#60a5fa', '#a78bfa', '#f472b6', '#2dd4bf', '#fb923c', '#94a3b8', '#e879f9', '#22d3ee']

export default function EquityChart() {
  const [data, setData] = useState<EquityHistoryPoint[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set(['portfolio']))

  useEffect(() => {
    fetchEquity().then(d => {
      setData(d)
      if (d.length > 0) {
        setSelected(prev => {
          const next = new Set(prev)
          next.add('portfolio')
          Object.keys(d[0].assets ?? {}).forEach(a => next.add(a))
          return next
        })
      }
    })
    const id = setInterval(() => {
      fetchEquity().then(d => {
        setData(d)
        if (d.length > 0) {
          setSelected(prev => {
            const next = new Set(prev)
            Object.keys(d[0].assets ?? {}).forEach(a => next.add(a))
            return next
          })
        }
      })
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  const chartData = useMemo(() => data.map(d => ({
    t: d.timestamp?.split('T')[0] ?? '',
    portfolio: d.portfolio_value,
    ...d.assets,
  })), [data])

  const assetNames = useMemo(() => {
    if (data.length === 0) return []
    return Object.keys(data[0].assets ?? {}).sort()
  }, [data])

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  if (chartData.length === 0) {
    return (
      <div className="card-gradient card-border rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-emerald-500/50" />
          <h2 className="text-sm font-semibold text-primary">Equity Curve</h2>
        </div>
        <div className="text-xs text-tertiary text-center py-8">Waiting for data...</div>
      </div>
    )
  }

  return (
    <div className="card-gradient card-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500/50" />
          <h2 className="text-sm font-semibold text-primary">Equity Curve</h2>
        </div>
        <span className="text-[11px] text-tertiary">{chartData.length} data points</span>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-4">
        {['portfolio', ...assetNames].map(name => {
          const active = selected.has(name)
          const color = name === 'portfolio' ? '#34d399' : COLORS[assetNames.indexOf(name) % COLORS.length]
          return (
            <button
              key={name}
              onClick={() => toggle(name)}
              className={`px-2 py-1 rounded-lg border text-[10px] font-medium transition-all duration-200 ${
                active
                  ? 'text-primary bg-panel border-strong'
                  : 'text-tertiary border-default hover:border-strong hover:text-secondary'
              }`}
            >
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: active ? color : 'var(--color-text-muted)' }} />
                {name}
              </span>
            </button>
          )
        })}
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-panel)" />
            <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} interval="preserveStartEnd" axisLine={{ stroke: 'var(--color-border)' }} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} domain={['auto', 'auto']} axisLine={false} tickLine={false} />
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
            {selected.has('portfolio') && (
              <Area type="monotone" dataKey="portfolio" stroke="#34d399" fill="#34d399" fillOpacity={0.08} strokeWidth={2} name="Portfolio" />
            )}
            {assetNames.map((a, i) =>
              selected.has(a) ? (
                <Area key={a} type="monotone" dataKey={a} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.04} strokeWidth={1.5} name={a} />
              ) : null
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
