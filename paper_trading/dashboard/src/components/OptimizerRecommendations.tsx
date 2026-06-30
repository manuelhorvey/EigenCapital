import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
import EmptyState from './ui/EmptyState'

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

export default function OptimizerRecommendations() {
  const { data: report, isLoading } = useQuery<DriftReport>({
    queryKey: ['optimization'],
    queryFn: () => fetchApi<DriftReport>('/optimization.json'),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 1,
  })

  const cards = useMemo(() => {
    if (!report) return null
    const items: { label: string; value: string; sub: string; accent: string }[] = []

    items.push({
      label: 'Assets Checked',
      value: report.n_assets.toString(),
      sub: `${report.flagged_assets.length} flagged, ${report.healthy_assets.length} healthy`,
      accent: '#3b82f6',
    })

    for (const flagged of report.flagged_assets.slice(0, 5)) {
      items.push({
        label: flagged.asset,
        value: `${(flagged.wr_margin >= 0 ? '+' : '')}${(flagged.wr_margin * 100).toFixed(1)}%`,
        sub: `${flagged.trend} · ${flagged.n_trades} trades · ${flagged.flag_reason}`,
        accent: '#ef4444',
      })
    }

    return items.length > 0 ? items : null
  }, [report])

  if (isLoading) {
    return (
      <Panel padding="md">
        <EmptyState message="Loading optimization data..." compact />
      </Panel>
    )
  }

  if (!report || report.flagged_assets.length === 0) {
    return (
      <Panel padding="md">
        <EmptyState message="All assets healthy — no optimization flags" compact />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
      {cards?.map(c => (
        <StatCard key={c.label} label={c.label} value={c.value} sub={c.sub} accent={c.accent} />
      ))}
    </div>
  )
}
