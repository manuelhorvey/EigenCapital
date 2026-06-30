import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import AssetMiniCard from './AssetMiniCard'
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

export default function AssetMiniGrid() {
  const { data: assets, isPending } = useSystemSnapshot(systemSelectors.assets)

  const sorted = useMemo(() => {
    if (!assets) return []
    return Object.entries(assets)
      .sort(([aName, aData], [bName, bData]) => {
        const aRank = signalRank(getSortSignal(aData))
        const bRank = signalRank(getSortSignal(bData))
        if (aRank !== bRank) return aRank - bRank
        return aName.localeCompare(bName)
      })
      .map(([name]) => name)
  }, [assets])

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
        <SectionHeader title="Asset Overview" accent="neutral" />
        <EmptyState message="No asset data yet" compact />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader title="Asset Overview" accent="neutral" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 mt-2">
        {sorted.map(name => (
          <AssetMiniCard key={name} name={name} />
        ))}
      </div>
    </div>
  )
}
