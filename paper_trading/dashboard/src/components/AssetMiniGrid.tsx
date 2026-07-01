import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import AssetCard from './AssetCard'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import type { AssetState } from '../types/portfolio'

function signalRank(signal: string): number {
  switch (signal) {
    case 'BUY': return 0
    case 'FLAT': return 1
    case 'SELL': return 2
    default: return 3
  }
}

function getSortSignal(asset: AssetState): string {
  return asset.final_signal ??
    (asset.sell_only && asset.last_signal?.signal === 'BUY' ? 'FLAT' : asset.last_signal?.signal) ??
    'FLAT'
}

interface AssetMiniGridProps {
  /** Show only assets with an open position. */
  openOnly?: boolean
}

export default function AssetMiniGrid({ openOnly }: AssetMiniGridProps) {
  const { data: assets, isPending } = useSystemSnapshot(systemSelectors.assets)

  const sorted = useMemo(() => {
    if (!assets) return []
    const entries = Object.entries(assets).filter(
      ([_, a]) => !openOnly || a.metrics.position != null,
    )
    return entries
      .sort(([aName, aData], [bName, bData]) => {
        const aRank = signalRank(getSortSignal(aData))
        const bRank = signalRank(getSortSignal(bData))
        if (aRank !== bRank) return aRank - bRank
        return aName.localeCompare(bName)
      })
      .map(([name]) => name)
  }, [assets, openOnly])

  const title = openOnly ? 'Open Positions' : 'Asset Overview'

  if (isPending) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-lg" shimmer />
        ))}
      </div>
    )
  }

  if (sorted.length === 0) {
    return (
      <div className="py-2">
        <SectionHeader title={title} accent="neutral" />
        <EmptyState message={openOnly ? 'No open positions' : 'No asset data yet'} compact />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader title={title} accent="neutral" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 mt-2">
        {sorted.map(name => (
          <AssetCard key={name} name={name} density="compact" />
        ))}
      </div>
    </div>
  )
}
