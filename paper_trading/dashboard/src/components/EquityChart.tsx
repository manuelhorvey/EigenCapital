import { useCallback, useMemo, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, ReferenceDot } from 'recharts'
import { useEquityHistory } from '../hooks/useEquityHistory'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import type { SystemBundle } from '../types/bundle'
import ChartContainer from './ui/ChartContainer'
import {
  CHART_PALETTE,
  CHART_PRIMARY,
  axisTick,
  cartesianGridProps,
  chartMargin,
  tooltipLabelStyle,
  tooltipStyle,
  chartCursor,
  ChartGradientDefs,
  getGradientFill,
} from './ui/chartTheme'

function formatValue(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`
  return v.toFixed(0)
}

const capitalSelector = (b: SystemBundle) => b.snapshot.portfolio.capital

/** Interactive equity curve chart with per-asset toggle, max-DD annotation, and baseline reference. */
export default function EquityChart() {
  const { data, isPending } = useEquityHistory()
  const { data: capital } = useSystemSnapshot(capitalSelector)
  const [selected, setSelected] = useState<Set<string>>(new Set(['portfolio']))

  const MAX_POINTS = 200

  const chartData = useMemo(
    () =>
      (data ?? [])
        .slice(-MAX_POINTS)
        .filter(d => d.portfolio_value != null && !isNaN(d.portfolio_value))
        .map(d => ({
          t: d.timestamp?.split('T')[0] ?? '',
          portfolio: d.portfolio_value,
          drawdown: d.drawdown,
          ...d.assets,
        })),
    [data],
  )

  const assetNames = useMemo(() => {
    if (!data || data.length === 0) return []
    return Object.keys(data[0].assets ?? {}).sort()
  }, [data])

  const firstVal = chartData.length > 0 ? chartData[0].portfolio : 0
  const lastVal = chartData.length > 0 ? chartData[chartData.length - 1].portfolio : 0
  const pctChange = firstVal > 0 ? ((lastVal - firstVal) / firstVal) * 100 : 0
  const startingCapital = data?.[0]?.portfolio_value ?? capital ?? firstVal
  const latestDrawdown = chartData.length > 0 ? chartData[chartData.length - 1].drawdown : null

  const minPoint = useMemo(() => {
    if (chartData.length === 0) return null
    let min = Infinity
    let minIdx = 0
    for (let i = 0; i < chartData.length; i++) {
      if (chartData[i].portfolio < min) {
        min = chartData[i].portfolio
        minIdx = i
      }
    }
    return { index: minIdx, value: min, date: chartData[minIdx].t }
  }, [chartData])

  const maxDD = minPoint && firstVal > 0 ? ((minPoint.value - firstVal) / firstVal) * 100 : 0

  const latestValues = useMemo(() => {
    if (chartData.length === 0) return {}
    const last = chartData[chartData.length - 1]
    const result: Record<string, number> = { portfolio: last.portfolio }
    for (const name of assetNames) {
      const v = (last as Record<string, unknown>)[name]
      if (typeof v === 'number') result[name] = v
    }
    return result
  }, [chartData, assetNames])

  const toggle = useCallback((name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  const legend = (
    <div className="flex flex-wrap gap-1.5 mb-3 -mt-1">
      {['portfolio', ...assetNames].map(name => {
        const active = selected.has(name)
        const color =
          name === 'portfolio' ? CHART_PRIMARY : CHART_PALETTE[assetNames.indexOf(name) % CHART_PALETTE.length]
        const latest = latestValues[name]
        return (
          <button
            key={name}
            type="button"
            onClick={() => toggle(name)}
            aria-pressed={active}
            aria-label={`${active ? 'Hide' : 'Show'} ${name} on equity chart`}
            className={`px-2 py-1 rounded-md border text-2xs font-medium font-mono transition-all duration-150 focus-ring ${
              active
                ? 'text-primary bg-panel border-strong shadow-inner-subtle'
                : 'text-muted border-default hover:border-strong hover:text-secondary'
            }`}

          >
            <span className="flex items-center gap-1.5">
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ backgroundColor: active ? color : 'var(--color-text-muted)' }}
              />
              {name}
              {active && latest != null && (
                <span className="text-muted tabular-nums">{formatValue(latest)}</span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )

  return (
    <ChartContainer
      title="Equity Curve"
      accent="emerald"
      meta={
        <div className="flex items-center gap-2">
          {chartData.length > 0 && (
            <span className={`text-2xs font-mono tabular-nums ${pctChange >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
              {pctChange >= 0 ? '+' : ''}{pctChange.toFixed(2)}%
            </span>
          )}
          {latestDrawdown != null && (
            <span className="hidden sm:inline text-2xs text-tertiary font-mono tabular-nums">
              DD {latestDrawdown.toFixed(1)}%
            </span>
          )}
          <span className="text-2xs text-tertiary font-mono tabular-nums">{chartData.length} pts</span>
        </div>
      }
      toolbar={chartData.length > 0 ? legend : undefined}
      isPending={isPending}
      isEmpty={chartData.length === 0}
      emptyMessage="Waiting for equity history…"
      height="h-56 sm:h-64"
      chartLabel={`Equity curve with ${chartData.length} points; visible portfolio change ${pctChange.toFixed(2)} percent`}
    >
      <div className="relative h-full w-full">
        <p className="sr-only">
          Equity chart showing {chartData.length} points. Portfolio changed {pctChange.toFixed(2)} percent over the visible range.
          {latestDrawdown != null ? ` Latest drawdown is ${latestDrawdown.toFixed(1)} percent.` : ''}
        </p>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={chartMargin}>
            <ChartGradientDefs />
            <CartesianGrid {...cartesianGridProps} />
            <XAxis
              dataKey="t"
              tick={axisTick}
              interval="preserveStartEnd"
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
            />
            <YAxis
              tick={axisTick}
              domain={['auto', 'auto']}
              axisLine={false}
              tickLine={false}
              width={48}
              tickFormatter={v => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              labelStyle={tooltipLabelStyle}
              itemStyle={{ fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 0' }}
              cursor={chartCursor}
            />
            {chartData.length > 0 && (
              <ReferenceLine
                y={startingCapital}
                stroke="var(--color-text-muted)"
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{
                  value: 'Baseline',
                  position: 'insideBottomRight',
                  fill: 'var(--color-text-tertiary)',
                  fontSize: 9,
                  fontFamily: 'var(--font-mono)',
                }}
              />
            )}
            {minPoint && selected.has('portfolio') && (
              <ReferenceDot
                x={minPoint.date}
                y={minPoint.value}
                r={4}
                fill="var(--color-gov-red)"
                stroke="var(--color-card)"
                strokeWidth={2}
                label={{
                  value: `Max DD ${maxDD.toFixed(1)}%`,
                  position: 'bottom',
                  fill: 'var(--color-gov-red)',
                  fontSize: 9,
                  fontFamily: 'var(--font-mono)',
                }}
              />
            )}
            {selected.has('portfolio') && (
              <Area
                type="monotone"
                dataKey="portfolio"
                stroke={CHART_PRIMARY}
                fill={getGradientFill()}
                fillOpacity={1}
                strokeWidth={2}
                name="Portfolio"
                dot={false}
                isAnimationActive={false}
                activeDot={{ stroke: CHART_PRIMARY, strokeWidth: 2, r: 4, fill: 'var(--color-card)' }}
              />
            )}
            {assetNames.map((a, i) =>
              selected.has(a) ? (
                <Area
                  key={a}
                  type="monotone"
                  dataKey={a}
                  stroke={CHART_PALETTE[i % CHART_PALETTE.length]}
                  fill={CHART_PALETTE[i % CHART_PALETTE.length]}
                  fillOpacity={0.04}
                  strokeWidth={1.5}
                  name={a}
                  dot={false}
                  isAnimationActive={false}
                  activeDot={{ stroke: CHART_PALETTE[i % CHART_PALETTE.length], strokeWidth: 2, r: 3, fill: 'var(--color-card)' }}
                />
              ) : null,
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </ChartContainer>
  )
}
