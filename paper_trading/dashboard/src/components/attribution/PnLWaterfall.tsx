import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useAttributionWaterfall } from '../../hooks/useAttributionWaterfall'
import ChartContainer from '../ui/ChartContainer'

const COLORS = {
  prediction_pnl: '#22c55e',
  execution_cost: '#ef4444',
  exit_cost: '#f97316',
  friction_cost: '#a855f7',
}

export default function PnLWaterfall() {
  const { data, isPending } = useAttributionWaterfall()

  const chartData = data ? [
    { name: 'Prediction', value: data.prediction_pnl, fill: COLORS.prediction_pnl },
    { name: 'Execution\nCost', value: -data.execution_cost, fill: COLORS.execution_cost },
    { name: 'Exit\nCost', value: -data.exit_cost, fill: COLORS.exit_cost },
    { name: 'Friction\nCost', value: -data.friction_cost, fill: COLORS.friction_cost },
    { name: 'Net PnL', value: data.net_pnl, fill: data.net_pnl >= 0 ? '#22c55e' : '#ef4444' },
  ] : []

  return (
    <ChartContainer title="PnL Decomposition" accent="emerald" isPending={isPending} isEmpty={!data || data.n === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', borderRadius: 6, fontSize: 12 }}
            formatter={(value: number) => [`$${value.toFixed(2)}`, '']}
          />
          <Bar dataKey="value" radius={[2, 2, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
