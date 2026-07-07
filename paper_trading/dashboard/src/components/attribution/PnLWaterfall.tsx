import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useAttributionBundle } from '../../hooks/useAttributionBundle'
import ChartContainer from '../ui/ChartContainer'
import { axisTick, tooltipStyle } from '../ui/chartTheme'

const COLORS = {
  prediction_pnl: 'var(--color-gov-green)',
  execution_cost: 'var(--color-gov-red)',
  exit_cost: 'var(--color-gov-yellow)',
  friction_cost: 'var(--color-accent-purple)',
}

/** Waterfall bar chart decomposing net PnL into prediction, execution cost, exit cost, and friction cost contributions. */
export default function PnLWaterfall() {
  const { data: bundle, isPending } = useAttributionBundle()
  const data = bundle?.attributionWaterfall

  const chartData = data ? [
    { name: 'Prediction', value: data.prediction_pnl, fill: COLORS.prediction_pnl },
    { name: 'Execution\nCost', value: -data.execution_cost, fill: COLORS.execution_cost },
    { name: 'Exit\nCost', value: -data.exit_cost, fill: COLORS.exit_cost },
    { name: 'Friction\nCost', value: -data.friction_cost, fill: COLORS.friction_cost },
    { name: 'Net PnL', value: data.net_pnl, fill: data.net_pnl >= 0 ? 'var(--color-gov-green)' : 'var(--color-gov-red)' },
  ] : []
  const netPnl = data?.net_pnl ?? 0
  const chartLabel = data
    ? `PnL decomposition for ${data.n} closed trades. Net PnL ${netPnl.toFixed(2)} dollars.`
    : 'PnL decomposition chart'

  return (
    <ChartContainer
      title="PnL Decomposition"
      accent="emerald"
      isPending={isPending}
      isEmpty={!data || data.n === 0}
      emptyMessage="No closed trades yet — appears on exit"
      chartLabel={chartLabel}
    >
      <p className="sr-only">{chartLabel}</p>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis dataKey="name" tick={axisTick} axisLine={false} tickLine={false} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={tooltipStyle}
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
