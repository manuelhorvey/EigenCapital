import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, ZAxis, Legend } from 'recharts'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import { useLiveAttribution } from '../../hooks/useLiveAttribution'
import ChartContainer from '../ui/ChartContainer'
import PanelFallback from '../ui/PanelFallback'
import { axisTick, tooltipStyle } from '../ui/chartTheme'

const ARCHETYPE_COLORS: Record<string, string> = {
  BREAKOUT: 'var(--color-gov-green)',
  MEAN_REVERSION: 'var(--color-accent-blue)',
  MOMENTUM: 'var(--color-accent-purple)',
  VOL_EXPANSION: 'var(--color-gov-yellow)',
  UNKNOWN: 'var(--color-text-muted)',
  LIVE: 'var(--color-accent-purple)',
}

// Distinct marker shapes per archetype so the chart remains readable for
// colour-blind users — never encode information by colour alone.
const ARCHETYPE_SHAPES: Record<string, 'circle' | 'cross' | 'diamond' | 'square' | 'star' | 'triangle' | 'wye'> = {
  BREAKOUT: 'circle',
  MEAN_REVERSION: 'triangle',
  MOMENTUM: 'square',
  VOL_EXPANSION: 'cross',
  UNKNOWN: 'diamond',
  LIVE: 'star',
}

const ARCHETYPE_ORDER = ['BREAKOUT', 'MEAN_REVERSION', 'MOMENTUM', 'VOL_EXPANSION', 'UNKNOWN', 'LIVE'] as const

export default function MaeMfeScatter() {
  const { data, isPending, isError, error, refetch } = useAttributionTrades(200)
  const live = useLiveAttribution()
  const liveError = live.isError

  if (isError || liveError) {
    return <PanelFallback title="MAE / MFE Scatter" error={error ?? live.error ?? undefined} onRetry={() => { refetch(); live.refetch() }} />
  }

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

  const livePoints = (live.data ?? [])
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
            formatter={(value, name) => [typeof value === 'number' ? value.toFixed(2) : String(value), name]}
          />
          <Legend
            iconType="circle"
            iconSize={6}
            wrapperStyle={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}
            formatter={(value) => <span style={{ color: 'var(--color-text-tertiary)' }}>{value}</span>}
          />
          {ARCHETYPE_ORDER.map((arch) => {
              const points = allData.filter(p => (p.isLive ? 'LIVE' : p.archetype ?? 'UNKNOWN') === arch)
              if (points.length === 0) return null
              return (
                <Scatter
                  key={arch}
                  name={arch}
                  data={points}
                  shape={ARCHETYPE_SHAPES[arch] ?? 'circle'}
                  fill={ARCHETYPE_COLORS[arch] ?? 'var(--color-text-muted)'}
                  stroke={ARCHETYPE_COLORS[arch] ?? 'var(--color-text-muted)'}
                  fillOpacity={arch === 'LIVE' ? 0.4 : 0.7}
                  strokeOpacity={arch === 'LIVE' ? 0.5 : 1}
                  isAnimationActive={false}
                />
              )
          })}
        </ScatterChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
