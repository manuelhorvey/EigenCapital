import { useAttributionBundle } from '../../hooks/useAttributionBundle'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { Skeleton } from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import Gauge from '../ui/Gauge'

export default function FillQualityGauge() {
  const { data: bundle, isPending } = useAttributionBundle()
  const data = bundle?.executionQuality

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Fill Quality" accent="purple" />
        <div className="flex gap-4 justify-center py-4">
          <Skeleton className="h-20 w-20 rounded-full" />
          <Skeleton className="h-20 w-20 rounded-full" />
        </div>
      </Panel>
    )
  }

  const byAsset = data?.by_asset ?? {}
  const assets = Object.keys(byAsset)
  if (assets.length === 0) return null

  const hasFqi = assets.some(a => byAsset[a].fqi != null)
  const hasEis = assets.some(a => byAsset[a].eis != null)
  if (!hasFqi && !hasEis) {
    return (
      <Panel padding="md">
        <SectionHeader title="Fill Quality" accent="purple" />
        <EmptyState message="Waiting for execution data…" compact />
      </Panel>
    )
  }

  const avgFqi = assets.reduce((s, a) => s + (byAsset[a].fqi ?? 0), 0) / assets.length
  const avgFillRatio = assets.reduce((s, a) => s + byAsset[a].avg_fill_ratio, 0) / assets.length

  return (
    <Panel padding="md">
      <SectionHeader title="Fill Quality" accent="purple" />
      <div className="flex items-center justify-center gap-6 py-2">
        <Gauge label="Avg FQI" value={avgFqi} />
        <Gauge label="Fill Ratio" value={avgFillRatio} />
      </div>
      <div className="grid grid-cols-2 gap-2 text-2xs text-tertiary mt-2">
        {assets.map(a => (
          <div key={a} className="flex justify-between">
            <span className="font-mono text-secondary">{a}</span>
            <span>FQI={((byAsset[a].fqi ?? 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
