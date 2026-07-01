import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

interface EquityRecord {
  id: number
  timestamp: string
  portfolio_value: number
  portfolio_return?: number
  drawdown?: number
}

interface EquityCurveSparklineProps {
  /** Height in pixels. Default 72. */
  height?: number
  /** Width in pixels. Default 100%. */
  width?: number | string
  /** Color for positive curve segments. */
  positiveColor?: string
  /** Color for negative curve segments. */
  negativeColor?: string
  /** Stroke width. Default 2. */
  strokeWidth?: number
  /** Show mini axis labels on hover-equivalent area. Default false. */
  showLabels?: boolean
}

function buildPath(
  values: number[],
  width: number,
  height: number,
): { path: string; fillPath: string; isUp: boolean } {
  if (values.length < 2) return { path: '', fillPath: '', isUp: true }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const stepX = width / (values.length - 1)

  const points = values.map((v, i) => ({
    x: i * stepX,
    y: height - ((v - min) / range) * height * 0.85 - height * 0.075,
  }))

  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const fill = `${line} L${points[points.length - 1].x},${height} L${points[0].x},${height} Z`

  return {
    path: line,
    fillPath: fill,
    isUp: values[values.length - 1] >= values[0],
  }
}

function formatAxisLabel(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`
  return `$${value.toFixed(0)}`
}

export default function EquityCurveSparkline({
  height = 72,
  width,
  positiveColor = '#22c55e',
  negativeColor = '#ef4444',
  strokeWidth = 2,
  showLabels = false,
}: EquityCurveSparklineProps) {
  const { data: history, isLoading } = useQuery<EquityRecord[]>({
    queryKey: ['equity_history'],
    queryFn: () => fetchApi<EquityRecord[]>('/equity_history.json'),
    refetchInterval: 60_000,
    staleTime: 60_000,
    retry: 1,
  })

  const { path, fillPath, isUp } = useMemo(() => {
    if (!history || history.length < 2) return { path: '', fillPath: '', isUp: true }
    const values = history.map((r) => r.portfolio_value)
    return buildPath(values, typeof width === 'number' ? width : 300, height)
  }, [history, width, height])

  if (isLoading) {
    return <div style={{ height }}><Skeleton className="w-full h-full rounded" shimmer /></div>
  }

  if (!history || history.length < 2) {
    return (
      <Panel padding="md">
        <EmptyState message="No equity history yet" compact />
      </Panel>
    )
  }

  const lastVal = history[history.length - 1].portfolio_value
  const firstVal = history[0].portfolio_value
  const returnPct = firstVal > 0 ? ((lastVal - firstVal) / firstVal * 100).toFixed(2) : '0.00'
  const color = isUp ? positiveColor : negativeColor

  return (
    <div className="flex items-end gap-3">
      <svg
        viewBox={`0 0 ${300} ${height}`}
        className="w-full shrink-0"
        style={{ height, maxWidth: typeof width === 'number' ? width : undefined }}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Equity curve: ${returnPct}% return`}
      >
        <defs>
          <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.2} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {fillPath && <path d={fillPath} fill="url(#equity-fill)" />}
        {path && (
          <path
            d={path}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
      </svg>
      <div className="flex flex-col shrink-0 text-right min-w-[72px]">
        <span className="text-xs font-semibold font-mono tabular-nums" style={{ color }}>
          {isUp ? '+' : ''}{returnPct}%
        </span>
        <span className="text-[10px] text-tertiary">{formatAxisLabel(lastVal)}</span>
        {showLabels && (
          <>
            <span className="text-[10px] text-tertiary/60">{history.length} points</span>
            <span className="text-[10px] text-tertiary/60">Peak: {formatAxisLabel(Math.max(...history.map(r => r.portfolio_value)))}</span>
          </>
        )}
      </div>
    </div>
  )
}
