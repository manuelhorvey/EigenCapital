import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, ZAxis, Cell } from 'recharts'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import { useLiveAttribution } from '../../hooks/useLiveAttribution'
import ChartContainer from '../ui/ChartContainer'
import { axisTick, tooltipStyle } from '../ui/chartTheme'

const ARCHETYPE_COLORS: Record<string, string> = {
  BREAKOUT: 'var(--color-gov-green)',
  MEAN_REVERSION: 'var(--color-accent-blue)',
  MOMENTUM: 'var(--color-accent-purple)',
  VOL_EXPANSION: 'var(--color-gov-yellow)',
  UNKNOWN: 'var(--color-text-muted)',
}

/** Scatter plot of maximum adverse excursion (MAE) vs maximum favorable excursion (MFE) per trade, colored by archetype with live positions overlaid. */
export default function MaeMfeScatter() {
  const { data, isPending } = useAttributionTrades(200)
  const { data: liveData } = useLiveAttribution()

  const chartData = (data ?? [])
    .filter(t => t.exit_mae > 0 || t.exit_mfe > 0)
    .map(t => ({
      mae: t.exit_mae,
      mfe: t.exit_mfe,
      archetype: t.pred_archetype_at_entry,
      r: t.exit_realized_r,
      asset: t.asset,
      trade_id: t.trade_id,
      isLive: false as const,
    }))

  const livePoints = (liveData ?? [])
    .filter(p => p.running_mae != null && p.running_mfe != null)
    .map(p => ({
      mae: p.running_mae!,
      mfe: p.running_mfe!,
      archetype: 'LIVE',
      r: 0,
      asset: p.asset,
      trade_id: `live-${p.asset}`,
      isLive: true as const,
    }))

  const allData = [...chartData, ...livePoints]
  const isEmpty = allData.length === 0
  const worstMae = allData.length ? Math.max(...allData.map(p => p.mae)) : 0
  const bestMfe = allData.length ? Math.max(...allData.map(p => p.mfe)) : 0
  const chartLabel = `MAE MFE scatter with ${allData.length} trades; worst adverse excursion ${worstMae.toFixed(2)}, best favorable excursion ${bestMfe.toFixed(2)}.`

  return (
    <ChartContainer
      title="MAE / MFE Scatter"
      accent="emerald"
      isPending={isPending}
      isEmpty={isEmpty}
      emptyMessage="No closed trades yet — appears on exit"
      chartLabel={chartLabel}
    >
      <p className="sr-only">{chartLabel}</p>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis
            dataKey="mae"
            type="number"
            name="MAE"
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            label={{ value: 'MAE', position: 'bottom', fontSize: 10, fill: 'var(--color-text-tertiary)' }}
          />
          <YAxis
            dataKey="mfe"
            type="number"
            name="MFE"
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            label={{ value: 'MFE', angle: -90, position: 'left', fontSize: 10, fill: 'var(--color-text-tertiary)' }}
          />
          <ZAxis dataKey="r" range={[20, 80]} name="R" />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: number, name: string) => [value.toFixed(2), name]}
          />
          <Scatter data={allData}>
            {allData.map((point, i) => (
              <Cell
                key={point.trade_id || i}
                fill={point.isLive ? 'var(--color-accent-purple)' : (ARCHETYPE_COLORS[point.archetype] ?? 'var(--color-text-muted)')}
                fillOpacity={point.isLive ? 0.4 : 0.7}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
