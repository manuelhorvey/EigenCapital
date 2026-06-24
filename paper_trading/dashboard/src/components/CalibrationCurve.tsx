import { useMemo } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { Skeleton } from './ui/Skeleton'
import EmptyState from './ui/EmptyState'

interface CalibrationPoint {
  asset: string
  confidence: number
  winRate: number
  sellOnly: boolean
  nTrades: number
  isBuyInverted: boolean
}

export default function CalibrationCurve() {
  const { data: bundle, isPending } = useSystemSnapshot()
  const state = bundle?.snapshot

  const points = useMemo(() => {
    if (!state?.assets) return []
    const result: CalibrationPoint[] = []

    for (const [name, asset] of Object.entries(state.assets)) {
      const m = asset.metrics
      if (!m || m.n_trades < 3) continue

      const conf = (m.mean_confidence ?? 0) * 100
      const wr = (m.win_rate ?? 0) * 100

      // Determine if BUY is inverted: SELL win rate >> BUY win rate
      let isBuyInverted = false
      if (asset.sell_only) {
        isBuyInverted = true
      }

      result.push({
        asset: name,
        confidence: Math.round(conf),
        winRate: Math.round(wr * 10) / 10,
        sellOnly: asset.sell_only ?? false,
        nTrades: m.n_trades ?? 0,
        isBuyInverted,
      })
    }

    result.sort((a, b) => a.confidence - b.confidence)
    return result
  }, [state])

  const normalPoints = points.filter(p => !p.sellOnly)
  const invertedPoints = points.filter(p => p.sellOnly)

  if (isPending) return <Skeleton className="h-64 rounded-lg" />
  if (points.length === 0) return <Panel><EmptyState message="Not enough trade data for calibration" compact /></Panel>

  return (
    <Panel padding="lg">
      <SectionHeader
        title="Probability Calibration"
        accent="purple"
        meta={
          <span className="text-2xs text-tertiary font-mono bg-surface px-2 py-0.5 rounded border border-default">
            {points.length} assets · {normalPoints.length} normal · {invertedPoints.length} SELL-only
          </span>
        }
      />
      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 30, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" strokeWidth={0.5} />
            <XAxis
              dataKey="confidence"
              name="Mean Confidence %"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }}
              label={{ value: 'Predicted Confidence %', position: 'bottom', fontSize: 10, fill: 'var(--color-text-tertiary)' }}
            />
            <YAxis
              dataKey="winRate"
              name="Win Rate %"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }}
              label={{ value: 'Actual Win Rate %', angle: -90, position: 'left', fontSize: 10, fill: 'var(--color-text-tertiary)', offset: 0 }}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                fontSize: '11px',
              }}
              formatter={(value: number, name: string) => [`${value}%`, name === 'winRate' ? 'Win Rate' : 'Confidence']}
              labelFormatter={(label: string) => label}
            />
            {/* Perfect calibration reference line */}
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
              stroke="var(--color-text-muted)"
              strokeWidth={1}
              strokeDasharray="4 4"
            />
            <Legend
              verticalAlign="top"
              height={30}
              formatter={(value: string) => (
                <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>{value}</span>
              )}
            />
            {/* Normal assets */}
            <Scatter
              name="Normal assets"
              data={normalPoints}
              fill="var(--color-accent-emerald)"
              stroke="var(--color-accent-emerald)"
              strokeWidth={0.5}
              shape="circle"
            />
            {/* SELL-only assets (potentially inverted BUY) */}
            <Scatter
              name="SELL-only assets"
              data={invertedPoints}
              fill="var(--color-gov-yellow)"
              stroke="var(--color-gov-yellow)"
              strokeWidth={0.5}
              shape="diamond"
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 mt-2 text-2xs text-tertiary">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-full bg-accent-emerald inline-block" />
          Normal assets
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 bg-gov-yellow inline-block rotate-45" />
          SELL-only assets
        </span>
        <span className="text-muted">·</span>
        <span>Dashed line = perfect calibration</span>
        <span className="text-muted">·</span>
        <span>Points below line = overconfident</span>
      </div>
    </Panel>
  )
}