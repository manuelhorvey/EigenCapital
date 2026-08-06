import { useAttributionBundle } from '../../hooks/useAttributionBundle'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import StatCard from '../ui/StatCard'
import { Skeleton } from '../ui/Skeleton'
import PanelFallback from '../ui/PanelFallback'
import EmptyState from '../ui/EmptyState'

export default function ExecutionQualityStrip() {
  const { data: bundle, isPending, isError, error, refetch } = useAttributionBundle()
  const data = bundle?.executionQuality

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Execution Quality" accent="blue" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </Panel>
    )
  }

  if (isError) {
    return <PanelFallback title="Execution Quality" error={error} onRetry={() => refetch()} />
  }

  const byAsset = data?.by_asset ?? {}
  const assets = Object.keys(byAsset)
  if (assets.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Execution Quality" accent="blue" />
        <EmptyState message="No execution quality data yet" compact />
      </Panel>
    )
  }

  const avgEis = assets.reduce((s, a) => s + (byAsset[a].eis ?? 0), 0) / assets.length
  const avgFqi = assets.reduce((s, a) => s + (byAsset[a].fqi ?? 0), 0) / assets.length
  const worstSlip = Math.max(...assets.map(a => byAsset[a].avg_entry_slippage_bps))
  const avgFill = assets.reduce((s, a) => s + byAsset[a].avg_fill_ratio, 0) / assets.length

  return (
    <Panel padding="md">
      <SectionHeader title="Execution Quality" accent="blue" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard variant="kpi" label="Avg EIS" value={(avgEis * 100).toFixed(1) + '%'} accent={avgEis >= 0.7 ? 'green' : 'yellow'} />
        <StatCard variant="kpi" label="Avg FQI" value={(avgFqi * 100).toFixed(1) + '%'} accent={avgFqi >= 0.8 ? 'green' : 'yellow'} />
        <StatCard variant="kpi" label="Worst Slippage" value={worstSlip.toFixed(1) + ' bps'} accent={worstSlip > 10 ? 'red' : 'green'} />
        <StatCard variant="kpi" label="Fill Rate" value={(avgFill * 100).toFixed(1) + '%'} accent={avgFill >= 0.95 ? 'green' : 'yellow'} />
      </div>
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-2xs text-tertiary">
        {assets.map(a => (
          <div key={a} className="flex items-center gap-1.5">
            <span className="font-mono font-medium text-secondary">{a}</span>
            <span>EIS={((byAsset[a].eis ?? 0) * 100).toFixed(0)}%</span>
            <span>FQI={((byAsset[a].fqi ?? 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
