import { useMemo } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from 'recharts'
import { useEquityHistory } from '../hooks/useEquityHistory'
import ChartContainer from './ui/ChartContainer'
import {
  axisTick,
  chartMargin,
  tooltipStyle,
  tooltipLabelStyle,
  cartesianGridProps,
} from './ui/chartTheme'

function formatPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}

/** Underwater drawdown chart showing the equity curve below the peak — negative area only. */
export default function DrawdownChart() {
  const { data, isPending } = useEquityHistory()

  const chartData = useMemo(() => {
    if (!data || data.length === 0) return []
    const raw = data
      .filter(d => d.drawdown != null && !isNaN(d.drawdown))
      .map(d => ({
        t: d.timestamp?.split('T')[0] ?? '',
        dd: d.drawdown * 100, // convert to percentage
      }))
    // Downsample to 2000 points max
    const MAX_POINTS = 2000
    if (raw.length <= MAX_POINTS) return raw
    const step = (raw.length - 1) / (MAX_POINTS - 1)
    const sampled: typeof raw = []
    for (let i = 0; i < MAX_POINTS; i++) {
      sampled.push(raw[Math.round(i * step)])
    }
    return sampled
  }, [data])

  const maxDD = chartData.length > 0
    ? Math.min(...chartData.map(d => d.dd))
    : 0

  const currentDD = chartData.length > 0
    ? chartData[chartData.length - 1].dd
    : 0

  const chartLabel = chartData.length > 0
    ? `Drawdown chart: maximum drawdown ${maxDD.toFixed(1)}%, current drawdown ${currentDD.toFixed(1)}%`
    : 'Drawdown chart'

  return (
    <ChartContainer
      title="Drawdown"
      accent="emerald"
      isPending={isPending}
      isEmpty={chartData.length === 0}
      emptyMessage="Waiting for equity history…"
      height="h-48"
      chartLabel={chartLabel}
      meta={
        <div className="flex items-center gap-2">
          <span className="text-2xs font-mono tabular-nums text-gov-red">
            Max DD {formatPct(maxDD)}
          </span>
          <span className="text-2xs font-mono tabular-nums" style={{ color: currentDD <= -5 ? 'var(--color-gov-red)' : currentDD <= -2 ? 'var(--color-gov-yellow)' : 'var(--color-gov-green)' }}>
            Now {formatPct(currentDD)}
          </span>
        </div>
      }
    >
      <p className="sr-only">{chartLabel}</p>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={chartMargin}>
          <defs>
            <linearGradient id="drawdown-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-gov-red)" stopOpacity={0.15} />
              <stop offset="100%" stopColor="var(--color-gov-red)" stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <ReferenceLine y={0} stroke="var(--color-border-strong)" strokeWidth={0.5} />
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
            domain={[maxDD * 1.1, 0]}
            axisLine={false}
            tickLine={false}
            width={48}
            tickFormatter={v => `${v.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            formatter={(value: number) => [`${value.toFixed(2)}%`, 'Drawdown']}
          />
          <Area
            type="monotone"
            dataKey="dd"
            stroke="var(--color-gov-red)"
            fill="url(#drawdown-fill)"
            fillOpacity={1}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
