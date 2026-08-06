import { useMemo, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, ReferenceDot } from 'recharts'
import { useEquityHistory } from '../hooks/useEquityHistory'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
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

type RangeKey = '1d' | '1w' | '1m' | '3m' | '6m' | '1y' | 'all'

const RANGE_PRESETS: { key: RangeKey; label: string; title: string; days: number | null }[] = [
  { key: '1w', label: '1W', title: '1 week', days: 7 },
  { key: '1m', label: '1M', title: '1 month', days: 30 },
  { key: '3m', label: '3M', title: '3 months', days: 90 },
  { key: '6m', label: '6M', title: '6 months', days: 180 },
  { key: 'all', label: 'All', title: 'All time', days: null },
]

const COMPACT_PRESETS: { key: RangeKey; label: string; title: string; days: number | null }[] = [
  { key: '1d', label: 'D', title: 'Daily', days: 1 },
  { key: '1w', label: 'W', title: 'Weekly', days: 7 },
  { key: '1m', label: 'M', title: 'Monthly', days: 30 },
  { key: '1y', label: 'Y', title: 'Yearly', days: 365 },
]

const DAY_MS = 24 * 60 * 60 * 1000

export default function EquityChart({ compact = false }: { compact?: boolean }) {
  const { data, isPending } = useEquityHistory()
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const state = snapshot
  const [selected, setSelected] = useState<Set<string>>(new Set(['portfolio']))
  const [range, setRange] = useState<RangeKey>(() => (compact ? '1m' : 'all'))

  const chartData = useMemo(() => {
    const raw = (data ?? [])
      .filter(d => d.portfolio_value != null && !isNaN(d.portfolio_value))
      .map(d => ({
        t: d.timestamp?.split('T')[0] ?? '',
        ts: d.timestamp ? new Date(d.timestamp).getTime() : 0,
        portfolio: d.portfolio_value,
        drawdown: d.drawdown,
        ...d.assets,
      }))
    const preset = (compact ? COMPACT_PRESETS : RANGE_PRESETS).find(r => r.key === range)
    if (!preset || preset.days == null) return raw
    const cutoff = Date.now() - preset.days * DAY_MS
    const filtered = raw.filter(d => d.ts >= cutoff)
    // Keep at least one point so the chart never renders empty for a valid range
    return filtered.length > 0 ? filtered : raw.slice(-1)
  }, [data, range, compact])

  const assetNames = useMemo(() => {
    if (!data || data.length === 0) return []
    return Object.keys(data[0].assets ?? {}).sort()
  }, [data])

  const firstVal = chartData.length > 0 ? chartData[0].portfolio : 0
  const lastVal = chartData.length > 0 ? chartData[chartData.length - 1].portfolio : 0
  const pctChange = firstVal > 0 ? ((lastVal - firstVal) / firstVal) * 100 : 0
  const startingCapital = data?.[0]?.portfolio_value ?? state?.portfolio?.capital ?? firstVal
  const latestDrawdown = chartData.length > 0 ? chartData[chartData.length - 1].drawdown : null

  // State-aware colour: green above baseline, red below (profit vs drawdown).
  const aboveBase = lastVal >= startingCapital
  const curveColor = aboveBase ? 'var(--color-gov-green)' : 'var(--color-gov-red)'
  const equityGradId = 'equityCurveGradient'

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

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const presets = compact ? COMPACT_PRESETS : RANGE_PRESETS

  const rangeSelector = (
    <div className="flex items-center gap-0.5 rounded-md border border-default bg-surface p-0.5" role="group" aria-label="Time range">
      {presets.map(r => (
        <button
          key={r.key}
          type="button"
          onClick={() => setRange(r.key)}
          title={r.title}
          aria-pressed={range === r.key}
          className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-semibold transition-all focus-ring ${
            range === r.key
              ? 'bg-brand-soft text-brand'
              : 'text-tertiary hover:text-secondary'
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  )

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
      toolbar={
        compact
          ? (
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2 -mt-1">
              {chartData.length > 0 && rangeSelector}
            </div>
          )
          : (
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3 -mt-1">
              {chartData.length > 0 ? legend : <span />}
              {chartData.length > 0 && rangeSelector}
            </div>
          )
      }
      isPending={isPending}
      isEmpty={chartData.length === 0}
      emptyMessage="Waiting for equity history…"
      height={compact ? 'h-36' : 'h-56 sm:h-64'}
      chartLabel={`Equity curve with ${chartData.length} points; visible portfolio change ${pctChange.toFixed(2)} percent`}
    >
      <div className="relative h-full w-full">
        <p className="sr-only">
          Equity chart showing {chartData.length} points. Portfolio changed {pctChange.toFixed(2)} percent over the visible range.
          {latestDrawdown != null ? ` Latest drawdown is ${latestDrawdown.toFixed(1)} percent.` : ''}
        </p>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={chartMargin}>
            <ChartGradientDefs id={equityGradId} color={curveColor} />
            <CartesianGrid {...cartesianGridProps} />
            <XAxis
              dataKey="t"
              tick={compact ? false : axisTick}
              height={compact ? 4 : 30}
              interval="preserveStartEnd"
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
            />
            <YAxis
              tick={compact ? false : axisTick}
              domain={['auto', 'auto']}
              axisLine={false}
              tickLine={false}
              width={compact ? 4 : 48}
              tickFormatter={v => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              labelStyle={tooltipLabelStyle}
              itemStyle={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-primary)', padding: '1px 0' }}
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
                stroke={curveColor}
                fill={getGradientFill(equityGradId)}
                fillOpacity={1}
                strokeWidth={2}
                name="Portfolio"
                dot={false}
                isAnimationActive={false}
                activeDot={{ stroke: curveColor, strokeWidth: 2, r: 4, fill: 'var(--color-card)' }}
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
