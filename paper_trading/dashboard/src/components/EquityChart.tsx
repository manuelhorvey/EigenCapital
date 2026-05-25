import { useMemo, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'
import { useEquityHistory } from '../hooks/useEquityHistory'
import ChartContainer from './ui/ChartContainer'
import {
  CHART_PALETTE,
  CHART_PRIMARY,
  axisTick,
  cartesianGridProps,
  chartMargin,
  tooltipLabelStyle,
  tooltipStyle,
  ChartGradientDefs,
  getGradientFill,
} from './ui/chartTheme'

function formatValue(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`
  return v.toFixed(0)
}

export default function EquityChart() {
  const { data, isPending } = useEquityHistory()
  const [selected, setSelected] = useState<Set<string>>(new Set(['portfolio']))

  const chartData = useMemo(
    () =>
      (data ?? []).map(d => ({
        t: d.timestamp?.split('T')[0] ?? '',
        portfolio: d.portfolio_value,
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

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const legend = (
    <div className="flex flex-wrap gap-1.5 mb-3 -mt-1">
      {['portfolio', ...assetNames].map(name => {
        const active = selected.has(name)
        const color =
          name === 'portfolio' ? CHART_PRIMARY : CHART_PALETTE[assetNames.indexOf(name) % CHART_PALETTE.length]
        return (
          <button
            key={name}
            type="button"
            onClick={() => toggle(name)}
            className={`px-2 py-1 rounded-md border text-2xs font-medium font-mono transition-all duration-150 ${
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
          <span className="text-2xs text-tertiary font-mono tabular-nums">{chartData.length} pts</span>
        </div>
      }
      toolbar={chartData.length > 0 ? legend : undefined}
      isPending={isPending}
      isEmpty={chartData.length === 0}
      emptyMessage="Waiting for equity history…"
      height="h-56 sm:h-64"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={chartMargin}>
          <ChartGradientDefs />
          <CartesianGrid {...cartesianGridProps} />
          <XAxis
            dataKey="t"
            tick={axisTick}
            interval="preserveStartEnd"
            axisLine={{ stroke: 'var(--color-border)', strokeWidth: 0.5 }}
            tickLine={false}
          />
          <YAxis
            tick={axisTick}
            domain={['auto', 'auto']}
            axisLine={false}
            tickLine={false}
            width={48}
            tickFormatter={formatValue}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            formatter={(value: number, name: string) => [
              `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
              name === 'portfolio' ? 'Portfolio' : name,
            ]}
            itemStyle={{ fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 0' }}
          />
          {firstVal > 0 && (
            <ReferenceLine
              y={firstVal}
              stroke="var(--color-text-muted)"
              strokeDasharray="4 4"
              strokeWidth={0.5}
              label={{
                value: 'Start',
                position: 'insideBottomRight',
                fill: 'var(--color-text-muted)',
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
              name="portfolio"
              dot={false}
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
                activeDot={{ stroke: CHART_PALETTE[i % CHART_PALETTE.length], strokeWidth: 2, r: 3, fill: 'var(--color-card)' }}
              />
            ) : null,
          )}
        </AreaChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
