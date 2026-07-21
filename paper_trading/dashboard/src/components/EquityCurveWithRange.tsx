import { useState, useMemo } from 'react'
import Panel from './ui/Panel'
import ChartDataTable from './ui/ChartDataTable'
import { Skeleton } from './ui/Skeleton'
import { useEquityHistory } from '../hooks/useEquityHistory'

type TimeRange = '1D' | '1W' | '1M' | '3M' | 'YTD' | 'ALL'

const RANGES: TimeRange[] = ['1D', '1W', '1M', '3M', 'YTD', 'ALL']

const MS = {
  '1D': 86_400_000,
  '1W': 604_800_000,
  '1M': 2_592_000_000,
  '3M': 7_776_000_000,
  'YTD': Infinity,
  'ALL': Infinity,
}

function buildPath(values: number[], width: number, height: number) {
  if (values.length < 2) return { path: '', fillPath: '', isUp: true }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const stepX = width / (values.length - 1)
  const points = values.map((v, i) => ({
    x: i * stepX,
    y: height - ((v - min) / range) * height * 0.95 - height * 0.025,
  }))
  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const fill = `${line} L${points[points.length - 1].x},${height} L${points[0].x},${height} Z`
  return {
    path: line,
    fillPath: fill,
    isUp: values[values.length - 1] >= values[0],
    min,
    max,
    firstVal: values[0],
    lastVal: values[values.length - 1],
  }
}

function formatAxisLabel(value: number) {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`
  return `$${value.toFixed(0)}`
}

export default function EquityCurveWithRange() {
  const { data: history, isPending } = useEquityHistory()
  const [range, setRange] = useState<TimeRange>('1M')
  const [crosshair, setCrosshair] = useState<number | null>(null)

  const filtered = useMemo(() => {
    if (!history || history.length < 2) return history ?? []
    const cutoff = range === 'ALL' || range === 'YTD' ? 0 : Date.now() - MS[range]
    return history.filter((r) => new Date(r.timestamp).getTime() >= cutoff)
  }, [history, range])

  const svgWidth = 600
  const svgHeight = 200

  const { path, fillPath, isUp, min, max, firstVal, lastVal } = useMemo(
    () => buildPath(filtered.map((r) => r.portfolio_value), svgWidth, svgHeight),
    [filtered, svgWidth, svgHeight],
  )

  const returnPct = firstVal != null && firstVal > 0 && lastVal != null ? ((lastVal - firstVal) / firstVal * 100).toFixed(2) : '0.00'
  const color = isUp ? 'var(--color-signal-long)' : 'var(--color-signal-short)'

  if (isPending) {
    return (
      <Panel padding="md">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Equity Curve</span>
        </div>
        <Skeleton className="w-full h-[200px] rounded" shimmer />
      </Panel>
    )
  }

  if (!history || history.length < 2) {
    return null
  }

  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const pct = x / rect.width
    const idx = Math.round(pct * (filtered.length - 1))
    setCrosshair(filtered[idx]?.portfolio_value ?? null)
  }

  const crosshairIdx = crosshair != null
    ? filtered.findIndex((r) => r.portfolio_value === crosshair)
    : null

  return (
    <Panel padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Equity Curve</span>
          <div className="flex items-center gap-0.5 bg-surface rounded-md border border-default p-0.5">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold font-mono transition-colors duration-100 ease-out ${
                  range === r
                    ? 'bg-accent-emerald/10 text-accent-emerald border border-accent-emerald/20'
                    : 'text-tertiary hover:text-secondary border border-transparent'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-xs font-semibold font-mono tabular-nums" style={{ color }}>
            {isUp ? '+' : ''}{returnPct}%
          </span>
          <span className="text-[10px] text-tertiary">{lastVal != null ? formatAxisLabel(lastVal) : '—'}</span>
        </div>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="w-full"
          style={{ height: svgHeight }}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`Equity curve: ${returnPct}% return over ${filtered.length} data points`}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setCrosshair(null)}
        >
          <defs>
            <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.15} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          {fillPath && <path d={fillPath} fill="url(#eq-fill)" />}
          {path && (
            <path
              d={path}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {crosshairIdx != null && crosshair != null && (
            <>
              <line
                x1={(crosshairIdx / (filtered.length - 1)) * svgWidth}
                y1={0}
                x2={(crosshairIdx / (filtered.length - 1)) * svgWidth}
                y2={svgHeight}
                stroke="var(--color-text-tertiary)"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <circle
                cx={(crosshairIdx / (filtered.length - 1)) * svgWidth}
                cy={svgHeight - ((crosshair - (min ?? 0)) / ((max ?? 1) - (min ?? 0) || 1)) * svgHeight * 0.95 - svgHeight * 0.025}
                r={4}
                fill={color}
                stroke="var(--color-surface)"
                strokeWidth={2}
              />
            </>
          )}
        </svg>
        {crosshair != null && (
          <div className="absolute top-0 right-0 mt-1 mr-2 px-2 py-0.5 rounded bg-surface/90 border border-default text-[10px] font-mono tabular-nums text-secondary backdrop-blur-sm">
            {formatAxisLabel(crosshair)}
          </div>
        )}
      </div>
      <ChartDataTable
        title={`Equity curve — ${range}`}
        columns={[
          { key: 'timestamp', label: 'Time', format: v => new Date(v as string).toLocaleString() },
          { key: 'portfolio_value', label: 'Portfolio Value ($)', format: v => `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` },
        ]}
        data={filtered.slice(0, 500) as unknown as Record<string, unknown>[]}
        summary={`Equity curve with ${filtered.length} data points, return ${returnPct}%`}
      />
      <div className="flex items-center justify-between mt-2 text-[10px] text-tertiary font-mono">
        <span>{filtered.length} points</span>
        <span>{range === 'ALL' ? 'Full history' : `Last ${range}`}</span>
      </div>
    </Panel>
  )
}
