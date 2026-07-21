import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
import EmptyState from './ui/EmptyState'
import { gridMetric4, GRID_GAP } from '../design/grid'

interface DriftReport {
  generated_at: string
  n_assets: number
  flagged_assets: DriftAsset[]
  healthy_assets: DriftAsset[]
}

interface DriftAsset {
  asset: string
  n_trades: number
  breakeven_wr: number
  win_rate: number
  wr_margin: number
  trend: string
  flagged: boolean
  flag_reason: string
}

/** Win-rate drift optimizer panel showing flagged and healthy assets with margin details. */
export default function OptimizerRecommendations() {
  const { data: report, isLoading } = useQuery<DriftReport>({
    queryKey: ['optimization'],
    queryFn: () => fetchApi<DriftReport>('/optimization.json'),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 1,
  })

  const flags = report?.flagged_assets
  const healthy = report?.healthy_assets

  const cards = useMemo(() => {
    if (!report || !flags) return null
    const items: { label: string; value: string; sub: string; accent: string }[] = []

    items.push({
      label: 'Assets Checked',
      value: (report.n_assets ?? (flags.length + (healthy ?? []).length)).toString(),
      sub: `${flags.length} flagged, ${(healthy ?? []).length} healthy`,
      accent: 'var(--color-accent-blue)',
    })

    for (const flagged of flags.slice(0, 5)) {
      items.push({
        label: flagged.asset,
        value: `${(flagged.wr_margin >= 0 ? '+' : '')}${(flagged.wr_margin * 100).toFixed(1)}%`,
        sub: `${flagged.trend} · ${flagged.n_trades} trades · ${flagged.flag_reason}`,
        accent: 'var(--color-signal-short)',
      })
    }

    return items.length > 0 ? items : null
  }, [report, flags, healthy])

  if (isLoading) {
    return (
      <Panel padding="md">
        <EmptyState message="Loading optimization data..." compact />
      </Panel>
    )
  }

  if (!report || !flags || flags.length === 0) {
    return (
      <Panel padding="md">
        <EmptyState message="All assets healthy — no optimization flags" compact />
      </Panel>
    )
  }

  return (
    <div className={`${gridMetric4()} ${GRID_GAP}`}>
      {cards?.map(c => (
        <StatCard key={c.label} label={c.label} value={c.value} sub={c.sub} accent={c.accent} />
      ))}
    </div>
  )
}
