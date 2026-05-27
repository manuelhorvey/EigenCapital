import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, ZAxis, Cell } from 'recharts'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import ChartContainer from '../ui/ChartContainer'

const ARCHETYPE_COLORS: Record<string, string> = {
  BREAKOUT: '#22c55e',
  MEAN_REVERSION: '#3b82f6',
  MOMENTUM: '#a855f7',
  VOL_EXPANSION: '#f97316',
  UNKNOWN: '#6b7280',
}

export default function MaeMfeScatter() {
  const { data, isPending } = useAttributionTrades(200)
  const isEmpty = !data || data.length === 0

  const chartData = (data ?? [])
    .filter(t => t.exit_mae > 0 || t.exit_mfe > 0)
    .map(t => ({
      mae: t.exit_mae,
      mfe: t.exit_mfe,
      archetype: t.pred_archetype_at_entry,
      r: t.exit_realized_r,
      asset: t.asset,
      trade_id: t.trade_id,
    }))

  return (
    <ChartContainer title="MAE / MFE Scatter" accent="emerald" isPending={isPending} isEmpty={isEmpty}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis
            dataKey="mae"
            type="number"
            name="MAE"
            tick={{ fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            label={{ value: 'MAE', position: 'bottom', fontSize: 10, fill: '#6b7280' }}
          />
          <YAxis
            dataKey="mfe"
            type="number"
            name="MFE"
            tick={{ fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            label={{ value: 'MFE', angle: -90, position: 'left', fontSize: 10, fill: '#6b7280' }}
          />
          <ZAxis dataKey="r" range={[20, 80]} name="R" />
          <Tooltip
            contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', borderRadius: 6, fontSize: 11 }}
            formatter={(value: number, name: string) => [value.toFixed(2), name]}
          />
          <Scatter data={chartData}>
            {chartData.map((point, i) => (
              <Cell key={point.trade_id || i} fill={ARCHETYPE_COLORS[point.archetype] ?? '#6b7280'} fillOpacity={0.7} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
