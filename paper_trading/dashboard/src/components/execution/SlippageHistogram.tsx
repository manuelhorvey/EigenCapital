import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useExecutionSlippage } from '../../hooks/useExecutionSlippage'
import ChartContainer from '../ui/ChartContainer'

function bucketize(values: number[], bins = 10): { range: string; count: number; fill: string }[] {
  if (values.length === 0) return []
  const max = Math.max(...values.map(Math.abs), 1)
  const step = max / bins
  const counts = new Array(bins).fill(0)
  for (const v of values) {
    const idx = Math.min(Math.floor(Math.abs(v) / step), bins - 1)
    counts[idx]++
  }
  return counts.map((c, i) => ({
    range: `${(i * step).toFixed(1)}-${((i + 1) * step).toFixed(1)}`,
    count: c,
    fill: i < bins / 2 ? '#22c55e' : '#f97316',
  }))
}

export default function SlippageHistogram() {
  const { data, isPending } = useExecutionSlippage()

  const entryData = data ? bucketize(data.entry_slippage) : []
  const exitData = data ? bucketize(data.exit_slippage) : []
  const isEmpty = !data || data.n === 0

  return (
    <ChartContainer title="Slippage Distribution (bps)" accent="blue" isPending={isPending} isEmpty={isEmpty}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 h-full">
        <div className="min-w-0">
          <p className="text-2xs text-tertiary mb-1 font-medium">Entry Slippage</p>
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={entryData} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
              <XAxis dataKey="range" tick={{ fontSize: 8 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 8 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', borderRadius: 6, fontSize: 11 }} />
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {entryData.map((e, i) => <Cell key={i} fill={e.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="min-w-0">
          <p className="text-2xs text-tertiary mb-1 font-medium">Exit Slippage</p>
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={exitData} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
              <XAxis dataKey="range" tick={{ fontSize: 8 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 8 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', borderRadius: 6, fontSize: 11 }} />
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {exitData.map((e, i) => <Cell key={i} fill={e.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartContainer>
  )
}
