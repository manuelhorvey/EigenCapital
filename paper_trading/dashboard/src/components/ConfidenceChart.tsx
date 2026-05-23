import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { useQuery } from '@tanstack/react-query'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import {
  CHART_PRIMARY,
  axisTick,
  cartesianGridProps,
  chartMargin,
  tooltipLabelStyle,
  tooltipStyle,
} from './ui/chartTheme'

async function fetchConfidence(): Promise<{
  live: Record<string, Record<string, number>>
  historical: Record<string, number>[]
}> {
  const res = await fetch('/confidence.json')
  if (!res.ok) return { live: {}, historical: [] }
  return res.json()
}

function aggregateBuckets(live: Record<string, Record<string, number>>): { range: string; count: number }[] {
  const agg: Record<string, number> = {}
  for (const assetBuckets of Object.values(live)) {
    for (const [range, count] of Object.entries(assetBuckets)) {
      agg[range] = (agg[range] ?? 0) + count
    }
  }
  return Object.entries(agg)
    .sort(([a], [b]) => parseInt(a) - parseInt(b))
    .map(([range, count]) => ({ range, count }))
}

export default function ConfidenceChart() {
  const { data: apiData, isPending } = useQuery({
    queryKey: ['confidenceDistribution'],
    queryFn: fetchConfidence,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })

  const liveBuckets = useMemo(() => {
    if (!apiData?.live) return []
    return aggregateBuckets(apiData.live)
  }, [apiData])

  const historicalCount = useMemo(() => {
    if (!apiData?.historical || apiData.historical.length === 0) return null
    const agg: Record<string, number> = {}
    for (const entry of apiData.historical) {
      for (const [range, count] of Object.entries(entry)) {
        if (range === 'date') continue
        agg[range] = (agg[range] ?? 0) + (count as number)
      }
    }
    const total = Object.values(agg).reduce((s, v) => s + v, 0)
    return { buckets: agg, total }
  }, [apiData])

  const showHistorical = historicalCount && historicalCount.total > 0
  const isEmpty = liveBuckets.length === 0 && !showHistorical

  return (
    <Panel padding="md">
      <SectionHeader title="Confidence Distribution" accent="emerald" />
      {isPending ? (
        <Skeleton className="h-32 w-full rounded-md" />
      ) : isEmpty ? (
        <EmptyState message="No signal data yet" compact />
      ) : (
        <div className="h-32 chart-surface rounded-md p-1">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={liveBuckets} margin={chartMargin}>
              <CartesianGrid {...cartesianGridProps} />
              <XAxis dataKey="range" tick={axisTick} axisLine={false} tickLine={false} />
              <YAxis
                tick={axisTick}
                allowDecimals={false}
                axisLine={false}
                tickLine={false}
                width={20}
              />
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={{ fontFamily: 'var(--font-mono)', fontSize: 11 }} />
              <Bar dataKey="count" fill={CHART_PRIMARY} radius={[3, 3, 0, 0]} maxBarSize={20} fillOpacity={0.85} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {showHistorical && historicalCount && (
        <div className="mt-3 pt-3 border-t border-default">
          <div className="flex items-center justify-between text-2xs text-tertiary uppercase tracking-wider mb-1.5">
            <span>Historical</span>
            <span className="font-mono tabular-nums">{historicalCount.total} signals</span>
          </div>
          <div className="flex gap-0.5 h-4">
            {Object.entries(historicalCount.buckets)
              .sort(([a], [b]) => parseInt(a) - parseInt(b))
              .map(([range, count]) => (
                <div
                  key={range}
                  className="flex-1 rounded-sm bg-gov-green-muted relative overflow-hidden"
                  title={`${range}: ${count} signals`}
                >
                  <div
                    className="absolute bottom-0 left-0 right-0 bg-gov-green/40 rounded-sm transition-all duration-300"
                    style={{ height: `${(count / historicalCount.total) * 100}%` }}
                  />
                </div>
              ))}
          </div>
          <div className="flex justify-between text-[8px] text-muted mt-1 font-mono">
            {Object.entries(historicalCount.buckets)
              .sort(([a], [b]) => parseInt(a) - parseInt(b))
              .map(([range]) => (
                <span key={range}>{range}</span>
              ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
